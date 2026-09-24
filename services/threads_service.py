import time
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Dict, Any

from config.settings import settings
from config.logger import logger
from services.alert_service import alert_service


class ThreadsService:
    """Production Meta Threads Graph API client with image/text support, polling, idempotency, and token lifecycle management."""

    def __init__(self):
        self.api_url = settings.THREADS_API_BASE_URL.rstrip("/")
        self.user_id = settings.THREADS_USER_ID

    @property
    def access_token(self) -> str:
        return settings.THREADS_ACCESS_TOKEN.get_secret_value()

    def verify_credentials(self) -> bool:
        """Verifies Threads API credentials against the /me endpoint."""
        if settings.DRY_RUN and not self.access_token:
            logger.info("[DRY RUN] Credentials verification bypassed (no token configured).")
            return True

        url = f"{self.api_url}/me?fields=id,username&access_token={self.access_token}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=20.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    logger.info(f"Connected to Threads API as user: {data.get('username', 'unknown')}")
                    return True
        except Exception as e:
            logger.error(f"Threads credentials verification failed: {e}")
        return False

    def get_recent_posts(self, hours: int = 6) -> List[Dict[str, Any]]:
        """
        Retrieves user's recent posts from Threads within the lookback window.
        Used for runtime idempotency verification.
        """
        if settings.DRY_RUN:
            logger.info(f"[DRY RUN] Querying recent posts (lookback: {hours}h).")
            return []

        url = f"{self.api_url}/me/threads?fields=id,media_type,text,timestamp&limit=20&access_token={self.access_token}"
        recent = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=20.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode()).get("data", [])
                    for post in data:
                        ts_str = post.get("timestamp")
                        if ts_str:
                            try:
                                dt = datetime.fromisoformat(ts_str.replace("+0000", "+00:00"))
                                if dt >= cutoff:
                                    recent.append(post)
                            except ValueError:
                                recent.append(post)
                        else:
                            recent.append(post)
        except Exception as e:
            logger.error(f"Exception fetching recent threads: {e}")

        return recent

    def _wait_for_container_status(self, container_id: str, max_timeout: int = 40, poll_interval: int = 2) -> bool:
        """Polls container status until FINISHED, ERROR, or timeout."""
        url = f"{self.api_url}/{container_id}?fields=status,error_message&access_token={self.access_token}"
        elapsed = 0
        while elapsed < max_timeout:
            time.sleep(poll_interval)
            elapsed += poll_interval
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=15.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode())
                        status = data.get("status")
                        if status == "FINISHED":
                            logger.info(f"Container {container_id} is FINISHED in ~{elapsed}s.")
                            return True
                        elif status == "ERROR":
                            logger.error(f"Container {container_id} processing failed: {data.get('error_message')}")
                            return False
            except Exception as e:
                logger.warning(f"Error checking container status: {e}")

        logger.warning(f"Container {container_id} timed out after {max_timeout}s.")
        return False

    def publish_post(
        self,
        text: str,
        image_url: Optional[str] = None,
        alt_text: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Publishes a post (IMAGE or TEXT) to Threads.
        Strictly enforces MAX_POST_CHARS = 470.
        If IMAGE container creation or processing fails, gracefully falls back to TEXT-ONLY.
        """
        if len(text) > settings.MAX_POST_CHARS:
            logger.error(f"Post exceeds MAX_POST_CHARS limit ({len(text)} > {settings.MAX_POST_CHARS}). Rejecting.")
            return False, None

        if settings.DRY_RUN:
            mode = "IMAGE" if image_url else "TEXT"
            logger.info(f"[DRY RUN] Would publish {mode} post ({len(text)} chars):\n{text}")
            return True, "DRY_RUN_POST_ID"

        create_url = f"{self.api_url}/{self.user_id}/threads"
        container_id = None
        media_type = "IMAGE" if image_url else "TEXT"

        # Attempt 1: Image container if URL provided
        if media_type == "IMAGE" and image_url:
            payload_dict = {
                "media_type": "IMAGE",
                "image_url": image_url,
                "text": text,
                "access_token": self.access_token
            }
            if alt_text:
                payload_dict["alt_text"] = alt_text

            payload = urllib.parse.urlencode(payload_dict).encode("utf-8")
            try:
                req = urllib.request.Request(create_url, data=payload, method="POST")
                with urllib.request.urlopen(req, timeout=30.0) as resp:
                    if resp.status == 200:
                        container_id = json.loads(resp.read().decode()).get("id")
            except Exception as e:
                logger.warning(f"Failed to create IMAGE container: {e}. Falling back to TEXT.")
                container_id = None

            # Poll image container readiness
            if container_id:
                ready = self._wait_for_container_status(container_id)
                if not ready:
                    logger.warning("Image container not ready/errored. Falling back to TEXT.")
                    container_id = None

        # Fallback to TEXT if IMAGE failed or was not requested
        if not container_id:
            text_payload = urllib.parse.urlencode({
                "media_type": "TEXT",
                "text": text,
                "access_token": self.access_token
            }).encode("utf-8")

            try:
                req = urllib.request.Request(create_url, data=text_payload, method="POST")
                with urllib.request.urlopen(req, timeout=30.0) as resp:
                    if resp.status == 200:
                        container_id = json.loads(resp.read().decode()).get("id")
                    else:
                        logger.error(f"Failed to create TEXT container: HTTP {resp.status}")
                        return False, None
            except Exception as e:
                logger.error(f"Exception creating TEXT container: {e}")
                return False, None

            # Poll text container
            if not self._wait_for_container_status(container_id, max_timeout=20):
                logger.error(f"TEXT container {container_id} failed readiness.")
                return False, None

        # Step: Publish Container
        publish_url = f"{self.api_url}/{self.user_id}/threads_publish"
        publish_payload = urllib.parse.urlencode({
            "creation_id": container_id,
            "access_token": self.access_token
        }).encode("utf-8")

        try:
            req = urllib.request.Request(publish_url, data=publish_payload, method="POST")
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                if resp.status == 200:
                    post_id = json.loads(resp.read().decode()).get("id")
                    logger.info(f"✅ Threads post published successfully! Post ID: {post_id}")
                    return True, post_id
                else:
                    logger.error(f"Publish container {container_id} failed: HTTP {resp.status}")
        except Exception as e:
            logger.error(f"Exception publishing container: {e}")

        return False, None

    def refresh_access_token_if_needed(self, last_refresh_iso: Optional[str]) -> Optional[str]:
        """
        Validates token age and refreshes only when token age is >= 7 days.
        Meta rule: Refreshing is forbidden if token age is < 24 hours.
        """
        if not self.access_token:
            return None

        now = datetime.now(timezone.utc)
        if last_refresh_iso:
            try:
                last_dt = datetime.fromisoformat(last_refresh_iso.replace("Z", "+00:00"))
                token_age_days = (now - last_dt).total_seconds() / 86400.0
                if token_age_days < 7.0:
                    logger.debug(f"Token is {token_age_days:.1f} days old (< 7 days). Refresh skipped.")
                    return None
                logger.info(f"Token is {token_age_days:.1f} days old. Initiating refresh...")
            except ValueError:
                logger.warning("Could not parse last_token_refresh timestamp. Proceeding with refresh check.")

        if settings.DRY_RUN:
            logger.info("[DRY RUN] Would refresh long-lived Threads access token.")
            return "DRY_RUN_NEW_TOKEN"

        url = f"{self.api_url}/refresh_access_token?grant_type=th_refresh_token&access_token={self.access_token}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    new_token = data.get("access_token")
                    expires_in = data.get("expires_in", 0)
                    logger.info(f"✅ Threads access token successfully refreshed! Valid for ~{expires_in // 86400} days.")
                    return new_token
        except Exception as e:
            err_msg = f"Threads token refresh exception: {e}"
            logger.error(err_msg)
            alert_service.send_telegram_alert(f"Critical Token Exception: {err_msg}")

        return None

    def get_post_insights(self, post_id: str) -> Optional[Dict[str, int]]:
        """
        Fetches metrics (views, likes, replies, reposts, quotes) for a given post.
        Best-effort operation: failure never blocks publishing.
        """
        if settings.DRY_RUN or not post_id or post_id == "DRY_RUN_POST_ID":
            return None

        url = f"{self.api_url}/{post_id}/insights?metric=views,likes,replies,reposts,quotes&access_token={self.access_token}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode()).get("data", [])
                    metrics = {}
                    for item in data:
                        name = item.get("name")
                        values = item.get("values", [])
                        if values:
                            metrics[name] = values[0].get("value", 0)
                    logger.info(f"📊 Insights collected for post {post_id}: {metrics}")
                    return metrics
        except Exception as e:
            logger.warning(f"Best-effort insights fetch skipped for {post_id}: {e}")

        return None


threads_service = ThreadsService()
