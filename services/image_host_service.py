import time
import hashlib
import json
import base64
import urllib.request
import urllib.parse
from typing import Optional, Tuple

from config.settings import settings
from config.logger import logger


class ImageHostService:
    """
    Handles image uploading and automatic deletion using Cloudinary's REST API.
    Uses pure Python standard library for zero external dependency overhead.
    Gracefully degrades to None if Cloudinary is not configured or fails.
    """

    def __init__(self):
        self.cloud_name = settings.CLOUDINARY_CLOUD_NAME
        self.api_key = settings.CLOUDINARY_API_KEY
        self.api_secret = settings.CLOUDINARY_API_SECRET.get_secret_value()

    @property
    def is_configured(self) -> bool:
        return bool(self.cloud_name and self.api_key and self.api_secret)

    def upload_image(self, file_path: str) -> Optional[Tuple[str, str]]:
        """
        Uploads a local image to Cloudinary.
        Returns: (secure_url, public_id) or None if upload fails or is not configured.
        """
        if not self.is_configured:
            logger.info("Cloudinary credentials not configured. Skipping image upload (Text fallback).")
            return None

        try:
            with open(file_path, "rb") as f:
                img_data = f.read()

            base64_data = f"data:image/png;base64,{base64.b64encode(img_data).decode('utf-8')}"
            timestamp = str(int(time.time()))

            # Generate Cloudinary SHA1 signature
            # Parameters must be sorted alphabetically: "timestamp=..."
            to_sign = f"timestamp={timestamp}{self.api_secret}"
            signature = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()

            upload_url = f"https://api.cloudinary.com/v1_1/{self.cloud_name}/image/upload"
            payload = urllib.parse.urlencode({
                "file": base64_data,
                "api_key": self.api_key,
                "timestamp": timestamp,
                "signature": signature
            }).encode("utf-8")

            req = urllib.request.Request(upload_url, data=payload, method="POST")
            with urllib.request.urlopen(req, timeout=25.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    secure_url = data.get("secure_url")
                    public_id = data.get("public_id")
                    logger.info(f"✅ Image uploaded to Cloudinary CDN: {public_id}")
                    return secure_url, public_id
                else:
                    logger.warning(f"Cloudinary upload failed: HTTP {resp.status}")

        except Exception as e:
            logger.warning(f"Cloudinary upload exception: {e} (Graceful fallback to TEXT)")

        return None

    def delete_image(self, public_id: str) -> bool:
        """
        Deletes the uploaded image from Cloudinary to keep free storage clean.
        """
        if not self.is_configured or not public_id:
            return False

        try:
            timestamp = str(int(time.time()))
            to_sign = f"public_id={public_id}&timestamp={timestamp}{self.api_secret}"
            signature = hashlib.sha1(to_sign.encode("utf-8")).hexdigest()

            destroy_url = f"https://api.cloudinary.com/v1_1/{self.cloud_name}/image/destroy"
            payload = urllib.parse.urlencode({
                "public_id": public_id,
                "api_key": self.api_key,
                "timestamp": timestamp,
                "signature": signature
            }).encode("utf-8")

            req = urllib.request.Request(destroy_url, data=payload, method="POST")
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                if resp.status == 200:
                    logger.info(f"🗑️ Cleaned up temporary Cloudinary image: {public_id}")
                    return True
        except Exception as e:
            logger.warning(f"Failed to delete Cloudinary image {public_id}: {e}")

        return False


image_host_service = ImageHostService()
