"""Where ticket attachments live, what is allowed in, and who may fetch them.

Three decisions worth stating.

*On disk, not in the database.* A screen recording of a fault is 50-200 MB.
MySQL's MEDIUMBLOB stops at 16 MB, every byte travels through
max_allowed_packet, and the nightly backup swells with video nobody needs to
restore. The row keeps the metadata; the bytes sit in ATTACHMENT_DIR.

*The file says what it is, not the browser.* The Content-Type on an upload is
whatever the client claims, and the extension is whatever the file was renamed
to. Both are checked against the first bytes of the file, and an upload whose
contents do not match an allowed type is refused. An HTML page renamed to
.png and served inline is a script running under this site's name.

*Signed links, not open ones.* An <img> or <video> tag cannot send a bearer
token, so the page cannot simply point at an authenticated URL. The API hands
out a link carrying a short-lived HMAC signature instead, and only to someone
already allowed to see the ticket. The link inherits their permission and
expires; it is not a standing key to the file.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime, timezone

from fastapi import UploadFile

from .. import config

CHUNK = 1024 * 1024

# ------------------------------------------------------------ what is allowed
# (kind, canonical mime, extensions that may carry it)
_IMAGE = "image"
_VIDEO = "video"
_DOC = "document"


def _sniff(head: bytes, name: str) -> tuple[str, str] | None:
    """Kind and mime from the file's own first bytes, or None if not allowed."""
    ext = os.path.splitext(name or "")[1].lower()
    h = head

    # images
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return _IMAGE, "image/png"
    if h.startswith(b"\xff\xd8\xff"):
        return _IMAGE, "image/jpeg"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return _IMAGE, "image/gif"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return _IMAGE, "image/webp"
    # ISO base media: HEIC photos and MP4 / MOV video share the ftyp box
    if h[4:8] == b"ftyp":
        brand = h[8:12]
        if brand in (b"heic", b"heix", b"mif1", b"msf1", b"hevc"):
            return _IMAGE, "image/heic"
        if brand == b"qt  ":
            return _VIDEO, "video/quicktime"
        return _VIDEO, "video/mp4"
    if h.startswith(b"\x1a\x45\xdf\xa3"):          # Matroska / WebM
        return _VIDEO, "video/webm"
    if h[:4] == b"RIFF" and h[8:12] == b"AVI ":
        return _VIDEO, "video/x-msvideo"

    # documents
    if h.startswith(b"%PDF-"):
        return _DOC, "application/pdf"
    if h.startswith(b"PK\x03\x04"):
        # Office files are zip containers; the extension tells them apart
        return _DOC, {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }.get(ext, "application/zip")
    if h.startswith(b"\xd0\xcf\x11\xe0"):          # legacy .doc / .xls
        return _DOC, "application/msword" if ext == ".doc" else "application/vnd.ms-excel"

    # plain text, only under a text extension and only if it really is text
    if ext in (".txt", ".log", ".csv", ".json", ".xml", ".md"):
        sample = h[:4096]
        if b"\x00" not in sample:
            try:
                sample.decode("utf-8")
            except UnicodeDecodeError:
                return None
            low = sample.lower()
            # text that is really markup would render as a page if served inline
            if b"<script" in low or b"<html" in low or b"<svg" in low:
                return None
            return _DOC, {".csv": "text/csv", ".json": "application/json",
                          ".xml": "application/xml"}.get(ext, "text/plain")
    return None


ALLOWED_HUMAN = ("images (JPG, PNG, GIF, WebP, HEIC), video (MP4, MOV, WebM, AVI), "
                 "PDF, Word, Excel, PowerPoint, ZIP, and plain text or CSV")


class FileRefused(ValueError):
    pass


def limit_for(kind: str) -> int:
    mb = config.MAX_VIDEO_MB if kind == _VIDEO else config.MAX_FILE_MB
    return mb * 1024 * 1024


# ---------------------------------------------------------------- storing
async def save_upload(f: UploadFile) -> dict:
    """Stream one upload to disk, enforcing type and size as it arrives.

    Nothing is held in memory beyond one chunk. The size limit is enforced
    while reading, so a 2 GB upload is cut off at the limit rather than being
    read in full and then refused.
    """
    name = (f.filename or "attachment").replace("\\", "/").split("/")[-1][:255] or "attachment"
    head = await f.read(8192)
    if not head:
        raise FileRefused(f'"{name}" is empty.')
    sniffed = _sniff(head, name)
    if sniffed is None:
        raise FileRefused(
            f'"{name}" is not a type that can be attached. Allowed: {ALLOWED_HUMAN}.')
    kind, mime = sniffed
    cap = limit_for(kind)

    now = datetime.now(timezone.utc)
    key = f"{now:%Y/%m}/{uuid.uuid4().hex}"
    path = os.path.join(config.ATTACHMENT_DIR, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    digest = hashlib.sha256()
    size = 0
    try:
        with open(tmp, "wb") as out:
            chunk = head
            while chunk:
                size += len(chunk)
                if size > cap:
                    raise FileRefused(
                        f'"{name}" is larger than {cap // (1024 * 1024)} MB, the limit '
                        f'for {"a video" if kind == _VIDEO else "this kind of file"}.')
                digest.update(chunk)
                out.write(chunk)
                chunk = await f.read(CHUNK)
        os.replace(tmp, path)        # only a complete file ever appears under its name
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return {"file_name": name, "content_type": mime, "kind": kind,
            "size_bytes": size, "storage_key": key, "sha256": digest.hexdigest()}


def path_for(storage_key: str) -> str:
    """Resolve a key to a path, refusing anything that climbs out of the store."""
    root = os.path.realpath(config.ATTACHMENT_DIR)
    p = os.path.realpath(os.path.join(root, storage_key))
    if not p.startswith(root + os.sep):
        raise FileRefused("That attachment is not in the store.")
    return p


def remove(storage_key: str | None) -> None:
    if not storage_key:
        return
    try:
        os.remove(path_for(storage_key))
    except (OSError, FileRefused):
        pass


# ------------------------------------------------------------ signed links
def _sig(att_id: int, exp: int) -> str:
    msg = f"att:{att_id}:{exp}".encode()
    return hmac.new(config.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()[:32]


def signed_query(att_id: int) -> str:
    exp = int(time.time()) + config.ATTACHMENT_LINK_MINUTES * 60
    return f"exp={exp}&sig={_sig(att_id, exp)}"


def signature_ok(att_id: int, exp: int | None, sig: str | None) -> bool:
    if not exp or not sig or exp < time.time():
        return False
    return hmac.compare_digest(sig, _sig(att_id, exp))


# Types a browser may show in the page. Anything else is always downloaded,
# never rendered, whatever the file claims to be.
INLINE_KINDS = {_IMAGE, _VIDEO}
INLINE_MIMES = {"application/pdf"}
