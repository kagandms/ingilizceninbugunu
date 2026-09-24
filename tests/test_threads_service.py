import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from config.settings import settings
from services.threads_service import ThreadsService

@pytest.mark.asyncio
async def test_publish_text_post_exceeding_limit():
    service = ThreadsService()
    oversized_text = "A" * (settings.MAX_POST_CHARS + 10)
    success, post_id = await service.publish_text_post(oversized_text)
    assert success is False
    assert post_id is None

@pytest.mark.asyncio
async def test_token_refresh_skips_when_young():
    service = ThreadsService()
    # Token refreshed 2 days ago (< 7 days)
    two_days_ago = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    result = await service.refresh_access_token_if_needed(two_days_ago)
    assert result is None  # Should skip refresh

@pytest.mark.asyncio
async def test_token_refresh_triggers_when_old():
    service = ThreadsService()
    # Token refreshed 10 days ago (>= 7 days)
    ten_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    # In DRY_RUN mode it returns DRY_RUN_NEW_TOKEN
    result = await service.refresh_access_token_if_needed(ten_days_ago)
    assert result == "DRY_RUN_NEW_TOKEN"
