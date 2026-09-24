import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import pytz

from config.settings import settings
from config.logger import logger


class CurriculumService:
    """
    Manages curriculum seed loading, weekday/slot mapping,
    anti-repetition cooldown (used_seed_ids), and dependent quiz answer resolution.
    """

    WEEKDAY_SLOT_MAP = {
        0: {"LUNCH": "LUNCH_COMMON_MISTAKE", "EVENING": "EVENING_EXPLANATION"},
        1: {"LUNCH": "LUNCH_TEXTBOOK_VS_NATIVE", "EVENING": "EVENING_CONTEXT_TEST"},
        2: {"LUNCH": "LUNCH_PREPOSITION", "EVENING": "EVENING_QUIZ"},
        3: {"LUNCH": "LUNCH_PHRASAL_VERB", "EVENING": "EVENING_SENTENCE_COMPLETION"},
        4: {"LUNCH": "LUNCH_BUSINESS_ENGLISH", "EVENING": "EVENING_SCENARIO"},
        5: {"LUNCH": "LUNCH_LEVEL_UP", "EVENING": "EVENING_LEVEL_UP_CARD"},
        6: {"LUNCH": "SUNDAY_WEEKLY_REVIEW", "EVENING": "SUNDAY_WEEKLY_REVIEW"},
    }

    def __init__(self, seeds_path: str = "data/seeds/curriculum.json"):
        self.seeds_path = seeds_path
        self._seeds: List[Dict[str, Any]] = []
        self._load_seeds()

    def _load_seeds(self):
        if os.path.exists(self.seeds_path):
            try:
                with open(self.seeds_path, "r", encoding="utf-8") as f:
                    self._seeds = json.load(f)
                logger.info(f"Loaded {len(self._seeds)} curriculum seeds from {self.seeds_path}")
            except Exception as e:
                logger.error(f"Failed to load curriculum seeds: {e}")
        else:
            logger.warning(f"Seeds file not found at {self.seeds_path}")

    def get_all_seeds(self) -> List[Dict[str, Any]]:
        if not self._seeds:
            self._load_seeds()
        return self._seeds

    def determine_slot_info(self, override_slot: Optional[str] = None) -> Tuple[str, str, str]:
        """
        Calculates (slot_key, time_of_day, slot_type) in Europe/Istanbul timezone.
        Returns e.g.: ('2026-09-24_EVENING', 'EVENING', 'EVENING_QUIZ')
        """
        tz = pytz.timezone(settings.TIMEZONE)
        now = datetime.now(tz)
        date_str = now.strftime("%Y-%m-%d")

        if override_slot and "_" in override_slot:
            slot_key = override_slot
            time_of_day = override_slot.split("_")[1].upper()
        else:
            time_of_day = "LUNCH" if now.hour < 16 else "EVENING"
            slot_key = f"{date_str}_{time_of_day}"

        weekday = now.weekday()
        slot_type = self.WEEKDAY_SLOT_MAP.get(weekday, {}).get(time_of_day, "LUNCH_COMMON_MISTAKE")

        return slot_key, time_of_day, slot_type

    def select_seed(self, slot_type: str, used_seed_ids: List[int]) -> Optional[Dict[str, Any]]:
        """
        Picks the next unused seed matching the target slot_type.
        Applies a 60-day recycling cooldown if all matching seeds have been used.
        """
        all_seeds = self.get_all_seeds()
        matching = [s for s in all_seeds if s.get("slot_type") == slot_type]

        if not matching:
            # Fallback to any seed if no exact category match exists
            matching = all_seeds

        if not matching:
            logger.error("No curriculum seeds available!")
            return None

        # Filter out already used seeds
        unused = [s for s in matching if s.get("seed_id") not in used_seed_ids]

        if unused:
            chosen = unused[0]
            logger.info(f"Selected seed #{chosen.get('seed_id')} ({slot_type})")
            return chosen

        # All matching seeds have been used: recycle oldest matching
        logger.info(f"All seeds for {slot_type} have been used. Recycling cooldown...")
        chosen = matching[0]
        return chosen

    def resolve_yesterday_quiz_answer(self, recent_posts: List[Any]) -> Optional[str]:
        """
        For Thursday Lunch posts:
        Checks recent_posts for Wednesday Evening QUIZ and extracts the correct option + explanation.
        """
        all_seeds_by_id = {s.get("seed_id"): s for s in self.get_all_seeds()}

        for post in recent_posts:
            # Post object or dict
            slot_key = getattr(post, "slot_key", None) or post.get("slot_key", "")
            if "EVENING" in slot_key:
                seed_id = getattr(post, "seed_id", None) or post.get("seed_id")
                if seed_id and seed_id in all_seeds_by_id:
                    seed = all_seeds_by_id[seed_id]
                    if seed.get("slot_type") == "EVENING_QUIZ":
                        facts = seed.get("facts", {})
                        correct = facts.get("correct_option", "")
                        explanation = facts.get("quiz_explanation", "")
                        return f"{correct} ({explanation})" if explanation else correct

        return None


curriculum_service = CurriculumService()
