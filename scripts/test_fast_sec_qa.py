#!/usr/bin/env python3
"""Test the fast-sec-qa path: classifier + knowledge-search + LLM synthesis.

Usage:
    python scripts/test_fast_sec_qa.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from secbot.agent.fast_sec_qa import is_knowledge_question, fast_sec_qa


def test_classifier() -> None:
    """Test the rule-based knowledge question classifier."""
    print("=" * 60)
    print("  测试1: 预筛分类器 (is_knowledge_question)")
    print("=" * 60)

    # Should be True (knowledge questions)
    knowledge_cases = [
        "什么是SQL注入",
        "XSS跨站脚本攻击的原理是什么",
        "如何防御CSRF攻击",
        "解释一下SSRF漏洞",
        "网络安全法有哪些重要条款",
        "WAF绕过技术有哪些",
        "OWASP Top 10是什么",
        "什么是等保2.0",
        "怎么修复SQL注入漏洞",
        "SQL注入和XSS的区别是什么",
        "介绍一下渗透测试方法论",
        "数据安全法对个人信息保护有什么规定",
    ]

    # Should be False (operational / non-knowledge)
    operational_cases = [
        "扫描 192.168.1.1",
        "对 http://example.com 进行渗透测试",
        "用nmap扫描 10.0.0.0/24",
        "sqlmap -u https://target.com/page?id=1",
        "帮我生成报告",
        "检测目标网站的安全漏洞",
        "hydra -L users.txt -P pass.txt 192.168.1.1 ssh",
        "攻击这台服务器",
        "fscan -h 10.0.0.0/24",
        "你好",
        "",
        "帮我分析这个文件",
    ]

    print("\n  知识问题（应全部为 True）:")
    all_pass = True
    for q in knowledge_cases:
        result = is_knowledge_question(q)
        status = "✅" if result else "❌"
        if not result:
            all_pass = False
        print(f"    {status} [{result}] {q}")

    print("\n  操作请求（应全部为 False）:")
    for q in operational_cases:
        result = is_knowledge_question(q)
        status = "✅" if not result else "❌"
        if result:
            all_pass = False
        print(f"    {status} [{not result}] {q}")

    print(f"\n  分类器结果: {'全部通过 ✅' if all_pass else '有误分类 ❌'}")
    print()


async def test_fast_path() -> None:
    """Test the full fast path with a real LLM call."""
    print("=" * 60)
    print("  测试2: 快速通道端到端 (knowledge-search + LLM)")
    print("=" * 60)

    # Load config to get provider
    from secbot.config.loader import load_config
    from secbot.providers.factory import make_provider

    cfg = load_config()
    provider = make_provider(cfg)
    model = cfg.agents.defaults.model

    test_questions = [
        "什么是SQL注入？如何防御？",
        "XSS攻击的三种类型是什么？",
    ]

    for q in test_questions:
        print(f"\n  问题: {q}")
        print(f"  预筛结果: {is_knowledge_question(q)}")

        if not is_knowledge_question(q):
            print("  ⏭️  跳过（非知识问题）")
            continue

        t0 = time.monotonic()
        result = await fast_sec_qa(
            q, provider, model,
            channel="test", chat_id="test",
        )
        elapsed = time.monotonic() - t0

        if result:
            print(f"  耗时: {elapsed:.1f}s")
            print(f"  回答长度: {len(result.content)} 字符")
            print(f"  回答前200字: {result.content[:200]}...")
            print(f"  fast_sec_qa 标记: {result.metadata.get('_fast_sec_qa', False)}")
        else:
            print(f"  ❌ 快速通道失败 ({elapsed:.1f}s)")

    print()


async def main() -> None:
    test_classifier()
    await test_fast_path()
    print("=" * 60)
    print("  测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
