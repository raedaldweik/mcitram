"""In-memory session & query store.

Keeps conversations (per selected agent) and completed query records so the
UI's "Recent conversations" panel survives page reloads for the lifetime of
the process. A single-process store is deliberate — this app is a demo/POC;
swap for Redis/Postgres when multi-replica persistence matters.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

MAX_HISTORY_TURNS = 16          # user+assistant messages kept per session
MAX_HISTORY_CHARS = 3000        # per stored message


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class QueryRun:
    id: str
    session_id: str
    agent_id: str
    content: str
    language: str = "en"                     # UI language ("en" | "ar")
    status: str = "running"                  # running | done | error
    result: Optional[dict] = None
    trace: dict = field(default_factory=lambda: {
        "toolCalls": [], "llmCalls": [], "retrievalCalls": []})
    created_at: float = field(default_factory=time.time)


@dataclass
class Session:
    id: str
    agent_id: str
    title: str = "Conversation"
    history: list = field(default_factory=list)   # [{role, content}]
    query_ids: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def add_turn(self, role: str, content: str):
        self.history.append({"role": role,
                             "content": (content or "")[:MAX_HISTORY_CHARS]})
        if len(self.history) > MAX_HISTORY_TURNS:
            self.history = self.history[-MAX_HISTORY_TURNS:]


_sessions: dict[str, Session] = {}
_queries: dict[str, QueryRun] = {}


def create_session(agent_id: str, first_content: str) -> Session:
    title = first_content.strip().replace("\n", " ")
    title = title[:40] + ("..." if len(title) > 40 else "") or "Conversation"
    s = Session(id=_id("qs"), agent_id=agent_id, title=title)
    _sessions[s.id] = s
    return s


def get_session(session_id: str) -> Optional[Session]:
    return _sessions.get(session_id)


def list_sessions() -> list[Session]:
    return sorted(_sessions.values(), key=lambda s: s.created_at, reverse=True)


def create_query(session: Session, agent_id: str, content: str,
                 language: str = "en") -> QueryRun:
    q = QueryRun(id=_id("q"), session_id=session.id, agent_id=agent_id,
                 content=content, language=language)
    _queries[q.id] = q
    session.query_ids.append(q.id)
    return q


def get_query(query_id: str) -> Optional[QueryRun]:
    return _queries.get(query_id)


def session_query_records(session: Session) -> list[dict]:
    """Completed query records shaped for the frontend's history rebuild."""
    records: list[dict] = []
    for qid in session.query_ids:
        q = _queries.get(qid)
        if not q or q.status == "running":
            continue
        rec: dict[str, Any] = {"queryId": q.id, "content": q.content}
        if q.result:
            rec.update(q.result)
        if q.status == "error" and not rec.get("errorCode"):
            rec["errorCode"] = 1
            rec.setdefault("errorText", "query failed")
        records.append(rec)
    return records
