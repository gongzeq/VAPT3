#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""secbot 子智能体部署自检脚本。

用途：当在一台新主机上部署 nanobot / secbot 后，orchestrator 只会输出
"第一步：资产发现"之类的纯文本规划就结束（没有实际调用 delegate_task），
用该脚本快速定位原因。

覆盖的检查项：
  1) Python / 关键依赖版本
  2) secbot 模块能否正确导入
  3) agents 目录是否存在、5 个 yaml 能否全部加载
  4) 每个专家智能体 scoped_skills 对应的 SKILL.md 是否齐全
  5) 每个专家智能体依赖的外部二进制是否在 PATH（决定 spec.available）
  6) orchestrator 工具表是否成功注册 delegate_task 等 5 个工具
  7) LLM provider / model 是否配置，并提示是否支持 function-calling
  8) 可选：实际发起一次最小 function-calling 探针 (--probe-llm)

用法：
  python scripts/diag_subagents.py
  python scripts/diag_subagents.py --probe-llm     # 实际发起一次 LLM 调用
  python scripts/diag_subagents.py --json          # 机器可读输出
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

# --------------------------------------------------------------------------- #
# 终端配色（在非 tty 下自动降级为纯文本）
# --------------------------------------------------------------------------- #
_IS_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    if not _IS_TTY:
        return text
    return f"\033[{code}m{text}\033[0m"


def ok(t: str) -> str:   return _c("32", f"[ OK ] {t}")
def warn(t: str) -> str: return _c("33", f"[WARN] {t}")
def err(t: str) -> str:  return _c("31", f"[FAIL] {t}")
def info(t: str) -> str: return _c("36", f"[INFO] {t}")


# --------------------------------------------------------------------------- #
# 报告收集
# --------------------------------------------------------------------------- #
class Report:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self.has_fail = False
        self.has_warn = False

    def add(self, name: str, status: str, detail: str = "", hint: str = "") -> None:
        self.items.append({"name": name, "status": status, "detail": detail, "hint": hint})
        if status == "fail":
            self.has_fail = True
            print(err(f"{name} — {detail}"))
            if hint:
                print(f"       └─ 建议: {hint}")
        elif status == "warn":
            self.has_warn = True
            print(warn(f"{name} — {detail}"))
            if hint:
                print(f"       └─ 建议: {hint}")
        else:
            print(ok(f"{name}{' — ' + detail if detail else ''}"))

    def dump_json(self) -> str:
        return json.dumps(
            {
                "ok": not self.has_fail,
                "has_warn": self.has_warn,
                "items": self.items,
            },
            ensure_ascii=False,
            indent=2,
        )


# --------------------------------------------------------------------------- #
# 具体检查
# --------------------------------------------------------------------------- #
EXPECTED_AGENTS = {
    "asset_discovery",
    "port_scan",
    "vuln_scan",
    "weak_password",
    "report",
}


def check_python(rep: Report) -> None:
    v = sys.version_info
    if v < (3, 10):
        rep.add(
            "Python 版本",
            "fail",
            detail=f"{v.major}.{v.minor}.{v.micro} < 3.10",
            hint="secbot 需要 Python >= 3.10，请升级后重装依赖。",
        )
    else:
        rep.add("Python 版本", "pass", detail=f"{v.major}.{v.minor}.{v.micro}")


def check_imports(rep: Report) -> bool:
    must_have = ["yaml", "jsonschema", "loguru", "httpx", "pydantic"]
    missing: list[str] = []
    for m in must_have:
        try:
            __import__(m)
        except Exception as e:
            missing.append(f"{m} ({e.__class__.__name__})")
    if missing:
        rep.add(
            "关键 Python 依赖",
            "fail",
            detail=f"缺失或无法导入: {', '.join(missing)}",
            hint="在项目根目录执行: pip install -e . (或 uv sync)。",
        )
        return False
    rep.add("关键 Python 依赖", "pass", detail=f"{', '.join(must_have)} 均可导入")
    return True


def check_secbot_import(rep: Report, project_root: Path) -> bool:
    # 保证能 import secbot 包
    sys.path.insert(0, str(project_root))
    try:
        import secbot  # noqa: F401
        from secbot.agents.registry import load_agent_registry  # noqa: F401
        from secbot.agent.skills import BUILTIN_SKILLS_DIR  # noqa: F401
        rep.add("secbot 包导入", "pass", detail="secbot / agents.registry / agent.skills 可导入")
        return True
    except Exception as e:
        rep.add(
            "secbot 包导入",
            "fail",
            detail=f"{e.__class__.__name__}: {e}",
            hint="确认你在正确的 repo 根目录，且执行过 pip install -e .。",
        )
        traceback.print_exc()
        return False


def check_agents_dir(rep: Report, project_root: Path) -> Path | None:
    agents_dir = project_root / "secbot" / "agents"
    if not agents_dir.is_dir():
        rep.add(
            "agents 目录",
            "fail",
            detail=f"未找到 {agents_dir}",
            hint="请确认代码完整拉取，或检查安装来源是否包含 secbot/agents/*.yaml。",
        )
        return None
    yamls = sorted(p.stem for p in agents_dir.glob("*.yaml"))
    missing = EXPECTED_AGENTS - set(yamls)
    extra = set(yamls) - EXPECTED_AGENTS
    if missing:
        rep.add(
            "agents yaml 文件",
            "fail",
            detail=f"缺失专家智能体: {sorted(missing)}; 已有: {yamls}",
            hint="从仓库同步 secbot/agents/*.yaml 以及对应的 prompts/*.md。",
        )
        return None
    rep.add("agents yaml 文件", "pass", detail=f"已发现 {yamls}" + (f"，额外: {sorted(extra)}" if extra else ""))
    return agents_dir


def check_registry_load(rep: Report, agents_dir: Path):
    from secbot.agent.skills import BUILTIN_SKILLS_DIR
    from secbot.agents.registry import load_agent_registry, AgentRegistryError

    if not BUILTIN_SKILLS_DIR.is_dir():
        rep.add(
            "内置 skills 目录",
            "fail",
            detail=f"未找到 {BUILTIN_SKILLS_DIR}",
            hint="secbot/skills 缺失会让所有专家智能体被判定为 offline，请恢复该目录。",
        )
        return None
    rep.add("内置 skills 目录", "pass", detail=str(BUILTIN_SKILLS_DIR))

    try:
        registry = load_agent_registry(
            agents_dir,
            skill_names=None,
            skills_root=BUILTIN_SKILLS_DIR,
        )
    except AgentRegistryError as e:
        rep.add(
            "加载 AgentRegistry",
            "fail",
            detail=str(e),
            hint=(
                "registry 任一 yaml/prompt 校验失败即整体终止。"
                "按提示修正对应 yaml 的 name / scoped_skills / system_prompt_file。"
            ),
        )
        return None
    except Exception as e:
        rep.add(
            "加载 AgentRegistry",
            "fail",
            detail=f"{e.__class__.__name__}: {e}",
            hint="多半是 yaml 本身语法错或 prompt 文件缺失。",
        )
        traceback.print_exc()
        return None

    names = registry.names()
    miss = EXPECTED_AGENTS - set(names)
    if miss:
        rep.add(
            "AgentRegistry 内容",
            "fail",
            detail=f"已加载 {names}，缺 {sorted(miss)}",
            hint="orchestrator prompt 的 agent 表会漏项，LLM 不知道可用的 delegate_task 目标。",
        )
    else:
        rep.add("AgentRegistry 内容", "pass", detail=f"{len(names)} 个专家智能体: {names}")
    return registry


def check_agent_availability(rep: Report, registry) -> None:
    if registry is None:
        return
    offline: list[str] = []
    for spec in registry:
        if spec.available:
            rep.add(
                f"agent[{spec.name}]",
                "pass",
                detail=(
                    f"skills={list(spec.scoped_skills)} "
                    f"required_binaries={list(spec.required_binaries) or 'none'}"
                ),
            )
        else:
            offline.append(spec.name)
            rep.add(
                f"agent[{spec.name}]",
                "warn",
                detail=f"offline, missing_binaries={list(spec.missing_binaries)}",
                hint=(
                    "把缺失的二进制加入 PATH（或通过 secbot 配置里的 skillBinaries 指定绝对路径），"
                    "否则 SpawnTool 会在调用时直接返回 'Agent xxx is offline'。"
                ),
            )
    if offline:
        rep.add(
            "整体可用性",
            "warn",
            detail=f"以下 agent 不可用: {offline}",
            hint="orchestrator 仍会把它们列入 prompt；LLM 调度后会被 SpawnTool 拒绝。",
        )


def check_scoped_skills(rep: Report, registry) -> None:
    from secbot.agent.skills import BUILTIN_SKILLS_DIR

    if registry is None:
        return
    missing_dirs: list[str] = []
    missing_md: list[str] = []
    for spec in registry:
        for skill in spec.scoped_skills:
            sd = BUILTIN_SKILLS_DIR / skill
            if not sd.is_dir():
                missing_dirs.append(f"{spec.name}:{skill}")
                continue
            if not (sd / "SKILL.md").is_file():
                missing_md.append(f"{spec.name}:{skill}")
    if missing_dirs:
        rep.add(
            "scoped_skills 目录",
            "fail",
            detail=f"缺失技能目录: {missing_dirs}",
            hint="确认 secbot/skills/<skill>/ 存在且包含 SKILL.md。",
        )
    elif missing_md:
        rep.add(
            "scoped_skills 目录",
            "fail",
            detail=f"缺 SKILL.md: {missing_md}",
            hint="每个技能目录都必须有 SKILL.md。",
        )
    else:
        rep.add("scoped_skills 目录", "pass", detail="所有技能目录齐全")


def _load_skill_binaries(config_path: Path | None) -> tuple[dict[str, str], Path | None]:
    """读取 secbot config.json 中的 tools.skillBinaries 映射。

    返回 (映射, 实际加载到的 config 路径)。当未找到任何 config 时返回 ({}, None)。
    """
    candidates: list[Path] = []
    if config_path:
        candidates.append(config_path)
    else:
        candidates += [
            Path.cwd() / "config.json",
            Path.home() / ".secbot" / "config.json",
        ]
    for p in candidates:
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        tools = (data or {}).get("tools") or {}
        # 同时兼容 camelCase 和 snake_case
        binaries = tools.get("skillBinaries") or tools.get("skill_binaries") or {}
        if isinstance(binaries, dict):
            return {str(k): str(v) for k, v in binaries.items() if isinstance(v, str)}, p
    return {}, None


def check_common_binaries(rep: Report, config_path: Path | None = None) -> None:
    """检查关键外部二进制的可用性。

    优先级：tools.skillBinaries[<name>] (绝对路径) > PATH (shutil.which)。
    与 secbot/skills/<skill>/handler.py 的 _resolve_*_binary() 解析顺序一致。
    """
    mapping = {
        "nmap": "asset_discovery / port_scan",
        "fscan": "asset_discovery / port_scan / vuln_scan",
        "httpx": "asset_discovery (httpx-probe)",
        "nuclei": "vuln_scan (nuclei-template-scan)",
        "ffuf": "vuln_scan (ffuf-*)",
        "sqlmap": "vuln_scan (sqlmap-*)",
        "hydra": "weak_password",
    }
    overrides, config_used = _load_skill_binaries(config_path)
    if config_used:
        rep.add(
            "config.json 加载",
            "pass",
            detail=f"{config_used}  •  skillBinaries keys={sorted(overrides) or '<空>'}",
        )
    else:
        rep.add(
            "config.json 加载",
            "warn",
            detail="未找到 ./config.json 或 ~/.secbot/config.json",
            hint="如已用其他路径，请通过 --config /abs/path/to/config.json 指定。",
        )

    missing: list[str] = []
    config_only: list[str] = []
    for bn, used in mapping.items():
        override = overrides.get(bn)
        path_hit = shutil.which(bn)
        if override:
            ovr = Path(override)
            if ovr.is_file():
                if path_hit:
                    rep.add(
                        f"外部二进制[{bn}]",
                        "pass",
                        detail=f"config={override}  •  PATH={path_hit}  ({used})",
                    )
                else:
                    config_only.append(bn)
                    rep.add(
                        f"外部二进制[{bn}]",
                        "pass",
                        detail=f"config={override}  •  PATH 未找到  ({used})",
                        hint=(
                            "skill handler 与 AgentRegistry 已统一识别 config 覆盖："
                            "PATH 直接二进制 / config 指向脚本（如 sqlmap.py）两种安装方式"
                            "都会被 registry 视为可用，无需再加 PATH。"
                        ),
                    )
            else:
                missing.append(bn)
                rep.add(
                    f"外部二进制[{bn}]",
                    "fail",
                    detail=f"config 指向 {override}，但文件不存在  ({used})",
                    hint="检查 config.json 里 tools.skillBinaries 的路径是否拼错或权限不足。",
                )
        elif path_hit:
            rep.add(f"外部二进制[{bn}]", "pass", detail=f"PATH={path_hit}  ({used})")
        else:
            missing.append(bn)
            rep.add(
                f"外部二进制[{bn}]",
                "warn",
                detail=f"既不在 PATH，也未在 config.skillBinaries 中声明  ({used})",
                hint=(
                    f"两种修法任选一：\n"
                    f"         (a) 安装 {bn} 并把目录加入 PATH（推荐，能让 AgentRegistry.available=True）；\n"
                    f"         (b) 在 config.json 中加 tools.skillBinaries.{bn} = \"/abs/path\""
                    "（仅 skill handler 生效，registry 仍会判 offline）。"
                ),
            )

    if missing:
        rep.add(
            "二进制总结",
            "fail" if any(b in {"nmap", "fscan", "nuclei"} for b in missing) else "warn",
            detail=f"缺失: {missing}",
            hint="缺哪个，对应 agent 就会被 SpawnTool 拒绝，orchestrator 会跳过该步骤或反复重试。",
        )
    if config_only:
        rep.add(
            "registry 盲区提醒",
            "pass",
            detail=f"仅 config 覆盖、PATH 缺失: {config_only}",
            hint=(
                "secbot/agents/registry.py 已支持 skill_binary_overrides，"
                "AgentRegistry 与 skill handler 的二进制解析顺序保持一致 "
                "(config.skillBinaries > PATH)。"
            ),
        )


def check_orchestrator_tools(rep: Report) -> None:
    """模拟 _register_orchestrator_tools，确认 5 个工具都能实例化。"""
    try:
        from secbot.agent.tools.spawn import SpawnTool
        from secbot.agent.tools.blackboard import BlackboardReadTool
        from secbot.agent.tools.approval import RequestApprovalTool
        from secbot.agent.tools.plan import WritePlanTool
        from secbot.agent.tools.message import MessageTool  # noqa: F401
    except Exception as e:
        rep.add(
            "orchestrator 工具导入",
            "fail",
            detail=f"{e.__class__.__name__}: {e}",
            hint="orchestrator 的 5 个核心工具类无法导入，代码不完整或版本不匹配。",
        )
        return

    expected = {"delegate_task", "read_blackboard", "request_approval", "write_plan", "message"}
    found = set()

    class _DummyMgr:
        def get_running_count(self): return 0
        max_concurrent_subagents = 1
        agent_registry = None

    try:
        found.add(SpawnTool(manager=_DummyMgr()).name)  # type: ignore[arg-type]
        found.add(BlackboardReadTool(blackboard=lambda: None).name)
        found.add(RequestApprovalTool().name)
        found.add(WritePlanTool(chat_id_getter=lambda: None).name)
        # MessageTool 需要 send_callback / workspace；用最小替身即可：
        from secbot.agent.tools.message import MessageTool as _MT
        async def _cb(*a, **k): return None
        found.add(_MT(send_callback=_cb, workspace=Path(".")).name)
    except Exception as e:
        rep.add(
            "orchestrator 工具实例化",
            "fail",
            detail=f"{e.__class__.__name__}: {e}",
            hint="注册路径异常，排查 secbot.agent.tools 下各工具构造签名。",
        )
        return

    miss = expected - found
    if miss:
        rep.add(
            "orchestrator 工具表",
            "fail",
            detail=f"缺失: {sorted(miss)}",
            hint="工具类 name 属性异常或代码版本不一致。",
        )
    else:
        rep.add("orchestrator 工具表", "pass", detail=f"工具齐全 {sorted(found)}")


def check_llm_env(rep: Report) -> dict:
    """读取典型 LLM 环境变量并提示。"""
    env_keys = {
        "OPENAI_API_KEY": "OpenAI / OpenAI 兼容",
        "OPENAI_BASE_URL": "OpenAI 兼容代理地址",
        "OPENAI_MODEL": "覆盖默认模型名",
        "ANTHROPIC_API_KEY": "Anthropic Claude",
        "AZURE_OPENAI_API_KEY": "Azure OpenAI",
        "AZURE_OPENAI_ENDPOINT": "Azure OpenAI endpoint",
    }
    present = {}
    for k, desc in env_keys.items():
        v = os.environ.get(k)
        if v:
            show = v if len(v) <= 8 or k.endswith("_URL") or k.endswith("_ENDPOINT") else v[:4] + "***" + v[-2:]
            rep.add(f"环境变量[{k}]", "pass", detail=f"{show}  ({desc})")
            present[k] = v
        else:
            rep.add(f"环境变量[{k}]", "warn", detail=f"未设置  ({desc})", hint="至少需要一组有效的 LLM 凭据。")
    # 给出总结
    if "OPENAI_API_KEY" not in present and "ANTHROPIC_API_KEY" not in present and "AZURE_OPENAI_API_KEY" not in present:
        rep.add(
            "LLM 凭据总结",
            "fail",
            detail="没有发现任何可用的 LLM key",
            hint="至少设置其中之一；否则 orchestrator 调用 LLM 将失败或直接降级为纯文本。",
        )
    return present


def probe_llm_function_call(rep: Report) -> None:
    """
    发起最小 function-calling 探针，验证当前 LLM 端点支持 tool_calls。
    这个检查最关键：很多国产/自部署 OpenAI 兼容服务不支持 tool_calls，
    表现就是 orchestrator 只输出"第一步：资产发现"文字，没有 delegate_task。
    """
    try:
        import httpx  # noqa: F401
        from openai import OpenAI
    except Exception as e:
        rep.add(
            "function-calling 探针",
            "warn",
            detail=f"未安装 openai SDK: {e.__class__.__name__}",
            hint="pip install openai 后重试，或跳过该检查。",
        )
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL")
    model = os.environ.get("OPENAI_MODEL") or os.environ.get("SECBOT_MODEL")
    if not api_key:
        rep.add(
            "function-calling 探针",
            "warn",
            detail="未设置 OPENAI_API_KEY，跳过 tool_calls 探针",
            hint="导出 OPENAI_API_KEY (必要时 OPENAI_BASE_URL/OPENAI_MODEL) 后再跑 --probe-llm。",
        )
        return
    if not model:
        rep.add(
            "function-calling 探针",
            "warn",
            detail="未设置 OPENAI_MODEL，默认用 gpt-4o-mini 试探",
        )
        model = "gpt-4o-mini"

    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    tools = [{
        "type": "function",
        "function": {
            "name": "delegate_task",
            "description": "Delegate work to an expert agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "task":  {"type": "string"},
                },
                "required": ["agent", "task"],
            },
        },
    }]
    try:
        resp = client.chat.completions.create(
            model=model,
            tools=tools,
            tool_choice="auto",
            messages=[
                {"role": "system", "content": "You must call delegate_task with agent=asset_discovery."},
                {"role": "user", "content": "扫描 10.0.0.0/24 的资产"},
            ],
            timeout=30,
        )
    except Exception as e:
        rep.add(
            "function-calling 探针",
            "fail",
            detail=f"{e.__class__.__name__}: {e}",
            hint="模型接口调用失败，先排查网络 / base_url / api_key / model 名是否正确。",
        )
        return

    msg = resp.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls:
        fn = tool_calls[0].function
        rep.add(
            "function-calling 探针",
            "pass",
            detail=f"模型返回 tool_calls: {fn.name}({fn.arguments})",
        )
    else:
        rep.add(
            "function-calling 探针",
            "fail",
            detail=f"模型没有返回 tool_calls，只给了文本: {repr((msg.content or '')[:160])}",
            hint=(
                "这与你看到的现象一致：orchestrator 不会调度子智能体。可能原因：\n"
                "         (a) 模型本身不支持 OpenAI function calling（换一款，如 gpt-4o-mini / qwen2.5 / deepseek-chat 新版）；\n"
                "         (b) OPENAI_BASE_URL 指向的代理剥离了 tools/tool_calls 字段；\n"
                "         (c) 供应商需要特殊参数（如 Dashscope 的 enable_search=false）才能启用 function-call。"
            ),
        )


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe-llm", action="store_true", help="实际调用一次 LLM，检测 function-calling")
    ap.add_argument("--json", action="store_true", help="只输出机器可读 JSON 结果")
    ap.add_argument("--project-root", default=None, help="覆盖自动检测的项目根目录")
    ap.add_argument("--config", default=None, help="指定 secbot config.json 路径（默认依次试 ./config.json 与 ~/.secbot/config.json）")
    args = ap.parse_args()

    project_root = Path(args.project_root).resolve() if args.project_root else Path(__file__).resolve().parent.parent
    config_path = Path(args.config).resolve() if args.config else None

    if not args.json:
        print(info(f"secbot 子智能体自检  •  项目根: {project_root}"))
        print("-" * 72)

    rep = Report()

    check_python(rep)
    if not check_imports(rep):
        if args.json:
            print(rep.dump_json())
        return 1 if rep.has_fail else 0

    if not check_secbot_import(rep, project_root):
        if args.json:
            print(rep.dump_json())
        return 1

    agents_dir = check_agents_dir(rep, project_root)
    registry = check_registry_load(rep, agents_dir) if agents_dir else None
    check_scoped_skills(rep, registry)
    check_agent_availability(rep, registry)
    check_common_binaries(rep, config_path)
    check_orchestrator_tools(rep)
    check_llm_env(rep)

    if args.probe_llm:
        probe_llm_function_call(rep)
    else:
        rep.add(
            "function-calling 探针",
            "warn",
            detail="未执行（加 --probe-llm 开启）",
            hint="这通常是 orchestrator 不调度子智能体的头号原因，建议至少跑一次。",
        )

    print("-" * 72)
    if rep.has_fail:
        print(err("结论: 存在阻塞性问题，请先修复上面所有 [FAIL] 项。"))
    elif rep.has_warn:
        print(warn("结论: 基本能跑，但有需要关注的警告（二进制缺失 / LLM 凭据 / function-calling）。"))
    else:
        print(ok("结论: 子智能体侧全部通过。若仍不工作，请开 debug 日志观察 orchestrator 的 tool_calls。"))

    if args.json:
        print(rep.dump_json())
    return 1 if rep.has_fail else 0


if __name__ == "__main__":
    sys.exit(main())
