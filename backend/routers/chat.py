"""API routes the frontend calls.

Same surface as the RAM chat UI (submit-then-poll queries, live trace,
sessions, attachment extraction) — served by the in-process agents instead of
SAS Retrieval Agent Manager.
"""
from __future__ import annotations

import io

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

import sasviya.config as viya_config
import sasvi.config as vi_config
import websearch.config as web_config
from agents import registry
from services import images, runner, store

router = APIRouter(prefix="/api", tags=["agents"])

# Attached documents are inlined into the query text — keep them inside a
# sane prompt budget for the agent's LLM.
MAX_ATTACH_CHARS = 20_000


class Attachment(BaseModel):
    name: str
    text: str


class QueryRequest(BaseModel):
    content: str
    agentId: str | None = None
    collectionIds: list[str] | None = None
    querySessionId: str | None = None
    attachments: list[Attachment] | None = None
    language: str | None = "en"              # UI language — agents answer in it


@router.get("/health")
async def health():
    ok = runner.llm_configured()
    return {
        "status": "ok" if ok else "unconfigured",
        "model": runner.MODEL,
        "connections": {
            "anthropic": ok,
            "sas_viya": "configured" if viya_config.configured() else "not configured",
            "visual_investigator": "configured" if vi_config.configured() else "not configured",
            "tavily": "configured" if web_config.configured() else "not configured",
        },
    }


@router.get("/agents")
async def agents():
    return registry.list_agents()


@router.get("/collections")
async def collections():
    # Kept for UI compatibility — this deployment has no direct-retrieval
    # collections; everything goes through the agents.
    return []


@router.get("/sessions")
async def sessions():
    return [{"id": s.id, "title": s.title, "agentId": s.agent_id,
             "collectionIds": []} for s in store.list_sessions()]


@router.get("/sessions/{session_id}/queries")
async def session_queries(session_id: str):
    s = store.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Unknown session.")
    return store.session_query_records(s)


# ─── Attachments (ad-hoc documents, inlined into the query) ─────────
@router.post("/extract")
async def extract(file: UploadFile = File(...)):
    """Extract plain text from an uploaded document so it can be sent inline
    with a question."""
    data = await file.read()
    name = file.filename or "attachment"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    if ext == "pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not read PDF: {e}")
        if not text.strip():
            raise HTTPException(status_code=422, detail=(
                "This PDF contains no extractable text (it looks scanned). "
                "OCR isn't available, so the assistant can't read it."))
    elif ext == "docx":
        try:
            from docx import Document
        except ImportError:
            raise HTTPException(status_code=415,
                                detail="DOCX support requires python-docx.")
        try:
            doc = Document(io.BytesIO(data))
            text = "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not read DOCX: {e}")
    elif ext in ("txt", "md", "csv", "json", "log", "xml", "html", "yaml", "yml",
                 "sas", "sql", "py"):
        text = data.decode("utf-8", errors="replace")
    elif ext in ("png", "jpg", "jpeg", "gif", "bmp", "webp", "tif", "tiff"):
        raise HTTPException(status_code=415, detail=(
            "Images can't be read — attachments are text-only. Export the "
            "content as a PDF or text file instead."))
    else:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: .{ext or '?'}")

    truncated = len(text) > MAX_ATTACH_CHARS
    return {"name": name, "text": text[:MAX_ATTACH_CHARS], "chars": len(text),
            "truncated": truncated}


# ─── Queries ─────────────────────────────────────────────────────────
@router.post("/query")
async def query(body: QueryRequest):
    """Submit a query asynchronously. Returns {queryId, querySessionId,
    pollInterval, timeout} — poll GET /api/query/{queryId} for the result."""
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Empty query.")
    agent = registry.get_agent(body.agentId or "")
    if agent is None:
        raise HTTPException(status_code=400,
                            detail="Select an agent from the dropdown first.")

    content = body.content
    if body.attachments:
        for a in body.attachments:
            content += (f"\n\n--- Attached document: {a.name} ---\n"
                        f"{a.text[:MAX_ATTACH_CHARS]}\n--- End of attached document ---")
        content += ("\n\nUse the attached document content above to answer "
                    "the question where relevant.")

    session = store.get_session(body.querySessionId or "")
    if session is None:
        session = store.create_session(agent.id, body.content)
    lang = "ar" if (body.language or "").lower().startswith("ar") else "en"
    run = store.create_query(session, agent.id, content, language=lang)
    runner.start(run, agent, session)
    return {"queryId": run.id, "querySessionId": session.id,
            "pollInterval": 2, "timeout": runner.QUERY_TIMEOUT}


@router.get("/query/{query_id}")
async def query_status(query_id: str):
    q = store.get_query(query_id)
    if not q:
        raise HTTPException(status_code=404, detail="Unknown query.")
    if q.status == "running":
        return {"done": False, "status": q.status}
    return {"done": True, "result": q.result}


@router.get("/query/{query_id}/trace")
async def query_trace(query_id: str):
    q = store.get_query(query_id)
    if not q:
        raise HTTPException(status_code=404, detail="Unknown query.")
    return q.trace


# ─── Rendered Visual Analytics report snapshots ──────────────────────
@router.get("/va/image/{image_id}")
async def va_image(image_id: str):
    item = images.get(image_id)
    if not item:
        raise HTTPException(status_code=404, detail="Image expired or unknown.")
    data, content_type = item
    return Response(content=data, media_type=content_type,
                    headers={"Cache-Control": "private, max-age=21600"})
