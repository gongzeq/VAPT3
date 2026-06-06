"""``kind=llm_chunked`` executor — split large content, analyse per chunk,
then merge the structured judgements into one aggregate result.

Why this exists
---------------
The plain :class:`~secbot.workflow.executors.llm.LlmExecutor` issues a
single chat completion. When the log-analysis workflow feeds a very large
log body into one call, a reasoning model can spend the entire
``maxTokens`` budget on hidden chain-of-thought and return *empty* content
at ``finishReason=length`` (surfaced as
``workflow.executor.llm_truncated``). Splitting the body into bounded
chunks keeps every call well inside the budget.

Args contract (camelCase; already interpolated by the runner)::

    {
        "systemPrompt":  "…",          # optional
        "userPrompt":    "… <<CHUNK>> …",  # required; must contain the
                                       # literal marker <<CHUNK>> where the
                                       # per-chunk content is injected
        "chunkContent":  "<raw text>", # required; the text to be chunked
        "chunkMaxChars": 10000,        # optional, ≥ 1 (default 10000)
        "maxChunks":     30,           # optional safety cap (default 30)
        "temperature":   0.1,          # optional
        "maxTokens":     16000,        # optional, applied *per chunk*
        "responseFormat": "json"|"text"  # optional, defaults to "json"
    }

Output payload (shape mirrors the merged log-analysis schema so the
downstream step3 script can read ``${steps.<id>.result.parsed}`` exactly
as it did with the single-call ``llm`` executor)::

    {
        "content":      <str>,        # JSON dump of the merged result
        "parsed":       <dict>,       # merged structured judgement
        "finishReason": "stop",
        "chunkCount":   <int>,
        "usage":        {"promptTokens": n, "completionTokens": n}
    }
"""

from __future__ import annotations

import json
import logging
from typing import Any

from secbot.workflow.executors.base import ExecutorError, StepContext
from secbot.workflow.executors.llm import (
    _DEFAULT_MAX_TOKENS,
    _DEFAULT_TEMPERATURE,
    LlmExecutor,
)
from secbot.workflow.types import WorkflowStep

logger = logging.getLogger(__name__)

_CHUNK_MARKER = "<<CHUNK>>"
_DEFAULT_CHUNK_MAX_CHARS = 10000
_DEFAULT_MAX_CHUNKS = 30

# suggested_action severity ordering (low → high). The merged result
# reports the most severe action any chunk proposed.
_ACTION_RANK = {
    "忽略": 0,
    "标记关注": 1,
    "告警": 2,
    "紧急处理": 3,
}


class ChunkedLlmExecutor(LlmExecutor):
    """Chunked one-shot LLM analysis with structured-result aggregation.

    Reuses :class:`LlmExecutor` for provider resolution / hot-reload; only
    the per-chunk loop and result merge are new.
    """

    kind = "llm_chunked"

    async def _run(
        self,
        step: WorkflowStep,
        args: dict[str, Any],
        ctx: StepContext,
    ) -> Any:
        provider = self._resolve_provider()
        if provider is None:
            raise ExecutorError(
                "workflow.validation.llm_config: no LLM provider is configured"
            )

        system_prompt = args.get("systemPrompt") or args.get("system_prompt")
        user_prompt = args.get("userPrompt") or args.get("user_prompt")
        if not isinstance(user_prompt, str) or not user_prompt.strip():
            raise ExecutorError(
                "workflow.validation.llm_prompt: args.userPrompt is required"
            )
        if _CHUNK_MARKER not in user_prompt:
            raise ExecutorError(
                "workflow.validation.llm_prompt: args.userPrompt must contain "
                f"the {_CHUNK_MARKER} marker for chunk injection"
            )
        if system_prompt is not None and not isinstance(system_prompt, str):
            raise ExecutorError(
                "workflow.validation.llm_prompt: args.systemPrompt must be a string"
            )

        content = args.get("chunkContent", args.get("chunk_content", ""))
        if content is None:
            content = ""
        if not isinstance(content, str):
            content = str(content)

        temperature = args.get("temperature", _DEFAULT_TEMPERATURE)
        max_tokens = args.get("maxTokens", args.get("max_tokens", _DEFAULT_MAX_TOKENS))
        chunk_max = args.get("chunkMaxChars", args.get("chunk_max_chars", _DEFAULT_CHUNK_MAX_CHARS))
        max_chunks = args.get("maxChunks", args.get("max_chunks", _DEFAULT_MAX_CHUNKS))

        if not isinstance(temperature, (int, float)) or not (0.0 <= float(temperature) <= 2.0):
            raise ExecutorError(
                "workflow.validation.llm_temperature: temperature must be a number in [0, 2]"
            )
        if not isinstance(max_tokens, int) or max_tokens < 1:
            raise ExecutorError(
                "workflow.validation.llm_max_tokens: maxTokens must be a positive int"
            )
        if not isinstance(chunk_max, int) or chunk_max < 1:
            raise ExecutorError(
                "workflow.validation.llm_chunk_max: chunkMaxChars must be a positive int"
            )
        if not isinstance(max_chunks, int) or max_chunks < 1:
            raise ExecutorError(
                "workflow.validation.llm_max_chunks: maxChunks must be a positive int"
            )

        chunks = _split_into_chunks(content, int(chunk_max))
        truncated_chunks = False
        if len(chunks) > max_chunks:
            chunks = chunks[:max_chunks]
            truncated_chunks = True
        if not chunks:
            # Empty content — still emit a single empty chunk so the model
            # returns a well-formed (benign) judgement instead of crashing.
            chunks = [""]

        merged = _new_merged()
        notes: list[str] = []
        prompt_tokens = 0
        completion_tokens = 0

        for idx, chunk in enumerate(chunks, 1):
            chunk_prompt = user_prompt.replace(_CHUNK_MARKER, chunk)
            messages: list[dict[str, Any]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": chunk_prompt})

            try:
                resp = await provider.chat(
                    messages,
                    max_tokens=int(max_tokens),
                    temperature=float(temperature),
                )
            except Exception as exc:  # transient provider error — skip chunk
                logger.warning(
                    "workflow.llm_chunked: chunk %s/%s chat failed: %s",
                    idx, len(chunks), exc,
                )
                notes.append(f"分块{idx}分析失败（调用异常）")
                continue

            usage = getattr(resp, "usage", None)
            if usage:
                prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
                completion_tokens += int(usage.get("completion_tokens", 0) or 0)

            finish_reason = getattr(resp, "finish_reason", "stop")
            chunk_content = getattr(resp, "content", None)

            if finish_reason == "error":
                err = (
                    getattr(resp, "error_type", None)
                    or getattr(resp, "error_code", None)
                    or "unknown"
                )
                notes.append(f"分块{idx}分析失败（{err}）")
                continue
            if finish_reason == "length" and not (
                isinstance(chunk_content, str) and chunk_content.strip()
            ):
                notes.append(
                    f"分块{idx}分析被截断（maxTokens={int(max_tokens)}），已跳过"
                )
                continue
            if finish_reason == "content_filter":
                notes.append(f"分块{idx}被内容安全过滤拦截")
                continue

            parsed = _parse_json(chunk_content)
            if parsed is None:
                notes.append(f"分块{idx}返回非法 JSON，已跳过")
                continue

            _merge_into(merged, parsed)

        if truncated_chunks:
            notes.append(
                f"日志过大，仅分析前 {max_chunks} 个分块"
                f"（每块≤{int(chunk_max)}字符）"
            )

        _finalise_merged(merged, notes)

        return {
            "content": json.dumps(merged, ensure_ascii=False),
            "parsed": merged,
            "finishReason": "stop",
            "chunkCount": len(chunks),
            "usage": {
                "promptTokens": prompt_tokens,
                "completionTokens": completion_tokens,
            },
        }


# ---------------------------------------------------------------------------
# Chunking + merge helpers
# ---------------------------------------------------------------------------


def _split_into_chunks(content: str, chunk_max: int) -> list[str]:
    """Split *content* into chunks of ≤ ``chunk_max`` chars on line
    boundaries. A single over-long line is hard-split.
    """
    content = content or ""
    if not content.strip():
        return []
    if len(content) <= chunk_max:
        return [content]

    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for line in content.splitlines(keepends=True):
        # A single line longer than the budget — hard-split it.
        while len(line) > chunk_max:
            if buf:
                chunks.append("".join(buf))
                buf, buf_len = [], 0
            chunks.append(line[:chunk_max])
            line = line[chunk_max:]
        if buf_len + len(line) > chunk_max and buf:
            chunks.append("".join(buf))
            buf, buf_len = [], 0
        buf.append(line)
        buf_len += len(line)
    if buf:
        chunks.append("".join(buf))
    return chunks


def _parse_json(content: Any) -> dict[str, Any] | None:
    """Parse a model reply into a dict, tolerating ```json fences."""
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not text:
        return None
    if text.startswith("```"):
        # Strip an optional ```json … ``` fence.
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
        text = text.strip()
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _new_merged() -> dict[str, Any]:
    return {
        "confidence": 0.0,
        "reason": "",
        "risk_factors": [],
        "suggested_action": "忽略",
        "anomaly_count": 0,
        "anomaly_entries": [],
        "severity_distribution": {"critical": 0, "high": 0, "medium": 0, "low": 0},
        "_reasons": [],  # scratch — removed in _finalise_merged
    }


def _merge_into(merged: dict[str, Any], parsed: dict[str, Any]) -> None:
    """Fold one chunk's structured judgement into the running aggregate."""
    # confidence — keep the highest across chunks
    try:
        c = float(parsed.get("confidence") or 0.0)
        merged["confidence"] = max(float(merged["confidence"]), c)
    except (TypeError, ValueError):
        pass

    # reason — accumulate non-empty chunk reasons
    reason = parsed.get("reason")
    if isinstance(reason, str) and reason.strip():
        merged["_reasons"].append(reason.strip())

    # risk_factors — dedup union, preserve order
    for rf in parsed.get("risk_factors") or []:
        if rf not in merged["risk_factors"]:
            merged["risk_factors"].append(rf)

    # suggested_action — most severe wins
    action = str(parsed.get("suggested_action") or "").strip()
    if action in _ACTION_RANK:
        cur = merged["suggested_action"]
        if _ACTION_RANK[action] > _ACTION_RANK.get(cur, 0):
            merged["suggested_action"] = action

    # anomaly_entries — concat
    entries = parsed.get("anomaly_entries") or []
    if isinstance(entries, list):
        merged["anomaly_entries"].extend(entries)

    # anomaly_count — sum (fall back to entry count when absent)
    try:
        ac = int(parsed.get("anomaly_count"))
    except (TypeError, ValueError):
        ac = len(entries) if isinstance(entries, list) else 0
    merged["anomaly_count"] += ac

    # severity_distribution — sum each bucket
    sev = parsed.get("severity_distribution") or {}
    if isinstance(sev, dict):
        for key in ("critical", "high", "medium", "low"):
            try:
                merged["severity_distribution"][key] += int(sev.get(key, 0) or 0)
            except (TypeError, ValueError):
                pass


def _finalise_merged(merged: dict[str, Any], notes: list[str]) -> None:
    """Collapse scratch fields and clamp sizes for downstream storage."""
    reasons = merged.pop("_reasons", [])
    parts: list[str] = []
    if reasons:
        parts.append("；".join(reasons))
    if notes:
        parts.append("（" + "；".join(notes) + "）")
    reason_text = " ".join(p for p in parts if p).strip()
    if len(reason_text) > 1000:
        reason_text = reason_text[:1000] + "…"
    merged["reason"] = reason_text

    if len(merged["risk_factors"]) > 30:
        merged["risk_factors"] = merged["risk_factors"][:30]
    # step3 re-clamps to 50; keep a generous cap here.
    if len(merged["anomaly_entries"]) > 200:
        merged["anomaly_entries"] = merged["anomaly_entries"][:200]


__all__ = ["ChunkedLlmExecutor"]
