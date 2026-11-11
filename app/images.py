"""Resolve public image URLs and read-only URLs for the dedicated S3 image bucket."""
import logging
from threading import Lock
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


class ImageURLs:
    def __init__(self, settings, client=None):
        self.bucket = settings.s3_image_bucket
        self.region = settings.s3_image_region
        self.ttl = settings.s3_image_url_ttl_seconds
        self._client = client
        self._lock = Lock()

    def model_url(self, key):
        return self._url(key, "models/")

    def vehicle_url(self, key):
        return self._url(key, "vehicles/")

    def _url(self, key, prefix):
        if not key or any(ord(char) < 32 or ord(char) == 127 for char in key):
            return None
        if key.lower().startswith("https://"):
            try:
                parsed = urlsplit(key)
                return key if parsed.hostname and parsed.username is None and parsed.password is None else None
            except ValueError:
                return None
        # Do not normalize S3 keys or sign paths outside the image namespaces.
        if (not self.bucket or not self.region or not key.startswith(prefix)
                or key == prefix or any(part in (".", "..") for part in key.split("/"))
                or len(key.encode("utf-8")) > 1024):
            return None
        try:
            with self._lock:
                if self._client is None:
                    self._client = boto3.session.Session().client("s3", region_name=self.region,
                        config=Config(signature_version="s3v4"))
            return self._client.generate_presigned_url("get_object",
                Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=self.ttl, HttpMethod="GET")
        except (BotoCoreError, ClientError) as error:
            # Signing failures must not fail rental queries or expose credentials/URLs.
            logger.warning("S3 image URL unavailable (%s)", type(error).__name__)
            return None

    def close(self):
        if self._client is not None:
            self._client.close()
