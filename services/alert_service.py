import json
import urllib.request
from typing import Optional
from config.settings import settings
from config.logger import logger


class AlertService:
    """Handles operational alerting (Telegram) and dead-man's switch pings (Healthchecks.io)."""

    def __init__(self):
        self.telegram_token = settings.TELEGRAM_ALERT_BOT_TOKEN.get_secret_value()
        self.telegram_chat_id = settings.TELEGRAM_ALERT_CHAT_ID
        self.healthchecks_url = settings.HEALTHCHECKS_PING_URL

    async def ping_healthchecks(self, msg: str = "OK") -> bool:
        """Sends a success ping to Healthchecks.io."""
        if settings.DRY_RUN:
            logger.info(f"[DRY RUN] Would ping Healthchecks.io: {self.healthchecks_url}")
            return True

        if not self.healthchecks_url:
            logger.debug("No Healthchecks.io URL configured. Skipping ping.")
            return False

        try:
            req = urllib.request.Request(
                self.healthchecks_url,
                data=msg.encode("utf-8"),
                headers={"User-Agent": "EnglishInThreads/1.0"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                if resp.status == 200:
                    logger.info("✅ Healthchecks.io ping successful.")
                    return True
                else:
                    logger.warning(f"Healthchecks.io ping HTTP {resp.status}")
        except Exception as e:
            logger.warning(f"Healthchecks.io ping exception: {e}")
        return False

    async def send_telegram_alert(self, message: str) -> bool:
        """Sends an urgent operational failure alert to Telegram."""
        if not self.telegram_token or not self.telegram_chat_id:
            logger.warning("Telegram credentials not configured. Skipping alert.")
            return False

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = json.dumps({
            "chat_id": self.telegram_chat_id,
            "text": f"🚨 [English in Threads Alert]\n\n{message}",
            "parse_mode": "HTML"
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                if resp.status == 200:
                    logger.info("Telegram critical alert dispatched successfully.")
                    return True
                else:
                    logger.error(f"Telegram alert returned HTTP {resp.status}")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
        return False


alert_service = AlertService()
