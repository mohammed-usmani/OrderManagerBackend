"""Cloudinary image upload for menu-item photos.

Render's filesystem is ephemeral, so uploaded files must live in object
storage. Configured via the single CLOUDINARY_URL env var
(cloudinary://<key>:<secret>@<cloud>). When unset, upload is disabled and the
admin can still paste an external image URL.
"""

import cloudinary
import cloudinary.uploader

from config import CLOUDINARY_URL

UPLOAD_FOLDER = "saffron-smoke/menu"
_configured = False


def upload_enabled() -> bool:
    return bool(CLOUDINARY_URL)


def _ensure_config() -> None:
    global _configured
    if _configured:
        return
    if not CLOUDINARY_URL:
        raise RuntimeError("CLOUDINARY_URL not set — image upload is disabled.")
    cloudinary.config(cloudinary_url=CLOUDINARY_URL, secure=True)
    _configured = True


def upload_image(file) -> str:
    """Upload an image (bytes or file-like) and return its hosted HTTPS URL."""
    _ensure_config()
    result = cloudinary.uploader.upload(
        file, folder=UPLOAD_FOLDER, resource_type="image"
    )
    return result["secure_url"]
