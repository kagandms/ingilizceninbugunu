import os
import random
import hashlib
from datetime import datetime, timezone, timedelta
import pytz

from config.settings import settings
from config.logger import logger
from data.state_store import StateStore, TursoStateStore, InMemoryStateStore, RecentPost
from services.threads_service import threads_service
from services.ai_service import ai_service
from services.curriculum_service import curriculum_service
from services.card_generator import card_generator
from services.image_host_service import image_host_service
from services.alert_service import alert_service


def sync_insights_best_effort(store: StateStore):
    """
    Checks recent posts in state older than 24 hours that haven't been checked yet.
    Queries Threads Insights API and saves metrics back to state.
    """
    if settings.DRY_RUN:
        return

    try:
        state = store.get_state()
        now = datetime.now(timezone.utc)
        updated = False

        for post in state.recent_posts:
            if not getattr(post, "insights_checked", False) and getattr(post, "published_at", None):
                try:
                    pub_dt = datetime.fromisoformat(post.published_at.replace("Z", "+00:00"))
                    age_hours = (now - pub_dt).total_seconds() / 3600.0
                    if age_hours >= 24.0:
                        metrics = threads_service.get_post_insights(post.id)
                        if metrics:
                            post.insights = metrics
                            post.insights_checked = True
                            updated = True
                except Exception as e:
                    logger.debug(f"Could not parse pub_dt for post {post.id}: {e}")

        if updated:
            store.save_state(state)
            logger.info("Saved 24h post insights to state.")
    except Exception as e:
        logger.warning(f"Best-effort insights sync skipped: {e}")


def execute_pipeline(store: StateStore, override_slot: str = None) -> bool:
    """
    Orchestrates the complete English in Threads publishing pipeline:
    1. Slot determination (Europe/Istanbul)
    2. Read state & Token refresh check (>= 7 days)
    3. Best-effort Insights sync (> 24 hours old)
    4. Threads API Lookback Idempotency check (/me/threads)
    5. Seed selection & AI Generation (Facts vs Voice)
    6. A/B Format assignment (Card Image vs Text)
    7. Atomic pending lock
    8. Post publication to Threads
    9. Media cleanup (Cloudinary & local temp)
    10. State persistence & Healthchecks ping
    """
    slot_key, time_of_day, slot_type = curriculum_service.determine_slot_info(override_slot)
    logger.info(f"🚀 Starting publishing run for: {slot_key} | Slot Type: {slot_type} | DRY_RUN: {settings.DRY_RUN}")

    try:
        # Step 1: Load State
        state = store.get_state()
        logger.info(f"State loaded. Used seeds: {len(state.used_seed_ids)}, Recent posts: {len(state.recent_posts)}")

        # Step 2: Token Refresh check
        new_token = threads_service.refresh_access_token_if_needed(state.last_token_refresh)
        if new_token and new_token != "DRY_RUN_NEW_TOKEN":
            state.last_token_refresh = datetime.now(timezone.utc).isoformat()
            store.save_state(state)

        # Step 3: Best-effort Insights sync
        sync_insights_best_effort(store)

        # Step 4: Lookback Idempotency check (/me/threads)
        recent_threads = threads_service.get_recent_posts(hours=6)
        for thread in recent_threads:
            thread_text = thread.get("text", "")
            # If a post already exists from this slot in the last 6 hours
            if slot_key in thread_text:
                logger.warning(f"⚠️ Idempotency hit: Slot {slot_key} already live on Threads (ID: {thread.get('id')}). Aborting.")
                return True

        # Step 5: Curriculum Seed Selection
        seed = curriculum_service.select_seed(slot_type, state.used_seed_ids)
        if not seed:
            logger.error("No valid seed found for this slot!")
            return False

        # If Thursday Lunch: resolve yesterday's quiz answer
        yesterday_answer = None
        if time_of_day == "LUNCH" and datetime.now(pytz.timezone(settings.TIMEZONE)).weekday() == 3:
            yesterday_answer = curriculum_service.resolve_yesterday_quiz_answer(state.recent_posts)

        # Step 6: AI Content Generation (Facts enforced, max 470 chars)
        generated = ai_service.generate_post_for_seed(seed, yesterday_quiz_answer=yesterday_answer)
        final_text = generated.raw_full_text
        payload_hash = hashlib.sha256(final_text.encode("utf-8")).hexdigest()[:16]

        logger.info(f"Post text ready ({len(final_text)} chars, Model: {generated.source_model})")

        # Step 7: A/B Format Assignment (50% random: CARD_IMAGE vs TEXT_ONLY)
        format_assignment = random.choice(["CARD_IMAGE", "TEXT_ONLY"])
        image_url = None
        cloudinary_public_id = None
        local_card_path = None

        if format_assignment == "CARD_IMAGE":
            logger.info("A/B Assignment: CARD_IMAGE. Generating visual card...")
            local_card_path = card_generator.generate_card(seed)
            if local_card_path:
                upload_res = image_host_service.upload_image(local_card_path)
                if upload_res:
                    image_url, cloudinary_public_id = upload_res
                else:
                    logger.warning("Cloudinary upload unavailable. Falling back to TEXT_ONLY.")
                    format_assignment = "TEXT_ONLY"
            else:
                logger.warning("Card rendering unavailable. Falling back to TEXT_ONLY.")
                format_assignment = "TEXT_ONLY"
        else:
            logger.info("A/B Assignment: TEXT_ONLY.")

        # Step 8: Acquire Atomic Pending Lock
        lock_acquired = store.acquire_pending_lock(slot_key=slot_key, payload_hash=payload_hash)
        if not lock_acquired:
            logger.warning(f"🔒 Could not acquire lock for {slot_key}. Run aborted.")
            if cloudinary_public_id:
                image_host_service.delete_image(cloudinary_public_id)
            return False

        # Step 9: Publish Post to Threads
        alt_text = f"İngilizce kalıp kartı: {seed.get('key_term', '')}" if image_url else None
        success, post_id = threads_service.publish_post(
            text=final_text,
            image_url=image_url,
            alt_text=alt_text
        )

        # Step 10: Cleanup Media
        if cloudinary_public_id:
            image_host_service.delete_image(cloudinary_public_id)
        if local_card_path and os.path.exists(local_card_path):
            try:
                os.remove(local_card_path)
            except Exception:
                pass

        if not success:
            logger.error(f"❌ Failed to publish post for {slot_key}")
            store.release_pending_lock(success=False)
            alert_service.send_telegram_alert(f"Failed to publish {slot_key}")
            return False

        # Step 11: Update State & Record Recent Post
        post_meta = RecentPost(
            id=post_id or "dry_run_id",
            slot_key=slot_key,
            seed_id=seed.get("seed_id"),
            text_preview=final_text[:70].replace("\n", " "),
            format_assignment=format_assignment,
            published_at=datetime.now(timezone.utc).isoformat()
        )

        # Track used seed
        seed_id = seed.get("seed_id")
        if seed_id and seed_id not in state.used_seed_ids:
            state.used_seed_ids.append(seed_id)

        # Track weekly key term
        key_term = seed.get("key_term")
        if key_term and key_term not in state.weekly_key_terms:
            state.weekly_key_terms.append(key_term)

        store.save_state(state)
        store.release_pending_lock(success=True, post=post_meta)

        logger.info(f"🎉 Run completed successfully for {slot_key}! Post ID: {post_id}")

        # Step 12: Dead-man's switch Ping
        alert_service.ping_healthchecks(f"SUCCESS {slot_key} - Post {post_id}")
        return True

    except Exception as e:
        logger.critical(f"💥 Unhandled exception during execution: {e}", exc_info=True)
        alert_service.send_telegram_alert(f"Unhandled pipeline crash in {slot_key}: {e}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="English in Threads Runner")
    parser.add_argument("--slot", type=str, help="Override slot key (e.g. 2026-09-24_LUNCH)")
    parser.add_argument("--use-in-memory", action="store_true", help="Force InMemoryStateStore")
    args = parser.parse_args()

    if args.use_in_memory or not settings.TURSO_DATABASE_URL:
        logger.info("Using InMemoryStateStore (local / test mode).")
        store = InMemoryStateStore()
    else:
        logger.info("Using TursoStateStore (production mode).")
        store = TursoStateStore()

    success = execute_pipeline(store=store, override_slot=args.slot)
    if not success:
        exit(1)


if __name__ == "__main__":
    main()
