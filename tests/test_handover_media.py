"""Media safety checks plus optional real SDK traffic to the local S3 simulation."""
import base64
import hashlib
import io
import json
import os
from types import SimpleNamespace

import boto3
from botocore.config import Config
from botocore.response import StreamingBody
from botocore.stub import Stubber
import pytest

from app.errors import Problem
from app.handover_media import HandoverMedia, inspect_file

ETAG = '"synthetic-etag"'
SIMULATION_ENDPOINT = os.getenv("NADREE_TEST_S3_ENDPOINT")


def adapter(endpoint=None):
    settings = SimpleNamespace(s3_image_bucket="nadree-synthetic-test", s3_image_region="ap-northeast-2",
        s3_image_url_ttl_seconds=900, media_ffprobe="ffprobe")
    client = boto3.client("s3", region_name=settings.s3_image_region, endpoint_url=endpoint,
        aws_access_key_id="synthetic", aws_secret_access_key="synthetic-test-only",
        config=Config(signature_version="s3v4", retries={"max_attempts": 0}, s3={"addressing_style": "path"}))
    return HandoverMedia(settings, client)


def slot(key="handover-upload-tmp/test/file.mp4"):
    return {"temporaryKey": key, "contentType": "video/mp4", "sizeBytes": 4}


def test_upload_policy_binds_exact_size_type_and_key():
    media = adapter()
    prepared = media.prepare(slot()["temporaryKey"], "video/mp4", 4)
    policy = json.loads(base64.b64decode(prepared["fields"]["policy"]))
    assert ["content-length-range", 4, 4] in policy["conditions"]
    assert {"Content-Type": "video/mp4"} in policy["conditions"]
    assert {"key": slot()["temporaryKey"]} in policy["conditions"]
    with pytest.raises(Problem) as error:
        media.prepare("test", "image/png", 10 * 1024 * 1024 + 1)
    assert error.value.code == "MEDIA_TOO_LARGE"


def test_inspected_version_is_the_copied_version(monkeypatch):
    media = adapter()
    key = slot()["temporaryKey"]
    final = "handover-media/shop/handover/file.mp4"
    source = {"Bucket": media.bucket, "Key": key}
    copied = {**source, "VersionId": "source-version"}
    expected = hashlib.sha256(b"test").hexdigest()
    inspected = []

    def inspect(path, mime, binary):
        with open(path, "rb") as file:
            inspected.append(file.read())
        return 9.5

    monkeypatch.setattr("app.handover_media.inspect_file", inspect)
    with Stubber(media.client()) as stub:
        stub.add_response("head_object", {"ContentLength": 4, "ETag": ETAG, "VersionId": "source-version"}, source)
        stub.add_response("get_object", {"Body": StreamingBody(io.BytesIO(b"test"), 4)},
            {**source, "IfMatch": ETAG, "VersionId": "source-version"})
        stub.add_response("copy_object", {"CopyObjectResult": {"ETag": ETAG}, "VersionId": "final-version"},
            {"Bucket": media.bucket, "Key": final, "CopySource": copied, "CopySourceIfMatch": ETAG,
             "MetadataDirective": "REPLACE", "ContentType": "video/mp4", "Metadata": {"sha256": expected},
             "ServerSideEncryption": "AES256"})
        result = media.finalize(slot(), final)
        stub.assert_no_pending_responses()
    assert inspected == [b"test"]
    assert result == {"key": final, "durationSeconds": 9.5, "sha256": expected, "objectVersion": "final-version"}


@pytest.mark.parametrize("operation,code,http,expected", [
    ("head_object", "404", 404, "MEDIA_UPLOAD_NOT_FOUND"),
    ("head_object", "ServiceUnavailable", 503, "MEDIA_STORAGE_UNAVAILABLE"),
    ("get_object", "PreconditionFailed", 412, "MEDIA_STORAGE_UNAVAILABLE"),
])
def test_storage_failure_cannot_publish_media(operation, code, http, expected):
    media = adapter()
    with Stubber(media.client()) as stub:
        if operation != "head_object":
            stub.add_response("head_object", {"ContentLength": 4, "ETag": ETAG})
        stub.add_client_error(operation, service_error_code=code, http_status_code=http)
        with pytest.raises(Problem) as error:
            media.finalize(slot(), "handover-media/test/file.mp4")
        assert error.value.code == expected
        stub.assert_no_pending_responses()


def test_size_mismatch_stops_before_download():
    media = adapter()
    with Stubber(media.client()) as stub:
        stub.add_response("head_object", {"ContentLength": 5, "ETag": ETAG})
        with pytest.raises(Problem) as error:
            media.finalize(slot(), "handover-media/test/file.mp4")
        assert error.value.code == "MEDIA_SIZE_MISMATCH"
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("duration,expected", [("10", None), ("10.01", "VIDEO_DURATION_EXCEEDED"),
    ("0", "VIDEO_DURATION_EXCEEDED"), ("NaN", "VIDEO_DURATION_EXCEEDED")])
def test_duration_uses_server_probe_result(monkeypatch, duration, expected):
    payload = {"streams": [{"codec_type": "video", "width": 640, "height": 480, "duration": duration}],
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": duration}}
    def run(args, **kwargs):
        assert "-protocol_whitelist" in args and args[args.index("-protocol_whitelist") + 1] == "file,pipe"
        assert kwargs["timeout"] == 15
        return SimpleNamespace(stdout=json.dumps(payload))
    monkeypatch.setattr("app.handover_media.subprocess.run", run)
    if expected:
        with pytest.raises(Problem) as error:
            inspect_file("/synthetic.mp4", "video/mp4")
        assert error.value.code == expected
    else:
        assert inspect_file("/synthetic.mp4", "video/mp4") == 10


def test_missing_probe_fails_closed(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError()
    monkeypatch.setattr("app.handover_media.subprocess.run", missing)
    with pytest.raises(Problem) as error:
        inspect_file("/synthetic.mp4", "video/mp4")
    assert error.value.code == "MEDIA_VALIDATION_UNAVAILABLE"


@pytest.mark.parametrize("format_name,codec", [("mov,mp4", "png"), ("png_pipe", "mjpeg")])
def test_photo_container_and_codec_must_match(monkeypatch, format_name, codec):
    payload = {"streams": [{"codec_type": "video", "width": 20, "height": 20, "codec_name": codec}],
        "format": {"format_name": format_name}}
    monkeypatch.setattr("app.handover_media.subprocess.run", lambda *a, **k: SimpleNamespace(stdout=json.dumps(payload)))
    with pytest.raises(Problem) as error:
        inspect_file("/synthetic.png", "image/png")
    assert error.value.code == "MEDIA_TYPE_NOT_ALLOWED"


@pytest.mark.skipif(not SIMULATION_ENDPOINT, reason="Local S3 simulation not running")
@pytest.mark.parametrize("prefix,expected", [("success", None), ("missing", "MEDIA_UPLOAD_NOT_FOUND"),
    ("unavailable", "MEDIA_STORAGE_UNAVAILABLE")])
def test_real_sdk_against_local_s3_simulation(monkeypatch, prefix, expected):
    endpoint = SIMULATION_ENDPOINT
    assert endpoint.startswith(("http://127.0.0.1:", "http://localhost:"))
    media = adapter(endpoint)
    monkeypatch.setattr("app.handover_media.inspect_file", lambda *a: 9.5)
    try:
        if expected:
            with pytest.raises(Problem) as error:
                media.finalize(slot(prefix + "/file.mp4"), "handover-media/test/file.mp4")
            assert error.value.code == expected
        else:
            result = media.finalize(slot(prefix + "/file.mp4"), "handover-media/test/file.mp4")
            assert result["sha256"] == hashlib.sha256(b"test").hexdigest()
            assert result["objectVersion"] == "final-version-1"
    finally:
        media.close()
