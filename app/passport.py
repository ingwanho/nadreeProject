"""Private storage and validation helpers for masked passport images.

The API never accepts a source passport image as a successful upload. Clients
must submit an already-redacted JPEG or PNG and explicitly acknowledge that
fact. The local filesystem adapter is intended for development and isolated
tests; production should provide a durable encrypted object-store adapter.
"""

import base64
import binascii
import os
import secrets
from pathlib import Path

from app.errors import Problem


MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png"}
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PassportStorage:
    """Small filesystem adapter with opaque, server-generated object keys."""

    def __init__(self, root: str = ""):
        self.root = Path(root).expanduser() if root else None

    @property
    def configured(self):
        return self.root is not None

    def _path(self, key: str):
        if not self.root or not key or Path(key).is_absolute() or ".." in Path(key).parts:
            raise Problem(503, "PASSPORT_STORAGE_NOT_CONFIGURED")
        root = self.root.resolve()
        path = (root / key).resolve()
        if path != root and root not in path.parents:
            raise Problem(503, "PASSPORT_STORAGE_NOT_CONFIGURED")
        return path

    def write(self, key: str, data: bytes):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
        try:
            with temporary.open("xb") as stream:
                os.chmod(temporary, 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def read(self, key: str):
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise Problem(503, "PASSPORT_STORAGE_OBJECT_MISSING") from None

    def delete(self, key: str):
        path = self._path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def decode_masked_image(encoded: str, content_type: str, masked: bool):
    if not masked:
        raise Problem(422, "PASSPORT_MASK_REQUIRED")
    if content_type not in IMAGE_TYPES:
        raise Problem(422, "PASSPORT_IMAGE_TYPE_INVALID")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise Problem(422, "PASSPORT_IMAGE_INVALID") from None
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise Problem(422, "PASSPORT_IMAGE_SIZE_INVALID")
    if content_type == "image/jpeg":
        if not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9"):
            raise Problem(422, "PASSPORT_IMAGE_INVALID")
        return _strip_jpeg_metadata(data)
    if not data.startswith(_PNG_SIGNATURE) or b"IEND" not in data:
        raise Problem(422, "PASSPORT_IMAGE_INVALID")
    return _strip_png_metadata(data)


def passport_key(spot_master_id: str, rental_contract_id: str, content_type: str):
    return "passport/{}/{}/{}{}".format(spot_master_id, rental_contract_id, secrets.token_urlsafe(24), IMAGE_TYPES[content_type])


def _strip_jpeg_metadata(data: bytes):
    """Drop JPEG APP1/COM metadata while preserving the encoded pixels."""
    output = bytearray(data[:2])
    position = 2
    while position < len(data):
        if data[position] != 0xFF:
            output.extend(data[position:])
            break
        marker_start = position
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            break
        marker = data[position]
        position += 1
        if marker == 0xDA:  # Start of scan: the remainder contains compressed pixels.
            output.extend(data[marker_start:])
            break
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            output.extend(data[marker_start:position])
            continue
        if position + 2 > len(data):
            raise Problem(422, "PASSPORT_IMAGE_INVALID")
        length = int.from_bytes(data[position:position + 2], "big")
        end = position + length
        if length < 2 or end > len(data):
            raise Problem(422, "PASSPORT_IMAGE_INVALID")
        if marker not in (0xE1, 0xFE):
            output.extend(data[marker_start:end])
        position = end
    return bytes(output)


def _strip_png_metadata(data: bytes):
    """Drop textual/EXIF PNG chunks without decoding the image pixels."""
    output = bytearray(data[:8])
    position = 8
    found_end = False
    while position < len(data):
        if position + 12 > len(data):
            raise Problem(422, "PASSPORT_IMAGE_INVALID")
        length = int.from_bytes(data[position:position + 4], "big")
        end = position + 12 + length
        if end > len(data):
            raise Problem(422, "PASSPORT_IMAGE_INVALID")
        chunk_type = data[position + 4:position + 8]
        if chunk_type not in (b"eXIf", b"tEXt", b"zTXt", b"iTXt"):
            output.extend(data[position:end])
        position = end
        if chunk_type == b"IEND":
            found_end = True
            break
    if not found_end:
        raise Problem(422, "PASSPORT_IMAGE_INVALID")
    return bytes(output)
