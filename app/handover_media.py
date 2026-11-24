"""Private S3 handover media: bounded uploads, server inspection, immutable final keys."""
import hashlib
import json
import subprocess
import tempfile
from threading import Lock

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.errors import Problem

VIDEO_LIMIT = 50 * 1024 * 1024
PHOTO_LIMIT = 10 * 1024 * 1024
MIME_EXTENSIONS = {"video/mp4": "mp4", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def inspect_file(path, content_type, ffprobe="ffprobe"):
    try:
        result = subprocess.run([ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe",
            "-show_entries", "format=format_name,duration:stream=codec_name,codec_type,width,height,duration",
            "-of", "json", path], capture_output=True, timeout=15, check=True)
        value = json.loads(result.stdout)
    except FileNotFoundError:
        raise Problem(503, "MEDIA_VALIDATION_UNAVAILABLE") from None
    except (subprocess.SubprocessError, ValueError):
        raise Problem(422, "MEDIA_TYPE_NOT_ALLOWED") from None
    videos = [s for s in value.get("streams", []) if s.get("codec_type") == "video"]
    if len(videos) != 1 or not videos[0].get("width") or not videos[0].get("height"):
        raise Problem(422, "MEDIA_TYPE_NOT_ALLOWED")
    stream = videos[0]
    if content_type == "video/mp4":
        if "mp4" not in value.get("format", {}).get("format_name", "").split(","):
            raise Problem(422, "MEDIA_TYPE_NOT_ALLOWED")
        try:
            duration = max(float(value.get("format", {}).get("duration", 0)), float(stream.get("duration", 0)))
        except (ValueError, TypeError):
            raise Problem(422, "MEDIA_TYPE_NOT_ALLOWED") from None
        if not 0 < duration <= 10:
            raise Problem(422, "VIDEO_DURATION_EXCEEDED")
        return duration
    codecs = {"image/jpeg": "mjpeg", "image/png": "png", "image/webp": "webp"}
    formats = {"image/jpeg": {"jpeg_pipe", "image2", "image2pipe"},
               "image/png": {"png_pipe", "image2", "image2pipe"}, "image/webp": {"webp_pipe", "image2", "image2pipe"}}
    if (stream.get("codec_name") != codecs.get(content_type) or
            not formats.get(content_type, set()).intersection(value.get("format", {}).get("format_name", "").split(","))):
        raise Problem(422, "MEDIA_TYPE_NOT_ALLOWED")
    return None


class HandoverMedia:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.bucket = settings.s3_image_bucket
        self.region = settings.s3_image_region
        self.ttl = settings.s3_image_url_ttl_seconds
        self._client, self._lock = client, Lock()

    def client(self):
        if not self.bucket or not self.region:
            raise Problem(503, "MEDIA_STORAGE_NOT_CONFIGURED")
        with self._lock:
            if self._client is None:
                self._client = boto3.session.Session().client("s3", region_name=self.region,
                    config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=15,
                                  retries={"max_attempts": 2}))
        return self._client

    def prepare(self, key, content_type, size):
        limit = VIDEO_LIMIT if content_type == "video/mp4" else PHOTO_LIMIT
        if size > limit:
            raise Problem(413, "MEDIA_TOO_LARGE")
        try:
            return self.client().generate_presigned_post(Bucket=self.bucket, Key=key,
                Fields={"Content-Type": content_type}, Conditions=[{"Content-Type": content_type},
                    ["content-length-range", size, size]], ExpiresIn=self.ttl)
        except (ClientError, BotoCoreError):
            raise Problem(503, "MEDIA_STORAGE_UNAVAILABLE") from None

    def finalize(self, slot, final_key):
        """Pin the inspected source and the copied bytes to the same S3 object."""
        client = self.client()
        try:
            head = client.head_object(Bucket=self.bucket, Key=slot["temporaryKey"])
            size, mime = head["ContentLength"], slot["contentType"]
            if size != slot["sizeBytes"]:
                raise Problem(422, "MEDIA_SIZE_MISMATCH")
            if size > (VIDEO_LIMIT if mime == "video/mp4" else PHOTO_LIMIT):
                raise Problem(413, "MEDIA_TOO_LARGE")
            args = {"Bucket": self.bucket, "Key": slot["temporaryKey"], "IfMatch": head["ETag"]}
            if head.get("VersionId"):
                args["VersionId"] = head["VersionId"]
            response = client.get_object(**args)
            digest, received = hashlib.sha256(), 0
            try:
                with tempfile.NamedTemporaryFile(suffix="." + MIME_EXTENSIONS[mime]) as file:
                    while block := response["Body"].read(64 * 1024):
                        received += len(block)
                        if received > size:
                            raise Problem(422, "MEDIA_SIZE_MISMATCH")
                        digest.update(block)
                        file.write(block)
                    if received != size:
                        raise Problem(422, "MEDIA_SIZE_MISMATCH")
                    file.flush()
                    duration = inspect_file(file.name, mime, self.settings.media_ffprobe)
            finally:
                response["Body"].close()
            source = {"Bucket": self.bucket, "Key": slot["temporaryKey"]}
            if head.get("VersionId"):
                source["VersionId"] = head["VersionId"]
            copied = client.copy_object(Bucket=self.bucket, Key=final_key, CopySource=source,
                CopySourceIfMatch=head["ETag"], MetadataDirective="REPLACE", ContentType=mime,
                Metadata={"sha256": digest.hexdigest()}, ServerSideEncryption="AES256")
            return {"durationSeconds": duration, "sha256": digest.hexdigest(),
                    "objectVersion": copied.get("VersionId"), "key": final_key}
        except ClientError as error:
            if str(error.response.get("Error", {}).get("Code")) in ("404", "NoSuchKey", "NotFound"):
                raise Problem(409, "MEDIA_UPLOAD_NOT_FOUND") from None
            raise Problem(503, "MEDIA_STORAGE_UNAVAILABLE") from None
        except BotoCoreError:
            raise Problem(503, "MEDIA_STORAGE_UNAVAILABLE") from None

    def url(self, key):
        if not key.startswith("handover-media/") or any(p in (".", "..") for p in key.split("/")):
            raise Problem(503, "MEDIA_STORAGE_INVALID")
        try:
            return self.client().generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=self.ttl, HttpMethod="GET")
        except (BotoCoreError, ClientError):
            raise Problem(503, "MEDIA_STORAGE_UNAVAILABLE") from None

    def close(self):
        if self._client is not None:
            self._client.close()
