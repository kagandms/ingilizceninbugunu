import pytest
from data.state_store import InMemoryStateStore, RecentPost

@pytest.mark.asyncio
async def test_in_memory_state_store_lock_flow():
    store = InMemoryStateStore()
    slot_key = "2026-09-24_LUNCH"
    payload_hash = "abc123hash"

    # Initial lock acquisition should succeed
    acquired = await store.acquire_pending_lock(slot_key=slot_key, payload_hash=payload_hash)
    assert acquired is True

    # Duplicate acquisition for the same slot while pending must fail
    acquired_dup = await store.acquire_pending_lock(slot_key=slot_key, payload_hash=payload_hash)
    assert acquired_dup is False

    # Release pending lock on success
    post = RecentPost(
        id="test_post_1",
        slot_key=slot_key,
        text_preview="Hello world preview",
        format_assignment="TEXT_ONLY",
        published_at="2026-09-24T12:00:00Z"
    )
    released = await store.release_pending_lock(success=True, post=post)
    assert released is True

    # State should now have the post in recent_posts
    state = await store.get_state()
    assert len(state.recent_posts) == 1
    assert state.recent_posts[0].slot_key == slot_key
    assert state.pending_execution is None

    # Subsequent acquisition for the already completed slot must be rejected
    acquired_after_complete = await store.acquire_pending_lock(slot_key=slot_key, payload_hash=payload_hash)
    assert acquired_after_complete is False
