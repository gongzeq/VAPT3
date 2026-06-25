"""Fast-path for security knowledge Q&A — bypasses the orchestrator.

When the user asks a pure knowledge question (e.g. "什么是SQL注入"), this
module:
  1. Pre-classifies the message with cheap regex rules (no LLM).
  2. Runs ``knowledge-search`` skill directly (~200 ms).
  3. Makes **one** LLM call with the sec_qa system prompt + search results
     pre-injected, returning the answer as an ``OutboundMessage``.

This eliminates 2-3 LLM calls (orchestrator routing + sec_qa tool-call
round-trip + orchestrator finalisation), cutting latency from ~15-40 s
down to ~5-10 s for knowledge questions.

If classification is uncertain or the fast path fails for any reason,
the caller falls back to the normal orchestrator flow.
"""

from __future__ import annotations

import importlib.util
import re
import time
from pathlib import Path
from typing import Any

from loguru import logger

from secbot.bus.events import OutboundMessage
from secbot.skills.types import SkillContext

# ---------------------------------------------------------------------------
# Lazy-loaded singletons
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_SEC_QA_PROMPT_PATH = _PROJECT_ROOT / "secbot" / "agents" / "prompts" / "sec_qa.md"
_KB_HANDLER_PATH = _PROJECT_ROOT / "secbot" / "skills" / "knowledge-search" / "handler.py"

_sec_qa_prompt: str | None = None
_kb_run: Any = None


def _get_sec_qa_prompt() -> str:
    """Load and cache the sec_qa system prompt."""
    global _sec_qa_prompt
    if _sec_qa_prompt is None:
        _sec_qa_prompt = _SEC_QA_PROMPT_PATH.read_text(encoding="utf-8")
    return _sec_qa_prompt


def _get_kb_run():
    """Load and cache the knowledge-search handler's ``run`` coroutine."""
    global _kb_run
    if _kb_run is None:
        spec = importlib.util.spec_from_file_location("kb_handler", _KB_HANDLER_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        _kb_run = module.run
    return _kb_run


# ---------------------------------------------------------------------------
# Pre-classification: is this a pure knowledge question?
# ---------------------------------------------------------------------------

# Patterns that indicate an *operational* request (scanning, exploitation,
# report generation) — these are **soft** vetoes: overridden by knowledge
# intent.  Tool names and targets are **hard** vetoes (see below).
_ACTION_PATTERNS = re.compile(
    r"(?i)"
    r"(?:扫描|检测|漏洞利用|攻击\s*(?:目标|服务器|主机|网站))"  # CN action verbs
    r"|(?:scan|exploit|brute.?force|pentest)"  # EN action verbs
    r"|(?:attack\s+(?:target|server|host|website|machine|system|this|the))"  # EN attack + target
    r"|(?:生成\s*(?:报告|报表)|generate\s+report)"  # report generation
)

# Tool names are a **hard** veto: even "如何用nmap扫描" is operational.
_TOOL_PATTERNS = re.compile(
    r"(?i)"
    r"(?:nmap|sqlmap|hydra|nuclei|ffuf|fscan|masscan|nikto)"
)

# Targets (IP, domain, URL, CIDR) are a **hard** veto — always operational.
_TARGET_PATTERNS = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b"  # IP address
    r"|https?://[^\s]+"  # URL
    r"|\b(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}\b"  # CIDR
)

# Patterns that indicate a knowledge question.
_KNOWLEDGE_PATTERNS = re.compile(
    r"(?i)"
    # CN question forms — cover all common interrogative patterns
    r"(?:什么是|是什么|什么叫|啥叫|啥是|啥意思|什么意思|指的是什么|指什么)"
    r"|(?:如何|怎么|怎样|为什么|哪些|有什么|包含哪些|分几类|有哪些)"
    # CN knowledge starters
    r"|(?:解释|介绍一下|讲解|了解|学习|概念|定义|含义|原理|区别|对比)"
    r"|(?:分类|类型|特点|特征|作用|目的|关系|联系|流程|步骤|方法)"
    # EN knowledge starters
    r"|(?:how\s+(?:does|do|to)|what\s+(?:is|are)|why|explain|describe|difference)"
    # CN defensive terms
    r"|(?:防御|防护|加固|缓解|预防|修复|修补|对策|措施)"
    # EN defensive terms
    r"|(?:defen[cs]e|mitigat|prevent|hardening|remediat|fix|patch)"
    # CN vulnerability & attack names
    # \b at start, (?![a-zA-Z]) at end — prevents "rce" in "force" but
    # allows "RCE漏洞" (Chinese char after abbreviation is OK).
    r"|(?:SQL\s*注入|\bXSS(?![a-zA-Z])|\bCSRF(?![a-zA-Z])|\bSSRF(?![a-zA-Z])|\bRCE(?![a-zA-Z])|\bLFI(?![a-zA-Z])|\bRFI(?![a-zA-Z])|\bXXE(?![a-zA-Z])|越权|注入|跨站)"
    r"|(?:命令执行|代码执行|命令注入|文件上传|文件包含|文件读取|目录遍历)"
    r"|(?:反序列化|逻辑漏洞|业务漏洞|权限绕过|缓冲区溢出|中间人攻击)"
    r"|(?:社会工程学|钓鱼攻击|勒索软件|木马|蠕虫|后门|\brootkit(?![a-zA-Z])|内存马|\bwebshell(?![a-zA-Z]))"
    # EN vulnerability names
    r"|(?:injection|cross.?site|request.?forgery|traversal|deserialization)"
    r"|(?:command.?exec|code.?exec|file.?upload|file.?inclusion|privilege.?esc)"
    # CN regulatory terms
    r"|(?:网络安全法|数据安全法|个人信息保护|密码法|等保|合规)"
    # Standards/frameworks
    r"|(?:\bCVE(?![a-zA-Z])|\bCWE(?![a-zA-Z])|\bOWASP(?![a-zA-Z])|\bCIS(?![a-zA-Z])|ISO\s*2700|\bNIST(?![a-zA-Z]))"
    # CN security concepts & methodology
    r"|(?:\bWAF(?![a-zA-Z])|\bIDS(?![a-zA-Z])|\bIPS(?![a-zA-Z])|防火墙|加密|认证|授权|鉴权|token|session)"
    r"|(?:信息收集|资产发现|后渗透|横向移动|权限提升|提权|渗透测试|红蓝对抗)"
    r"|(?:访问控制|安全审计|应急响应|安全基线|风险评估|安全策略|安全架构)"
    r"|(?:零信任|态势感知|蜜罐|沙箱|取证|恶意代码|流量分析|密码学|数字证书|数字签名)"
)


def is_knowledge_question(content: str) -> bool:
    """Rule-based classifier: should this message take the sec_qa fast path?

    Decision order:
      1. **Hard veto** — targets (IP/URL) or tool names (nmap etc.) always
         go to the orchestrator, regardless of phrasing.
      2. **Knowledge intent** — if the message matches knowledge patterns,
         it takes the fast path even when it contains soft action words
         like "扫描" or "检测".  e.g. "如何进行漏洞扫描" → knowledge.
      3. **Soft veto** — action words without knowledge intent go to the
         orchestrator.  e.g. "扫描" alone → operational.

    Conservative by design: false negatives (falling through to the
    orchestrator) are harmless; false positives (sending a scan request
    through the knowledge path) would be bad.
    """
    if not content or not content.strip():
        return False

    text = content.strip()

    # 1. Hard veto: targets and tool names are always operational.
    if _TARGET_PATTERNS.search(text):
        return False
    if _TOOL_PATTERNS.search(text):
        return False

    # 2. Knowledge intent overrides soft action words.
    if _KNOWLEDGE_PATTERNS.search(text):
        return True

    # 3. Soft veto: action words without knowledge intent.
    if _ACTION_PATTERNS.search(text):
        return False

    return False


# ---------------------------------------------------------------------------
# Fast-path execution
# ---------------------------------------------------------------------------


async def fast_sec_qa(
    content: str,
    provider: Any,
    model: str,
    *,
    channel: str = "",
    chat_id: str = "",
    metadata: dict[str, Any] | None = None,
    on_stream: Any = None,
) -> OutboundMessage | None:
    """Execute the sec_qa fast path.

    1. Run ``knowledge-search`` with the user's question.
    2. Build a single LLM call: sec_qa system prompt + user question +
       pre-injected search results.
    3. Return the answer as an ``OutboundMessage``. When *on_stream* is
       provided, the LLM response is streamed token-by-token via the
       callback before the final ``OutboundMessage`` is returned.

    Returns an ``OutboundMessage`` on success, or ``None`` on failure
    (caller should fall back to the orchestrator).
    """
    t0 = time.monotonic()
    meta = dict(metadata or {})

    try:
        # ── Phase 1: knowledge-search ──
        kb_run = _get_kb_run()
        ctx = SkillContext(
            scan_id=f"fast-qa-{int(time.time())}",
            scan_dir=Path("/tmp/secbot-fast-qa"),
        )
        skill_result = await kb_run(
            {"query": content, "top_k": 5},
            ctx,
        )

        search_data = skill_result.summary.get("data", {})
        results = search_data.get("results", [])
        search_mode = search_data.get("search_mode", "unknown")
        elapsed_ms = skill_result.summary.get("elapsed_ms", 0)

        logger.info(
            "[fast-sec-qa] knowledge-search: {} hits, mode={}, {}ms",
            len(results), search_mode, elapsed_ms,
        )

        # ── Phase 2: build the LLM prompt ──
        system_prompt = _get_sec_qa_prompt()

        # Format search results as context for the LLM
        if results:
            context_parts = ["以下是从知识库中检索到的相关文档片段：\n"]
            for i, r in enumerate(results, 1):
                source = r.get("source", "")
                heading = r.get("heading", "")
                text = r.get("text", "")[:1500]
                score = r.get("score", 0.0)
                match_type = r.get("match_type", "")
                context_parts.append(
                    f"---\n[{i}] 来源: {source} | 标题: {heading} | "
                    f"相关度: {score:.2f} | 匹配类型: {match_type}\n{text}\n"
                )
            search_context = "\n".join(context_parts)
        else:
            search_context = "知识库中未找到相关文档。请基于你的安全知识回答。"

        user_message = (
            f"用户问题：{content}\n\n"
            f"---\n{search_context}\n---\n"
            f"请基于以上知识库检索结果回答用户的问题。"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # ── Phase 3: single LLM call (streaming if callback provided) ──
        if on_stream is not None:
            response = await provider.chat_stream_with_retry(
                messages=messages,
                model=model,
                on_content_delta=on_stream,
            )
        else:
            response = await provider.chat_with_retry(
                messages=messages,
                model=model,
            )

        answer = response.content or ""
        if not answer.strip():
            logger.warning("[fast-sec-qa] LLM returned empty content, falling back")
            return None

        elapsed = time.monotonic() - t0
        logger.info(
            "[fast-sec-qa] completed in {:.1f}s ({} chars)",
            elapsed, len(answer),
        )

        meta["_fast_sec_qa"] = True
        meta["_kb_sources"] = [
            r.get("source", "") for r in results if r.get("source")
        ]
        meta["_kb_search_mode"] = search_mode
        meta["_agent_name"] = "sec_qa"

        return OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=answer,
            metadata=meta,
        )

    except Exception as exc:
        logger.warning("[fast-sec-qa] failed ({}), falling back to orchestrator", exc)
        return None
