"""Built-in workflow templates exposed via ``GET /api/workflows/_templates``.

PRD: ``.trellis/tasks/05-13-phishing-email-workflow/prd.md``.

Templates here are *factory functions* that return a fresh
:class:`Workflow` each call — never share a mutable instance, the API
clones it before returning so the editor can mutate freely.

The wire shape (camelCase) for each catalogue item is::

    {
        "id":          "phishing-email-detect",
        "name":        "钓鱼邮件检测",
        "description": "...",
        "tags":        ["email", "phishing", "llm"],
        "workflow":    {<WorkflowDraft>}      # already camelCase
    }

The ``workflow`` payload omits ``id`` / ``createdAtMs`` / ``updatedAtMs``
so the WebUI can drop it straight into the editor as a draft (see
``webui/src/lib/workflow-client.ts#WorkflowDraft``).
"""

from __future__ import annotations

from typing import Any

from secbot.workflow.types import (
    Workflow,
    WorkflowInput,
    WorkflowStep,
)
from secbot.workflow.scripts import (
    PHISHING_STEP1_CODE,
    PHISHING_STEP3_CODE,
)


# ---------------------------------------------------------------------------
# Phishing email detection — 3-step (script → llm → script) MVP
# ---------------------------------------------------------------------------


_PHISHING_LLM_SYSTEM = (
    "你是一个邮件安全分析专家。判断邮件是否为钓鱼邮件，"
    "只输出 JSON，不输出多余文字。"
)

_PHISHING_LLM_USER = (
    "请分析以下邮件特征，判断是否为钓鱼邮件，并输出 JSON：\n"
    "{\n"
    '  "is_phishing": true|false,\n'
    '  "confidence": 0.0-1.0,\n'
    '  "risk_level": "high|medium|low|safe",\n'
    '  "reason": "简要说明判断依据（≤200 字）",\n'
    '  "risk_factors": ["可疑特征 1", "可疑特征 2"],\n'
    '  "suggested_action": "拒绝|隔离|标记|放行"\n'
    "}\n\n"
    "邮件特征（已脱敏）：\n"
    "- 发件人域名：${steps.step1.result.parsed.features.sender_domain}\n"
    "- 发件人前缀：${steps.step1.result.parsed.features.sender_local}\n"
    "- 主题：${steps.step1.result.parsed.features.subject}\n"
    "- 正文摘要：${steps.step1.result.parsed.features.body_excerpt}\n"
    "- 链接数量：${steps.step1.result.parsed.features.url_count}\n"
    "- 可疑链接域：${steps.step1.result.parsed.features.suspicious_domains}\n"
    "- rspamd 评分：${inputs.rspamd_score}\n"
)


def _phishing_email_template() -> dict[str, Any]:
    wf = Workflow.new(
        name="钓鱼邮件检测",
        description=(
            "rspamd → secbot workflow 同步调用：脚本预筛 + LLM 兜底，"
            "step3 输出扁平 JSON 供 Lua 插件读取 add_score。"
        ),
        tags=["email", "phishing", "llm"],
        inputs=[
            WorkflowInput(
                name="sender",
                label="发件人",
                type="string",
                required=True,
                description="完整邮箱地址，如 alice@example.com",
            ),
            WorkflowInput(
                name="subject",
                label="主题",
                type="string",
                required=True,
            ),
            WorkflowInput(
                name="body",
                label="正文",
                type="string",
                required=True,
                description="纯文本正文（HTML 由 rspamd 预先去标签）",
            ),
            WorkflowInput(
                name="urls",
                label="链接 JSON",
                type="string",
                required=False,
                default="[]",
                description='JSON 字符串列表，例如 ["http://a.com", ...]',
            ),
            WorkflowInput(
                name="recipient",
                label="收件人",
                type="string",
                required=False,
                default="",
            ),
            WorkflowInput(
                name="rspamd_score",
                label="rspamd 评分",
                type="string",
                required=True,
                description="字符串保留精度，例如 \"6.5\"",
            ),
        ],
        steps=[
            WorkflowStep(
                id="step1",
                name="特征提取与缓存查询",
                kind="script",
                ref="python",
                args={
                    "kind": "python",
                    "timeoutMs": 8000,
                    "code": PHISHING_STEP1_CODE,
                    "stdin": (
                        # All placeholders sit inside ``"..."`` JSON
                        # string literals — combined with the
                        # ``_sub`` JSON-escape rule in ``expr.py`` this
                        # tolerates ``\n``, quotes, backslashes and
                        # empty values without breaking ``stdin`` JSON.
                        # ``urls`` is also wrapped: lua sends it as a
                        # JSON-encoded string and step1 ``json.loads``
                        # it again (dual-shape — see scripts.py).
                        '{"sender": "${inputs.sender}",'
                        ' "subject": "${inputs.subject}",'
                        ' "body": "${inputs.body}",'
                        ' "urls": "${inputs.urls}",'
                        ' "recipient": "${inputs.recipient}",'
                        ' "rspamd_score": "${inputs.rspamd_score}"}'
                    ),
                },
                on_error="continue",
                retry=0,
            ),
            WorkflowStep(
                id="step2",
                name="LLM 判定",
                kind="llm",
                ref="default",
                args={
                    "systemPrompt": _PHISHING_LLM_SYSTEM,
                    "userPrompt": _PHISHING_LLM_USER,
                    "temperature": 0.1,
                    # 1500 是给非 reasoning 模型的安全余量；reasoning
                    # 模型会把大量 token 花在隐藏 chain-of-thought 上，
                    # 600 token 实测被截断（llm_parse: Unterminated
                    # string）。如果上线后仍出现 truncated，应改用
                    # 非 reasoning 模型或继续上调。
                    "maxTokens": 1500,
                    "responseFormat": "json",
                },
                # Skip LLM when:
                #   - step1 says cache hit (parsed-from-stdout business
                #     payload — the raw script result is the executor
                #     wrapper {exit_code, stdout, stderr}, the business
                #     fields live under .parsed)
                #   - rspamd_score < 4.0 (likely benign) or > 10.0 (already
                #     decided by other rules), saving an LLM call
                #
                # NOTE: ``eval_bool`` forbids function calls in conditions
                # (no ``float(inputs.x)`` allowed) — we therefore compare
                # against ``step1.result.parsed.rspamd_score`` which step1
                # already coerces to a Python ``float`` before emitting.
                condition=(
                    "steps.step1.result.parsed.cache_hit == False"
                    " and steps.step1.result.parsed.rspamd_score >= 4.0"
                    " and steps.step1.result.parsed.rspamd_score <= 10.0"
                ),
                on_error="continue",
                retry=1,
            ),
            WorkflowStep(
                id="step3",
                name="结果聚合与回写",
                kind="script",
                ref="python",
                args={
                    "kind": "python",
                    "timeoutMs": 8000,
                    "code": PHISHING_STEP3_CODE,
                    "stdin": (
                        # ``.parsed`` exposes the business JSON; using
                        # ``.result`` directly would embed the
                        # {exit_code, stdout, stderr} wrapper instead.
                        # For step2 (LLM, responseFormat=json) ``.parsed``
                        # is the model's structured judgement.
                        '{"step1": ${steps.step1.result.parsed},'
                        ' "step2": ${steps.step2.result.parsed},'
                        ' "rspamd_score": "${inputs.rspamd_score}"}'
                    ),
                },
                on_error="continue",
                retry=0,
            ),
        ],
    )

    payload = wf.to_dict()
    # WorkflowDraft omits server-owned identifiers; the editor will assign
    # its own when the user saves a clone.
    payload.pop("id", None)
    payload.pop("createdAtMs", None)
    payload.pop("updatedAtMs", None)
    payload.pop("scheduleRef", None)

    return {
        "id": "phishing-email-detect",
        "name": "钓鱼邮件检测",
        "description": (
            "Per-Mail 触发：rspamd 同步调用本工作流，"
            "脚本预筛（Redis 7 天去重 + 特征脱敏）→ LLM 判定（confidence + risk_level）"
            " → step3 聚合输出 add_score 给 Lua 插件。"
        ),
        "tags": ["email", "phishing", "llm"],
        "workflow": payload,
    }


# ---------------------------------------------------------------------------
# Public catalogue
# ---------------------------------------------------------------------------


def list_templates() -> list[dict[str, Any]]:
    """Return the built-in template catalogue.

    Each call rebuilds the underlying :class:`Workflow` instances so two
    callers never share mutable state.
    """
    return [_phishing_email_template()]


__all__ = ["list_templates"]
