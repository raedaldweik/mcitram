"""The agentic loop: Claude (Sonnet 5) + in-process toolsets.

Runs one query against one agent definition: system prompt + tools, iterating
model → tool calls → tool results until the model answers. Every tool call
and LLM call is recorded live into the query's trace, which the frontend
polls to show agent activity in real time (and renders afterwards in the
details view). The SAS Viya Copilot's `delegate_to_specialist` tool runs a
nested sub-agent loop with the same recording, so orchestration is fully
visible in the UI.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Optional

from anthropic import AsyncAnthropic

from agents.registry import AgentDef
from services.store import QueryRun, Session
from toolset import ToolError

logger = logging.getLogger("runner")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
MODEL = os.getenv("MODEL", "claude-sonnet-5")
# Sonnet 5 supports low|medium|high|xhigh|max. Medium keeps demo turns snappy;
# raise via env for the hardest workloads.
LLM_EFFORT = os.getenv("LLM_EFFORT", "medium")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "8192"))
QUERY_TIMEOUT = int(os.getenv("QUERY_TIMEOUT", "600"))

_TRACE_STR_CAP = 6000       # per string inside recorded tool outputs
_TOOL_RESULT_CAP = 30000    # chars of a tool result sent back to the model

_client: Optional[AsyncAnthropic] = None


def get_client() -> Optional[AsyncAnthropic]:
    global _client
    if _client is None and ANTHROPIC_API_KEY:
        _client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def llm_configured() -> bool:
    return bool(ANTHROPIC_API_KEY)


def _cap_strings(value: Any, limit: int = _TRACE_STR_CAP) -> Any:
    """Recursively cap long strings so one huge log can't bloat the trace."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"… [truncated {len(value) - limit} chars]"
    if isinstance(value, list):
        return [_cap_strings(v, limit) for v in value[:200]]
    if isinstance(value, dict):
        return {k: _cap_strings(v, limit) for k, v in value.items()}
    return value


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        try:
            return json.loads(json.dumps(value, default=str))
        except Exception:
            return str(value)


ARABIC_NOTE = (
    "The user interface is set to Arabic. Always respond in clear Modern "
    "Standard Arabic (اللغة العربية الفصحى). Keep code, SAS syntax, REST "
    "paths, table/column names, technical identifiers, and URLs in their "
    "original form. Chart titles may stay in English when the data keys are "
    "English. Markdown structure (headings, bold, tables) still applies.")

_DELEGATE_TOOL = "delegate_to_specialist"


def _delegate_spec(agent: AgentDef) -> dict:
    roster = "; ".join(
        f"{sid} — {sdef.description}" for sid, sdef in agent.specialists.items())
    return {
        "name": _DELEGATE_TOOL,
        "description": (
            "Delegate a well-defined stage of work to one of your specialist "
            "sub-agents. Each runs its own tool loop and reports back. "
            f"Specialists: {roster}. Give the specialist a precise, "
            "self-contained task including every identifier it needs "
            "(server/caslib/table names, target variable, project IDs, prior "
            "results) — it cannot see this conversation."),
        "input_schema": {
            "type": "object",
            "properties": {
                "specialist": {"type": "string",
                               "enum": list(agent.specialists.keys())},
                "task": {"type": "string",
                         "description": "Precise instructions for the specialist."},
                "context": {"type": "string",
                            "description": "Optional extra context (data locations, prior findings)."},
            },
            "required": ["specialist", "task"],
        },
    }


class AgentRunner:
    def __init__(self, run: QueryRun, agent: AgentDef, session: Session):
        self.run = run
        self.agent = agent
        self.session = session
        self.usage = {"prompt": 0, "completion": 0}

    # ── trace recording ─────────────────────────────────────────────
    def _record_tool(self, tool_name: str, args: Any, output: Any, agent_label: str = ""):
        entry = {
            "id": f"tc_{uuid.uuid4().hex[:10]}",
            "toolName": f"{agent_label} › {tool_name}" if agent_label else tool_name,
            "input": _cap_strings(_jsonable(args)),
            "output": _cap_strings(_jsonable(output)),
        }
        self.run.trace["toolCalls"].append(entry)

    def _record_llm(self, usage):
        p = getattr(usage, "input_tokens", 0) or 0
        c = getattr(usage, "output_tokens", 0) or 0
        cache_r = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_w = getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.usage["prompt"] += p + cache_r + cache_w
        self.usage["completion"] += c
        self.run.trace["llmCalls"].append({
            "id": f"llm_{uuid.uuid4().hex[:10]}",
            "input": {"modelName": MODEL, "modelProvider": "anthropic"},
            "promptTokens": p + cache_r + cache_w,
            "completionTokens": c,
        })

    # ── LLM call ────────────────────────────────────────────────────
    async def _call_llm(self, system: str, tools: list[dict], messages: list) -> Any:
        client = get_client()
        system_blocks = [{"type": "text", "text": system,
                          "cache_control": {"type": "ephemeral"}}]
        if getattr(self.run, "language", "en") == "ar":
            # appended AFTER the cached block so the agent-prompt cache still hits
            system_blocks.append({"type": "text", "text": ARABIC_NOTE})
        async with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_blocks,
            tools=tools,
            messages=messages,
            output_config={"effort": LLM_EFFORT},
        ) as stream:
            msg = await stream.get_final_message()
        self._record_llm(msg.usage)
        return msg

    # ── tool dispatch ───────────────────────────────────────────────
    async def _execute_tool(self, agent: AgentDef, name: str, args: dict,
                            agent_label: str = "") -> tuple[Any, bool]:
        """Returns (output, is_error)."""
        if name == _DELEGATE_TOOL and agent.specialists:
            return await self._delegate(args), False
        ts = agent.find_toolset(name)
        if ts is None:
            return {"error": f"unknown tool: {name}"}, True
        try:
            out = await ts.execute(name, args or {})
            return out, False
        except ToolError as e:
            return {"error": str(e)}, True
        except Exception as e:  # network, auth, API errors — let the agent react
            logger.exception("tool %s failed", name)
            return {"error": f"{type(e).__name__}: {str(e)[:600]}"}, True

    async def _delegate(self, args: dict) -> dict:
        sid = (args or {}).get("specialist", "")
        spec = self.agent.specialists.get(sid)
        if spec is None:
            return {"error": f"unknown specialist '{sid}'. Available: "
                             f"{', '.join(self.agent.specialists)}"}
        task = (args or {}).get("task", "")
        context = (args or {}).get("context", "")
        prompt = task if not context else f"{task}\n\nContext from the copilot:\n{context}"
        report = await self._loop(spec, [{"role": "user", "content": prompt}],
                                  agent_label=spec.id)
        return {"specialist": sid, "report": report}

    # ── the agentic loop ────────────────────────────────────────────
    async def _loop(self, agent: AgentDef, messages: list, agent_label: str = "") -> str:
        tools = agent.tool_specs()
        if agent.specialists:
            tools = tools + [_delegate_spec(agent)]
        final_text = ""
        for _ in range(agent.max_iters):
            msg = await self._call_llm(agent.system, tools, messages)

            text_parts = [b.text for b in msg.content if b.type == "text"]
            if text_parts:
                final_text = "\n".join(text_parts).strip()

            tool_uses = [b for b in msg.content if b.type == "tool_use"]
            if not tool_uses:
                break

            messages.append({"role": "assistant", "content": msg.content})
            results = []
            for tu in tool_uses:
                args = tu.input or {}
                output, is_error = await self._execute_tool(
                    agent, tu.name, args, agent_label)
                self._record_tool(tu.name, args, output, agent_label)
                content = json.dumps(output, default=str)
                if len(content) > _TOOL_RESULT_CAP:
                    content = content[:_TOOL_RESULT_CAP] + '… [truncated]"'
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": content, "is_error": is_error})
            messages.append({"role": "user", "content": results})
        else:
            final_text = final_text or (
                "I hit the step limit for one turn before finishing. The work "
                "so far is in the activity trace — ask me to continue.")
        return final_text or "I wasn't able to produce an answer for that query."

    # ── public entrypoint ───────────────────────────────────────────
    async def execute(self):
        run = self.run
        try:
            if not llm_configured():
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set — the agents need it to think. "
                    "Add it to the deployment environment variables.")
            messages = list(self.session.history) + [
                {"role": "user", "content": run.content}]
            answer = await asyncio.wait_for(
                self._loop(self.agent, messages), timeout=QUERY_TIMEOUT)

            run.result = {
                "queryId": run.id,
                "content": run.content,
                "answer": answer,
                "toolCalls": run.trace["toolCalls"],
                "usage": {
                    "llmPromptTokens": self.usage["prompt"],
                    "llmCompletionTokens": self.usage["completion"],
                    "llmTotalTokens": self.usage["prompt"] + self.usage["completion"],
                },
                "context": _extract_context(run.trace["toolCalls"]),
                "target": self.agent.name,
                "errorCode": 0,
            }
            run.status = "done"
            self.session.add_turn("user", run.content)
            self.session.add_turn("assistant", answer)
        except asyncio.TimeoutError:
            run.result = {"queryId": run.id, "errorCode": 1,
                          "errorText": f"The agent did not finish within "
                                       f"{QUERY_TIMEOUT}s. Try a narrower request."}
            run.status = "error"
        except Exception as e:
            logger.exception("query %s failed", run.id)
            run.result = {"queryId": run.id, "errorCode": 1,
                          "errorText": f"{type(e).__name__}: {str(e)[:500]}"}
            run.status = "error"


def _extract_context(tool_calls: list[dict]) -> list[dict]:
    """Surface web sources the agent read as clickable context passages."""
    docs, seen = [], set()
    for call in tool_calls:
        out = call.get("output")
        if not isinstance(out, dict):
            continue
        for key in ("articles", "sources"):
            for item in out.get(key) or []:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                docs.append({
                    "metadata": {"title": item.get("title") or url,
                                 "source": item.get("source") or url,
                                 "url": url,
                                 "filename": item.get("title") or item.get("source") or url},
                    "pageContent": (item.get("snippet") or "")
                                   + f"\n\n{url}",
                })
    return docs[:8]


def start(run: QueryRun, agent: AgentDef, session: Session) -> None:
    """Fire-and-forget execution; the frontend polls for completion."""
    asyncio.create_task(AgentRunner(run, agent, session).execute())
