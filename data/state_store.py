import json
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from config.settings import settings
from config.logger import logger

try:
    from pydantic import BaseModel, Field
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def model_dump(self):
            return self.__dict__
        def model_dump_json(self):
            return json.dumps(self.model_dump(), default=str)
        def model_copy(self, deep=True):
            return self.__class__(**json.loads(self.model_dump_json()))
    def Field(default_factory=None, default=None):
        if default_factory:
            return default_factory()
        return default


class PendingExecution(BaseModel):
    slot_key: str
    started_at: str
    payload_hash: str
    status: str = "PENDING"  # PENDING, COMPLETED, FAILED


class RecentPost(BaseModel):
    id: str
    slot_key: str
    seed_id: Optional[int] = None
    text_preview: str = ""
    format_assignment: str = "TEXT_ONLY"  # TEXT_ONLY, CARD_IMAGE
    published_at: str = ""
    insights: Dict[str, int] = Field(default_factory=dict)
    insights_checked: bool = False


class BotState(BaseModel):
    last_token_refresh: Optional[str] = None
    used_seed_ids: List[int] = Field(default_factory=list)
    pending_execution: Optional[PendingExecution] = None
    recent_posts: List[RecentPost] = Field(default_factory=list)
    weekly_key_terms: List[str] = Field(default_factory=list)


class StateStore(ABC):
    """Abstract Interface for Bot State Management."""

    @abstractmethod
    def get_state(self) -> BotState:
        """Retrieves the current state."""
        pass

    @abstractmethod
    def save_state(self, state: BotState) -> bool:
        """Persists the updated state."""
        pass

    @abstractmethod
    def acquire_pending_lock(self, slot_key: str, payload_hash: str) -> bool:
        """Atomically checks and acquires pending execution lock."""
        pass

    @abstractmethod
    def release_pending_lock(self, success: bool, post: Optional[RecentPost] = None) -> bool:
        """Releases pending lock and updates recent posts."""
        pass


class InMemoryStateStore(StateStore):
    """In-memory fake implementation for testing and local simulation."""

    def __init__(self, initial_state: Optional[BotState] = None):
        self._state = initial_state or BotState()

    def get_state(self) -> BotState:
        return self._state.model_copy(deep=True)

    def save_state(self, state: BotState) -> bool:
        self._state = state.model_copy(deep=True)
        return True

    def acquire_pending_lock(self, slot_key: str, payload_hash: str) -> bool:
        state = self.get_state()
        for p in state.recent_posts:
            p_slot = getattr(p, "slot_key", None) or (p.get("slot_key") if isinstance(p, dict) else "")
            if p_slot == slot_key:
                logger.warning(f"Lock rejected: Slot {slot_key} already completed in recent_posts.")
                return False

        if state.pending_execution:
            pend_status = getattr(state.pending_execution, "status", None) or state.pending_execution.get("status")
            pend_slot = getattr(state.pending_execution, "slot_key", None) or state.pending_execution.get("slot_key")
            if pend_status == "PENDING" and pend_slot == slot_key:
                logger.warning(f"Lock rejected: Slot {slot_key} currently pending.")
                return False

        state.pending_execution = PendingExecution(
            slot_key=slot_key,
            started_at=datetime.now(timezone.utc).isoformat(),
            payload_hash=payload_hash,
            status="PENDING"
        )
        return self.save_state(state)

    def release_pending_lock(self, success: bool, post: Optional[RecentPost] = None) -> bool:
        state = self.get_state()
        if not state.pending_execution:
            return True

        if success and post:
            state.pending_execution.status = "COMPLETED"
            state.recent_posts.insert(0, post)
            if len(state.recent_posts) > 120:
                state.recent_posts = state.recent_posts[:120]
        else:
            state.pending_execution.status = "FAILED"

        state.pending_execution = None
        return self.save_state(state)


class TursoStateStore(StateStore):
    """
    Production StateStore implementation backed by Turso libSQL over HTTPS.
    Uses Turso's /v2/pipeline HTTP endpoint with zero native C-dependencies.
    """

    def __init__(self):
        self.db_url = settings.TURSO_DATABASE_URL.rstrip("/")
        self.auth_token = settings.TURSO_AUTH_TOKEN.get_secret_value()
        self.pipeline_url = f"{self.db_url}/v2/pipeline"
        self._initialized = False

    def _execute_sql(self, sql: str, args: Optional[List[Any]] = None) -> Optional[Dict[str, Any]]:
        """Executes a single SQL statement against Turso pipeline API."""
        if not self.db_url or not self.auth_token:
            logger.debug("Turso database URL or Auth Token not set.")
            return None

        stmt: Dict[str, Any] = {"sql": sql}
        if args:
            stmt["args"] = [{"type": "text", "value": str(a)} if a is not None else {"type": "null"} for a in args]

        payload = json.dumps({
            "requests": [{"type": "execute", "stmt": stmt}]
        }).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json"
        }

        try:
            req = urllib.request.Request(self.pipeline_url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    results = data.get("results", [])
                    if results and results[0].get("type") == "ok":
                        return results[0].get("response", {}).get("result")
                    else:
                        logger.error(f"Turso pipeline response error: {data}")
        except Exception as e:
            logger.error(f"Turso connection error: {e}")
        return None

    def _ensure_table(self):
        if self._initialized:
            return
        sql = (
            "CREATE TABLE IF NOT EXISTS english_bot_state ("
            "  id TEXT PRIMARY KEY,"
            "  state_json TEXT NOT NULL,"
            "  updated_at TEXT NOT NULL"
            ");"
        )
        res = self._execute_sql(sql)
        if res is not None:
            self._initialized = True

    def get_state(self) -> BotState:
        self._ensure_table()
        sql = "SELECT state_json FROM english_bot_state WHERE id = 'primary_state';"
        res = self._execute_sql(sql)
        if res and res.get("rows"):
            row = res["rows"][0]
            val = row[0].get("value") if isinstance(row[0], dict) else row[0]
            if val:
                try:
                    data = json.loads(val)
                    posts = [RecentPost(**p) for p in data.get("recent_posts", [])]
                    pend = PendingExecution(**data["pending_execution"]) if data.get("pending_execution") else None
                    return BotState(
                        last_token_refresh=data.get("last_token_refresh"),
                        used_seed_ids=data.get("used_seed_ids", []),
                        pending_execution=pend,
                        recent_posts=posts,
                        weekly_key_terms=data.get("weekly_key_terms", [])
                    )
                except Exception as e:
                    logger.error(f"Failed to parse BotState from Turso: {e}")
        return BotState()

    def save_state(self, state: BotState) -> bool:
        self._ensure_table()
        state_json = state.model_dump_json()
        now_iso = datetime.now(timezone.utc).isoformat()
        sql = (
            "INSERT INTO english_bot_state (id, state_json, updated_at) "
            "VALUES ('primary_state', ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "  state_json = excluded.state_json, "
            "  updated_at = excluded.updated_at;"
        )
        res = self._execute_sql(sql, [state_json, now_iso])
        return res is not None

    def acquire_pending_lock(self, slot_key: str, payload_hash: str) -> bool:
        state = self.get_state()
        for p in state.recent_posts:
            if p.slot_key == slot_key:
                logger.warning(f"Lock rejected: Slot {slot_key} already published.")
                return False

        if state.pending_execution and state.pending_execution.status == "PENDING":
            if state.pending_execution.slot_key == slot_key:
                logger.warning(f"Lock rejected: Slot {slot_key} has an active PENDING lock.")
                return False

        state.pending_execution = PendingExecution(
            slot_key=slot_key,
            started_at=datetime.now(timezone.utc).isoformat(),
            payload_hash=payload_hash,
            status="PENDING"
        )
        return self.save_state(state)

    def release_pending_lock(self, success: bool, post: Optional[RecentPost] = None) -> bool:
        state = self.get_state()
        if not state.pending_execution:
            return True

        if success and post:
            state.pending_execution.status = "COMPLETED"
            state.recent_posts.insert(0, post)
            if len(state.recent_posts) > 120:
                state.recent_posts = state.recent_posts[:120]
        else:
            state.pending_execution.status = "FAILED"

        state.pending_execution = None
        return self.save_state(state)
