#!/usr/bin/env python3
"""End-to-end scan test via WebSocket.

Sends a scan request, monitors all messages for tool errors,
and checks whether a complete report is generated.

WS event format:
  event: "delta"          → streaming text chunk (content field)
  event: "message"        → complete text (text field)
  event: "activity_event" → category, agent, step fields
  event: "agent_event"    → type, payload fields (subagent_done etc.)
  event: "turn_end"       → turn complete
"""

import asyncio
import json
import time

import websockets

WS_URL = "ws://127.0.0.1:8765/"
SCAN_MSG = "扫描http://111.228.2.47:8080，不扫描其他端口"
TIMEOUT_S = 900  # 15 min max

errors: list[str] = []
tool_calls: list[str] = []
subagent_events: list[str] = []
report_paths: list[str] = []
agent_stages: list[str] = []
turn_texts: list[str] = []


async def run_scan():
    print(f"[{time.strftime('%H:%M:%S')}] Connecting to {WS_URL} ...")
    async with websockets.connect(WS_URL, max_size=50 * 1024 * 1024) as ws:
        print(f"[{time.strftime('%H:%M:%S')}] Connected. Sending scan request...")
        await ws.send(json.dumps({"content": SCAN_MSG}))
        print(f"[{time.strftime('%H:%M:%S')}] Sent: {SCAN_MSG}")
        print("=" * 70)

        start = time.time()
        msg_count = 0
        last_activity = start
        current_delta = ""

        while time.time() - start < TIMEOUT_S:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=90)
            except asyncio.TimeoutError:
                elapsed = time.time() - last_activity
                print(f"[{time.strftime('%H:%M:%S')}] No message for {elapsed:.0f}s")
                if elapsed > 180:
                    print("[TIMEOUT] No activity for 3 min, assuming done/stalled.")
                    break
                continue

            msg_count += 1
            last_activity = time.time()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[{msg_count}] RAW (non-JSON): {raw[:200]}")
                continue

            event = msg.get("event", "")
            ts = time.strftime("%H:%M:%S")

            if event == "delta":
                # Streaming text delta
                content = msg.get("content", "")
                if content:
                    current_delta += content
                    # Print key phrases inline
                    if any(kw in content for kw in ["爬虫", "crawl", "漏洞", "vuln", "报告", "report",
                                                      "扫描", "端口", "port", "asset", "资产", "create_agent",
                                                      "阶段", "stage", "完成", "complete", "error", "错误"]):
                        print(f"[{ts}] DELTA: {content[:150]}", end="")

            elif event == "message":
                # Complete message
                text = msg.get("text", msg.get("content", ""))
                kind = msg.get("kind", "")
                if kind == "tool_hint":
                    tool_name = text if isinstance(text, str) else str(text)
                    tool_calls.append(f"hint:{tool_name[:80]}")
                    print(f"[{ts}] TOOL_HINT: {tool_name[:200]}")
                elif kind == "progress":
                    print(f"[{ts}] PROGRESS: {str(text)[:200]}")
                elif text and isinstance(text, str) and len(text) > 5:
                    print(f"[{ts}] MESSAGE: {text[:300]}")
                    if "report" in text.lower() or "报告" in text:
                        report_paths.append(text[:300])

            elif event == "activity_event":
                category = msg.get("category", "")
                agent = msg.get("agent", "")
                step = msg.get("step", "")
                duration = msg.get("duration_ms")

                if category == "tool_call":
                    tool_calls.append(f"{agent}:{step}")
                    dur_str = f" ({duration}ms)" if duration else ""
                    print(f"[{ts}] TOOL_CALL: {agent} → {step[:150]}{dur_str}")
                elif category == "tool_result":
                    result_str = step[:300] if step else ""
                    if "error" in result_str.lower() or "fail" in result_str.lower():
                        errors.append(f"{agent}:{result_str[:200]}")
                        print(f"[{ts}] TOOL_ERROR: {agent} → {result_str[:200]}")
                    else:
                        print(f"[{ts}] TOOL_RESULT: {agent} → {result_str[:150]}")
                elif "subagent" in category or category in ("agent_spawn", "agent_done"):
                    subagent_events.append(f"{agent}:{category}:{step[:100]}")
                    print(f"[{ts}] SUBAGENT({category}): {agent} → {step[:200]}")
                    if "done" in category or "complete" in category:
                        agent_stages.append(f"{agent}:{category}")
                        if "report" in step.lower() or "报告" in step:
                            report_paths.append(step[:300])
                else:
                    print(f"[{ts}] ACTIVITY({category}): {agent} → {step[:150]}")

            elif event == "agent_event":
                evt_type = msg.get("type", "")
                payload = msg.get("payload", {})
                payload_str = json.dumps(payload, ensure_ascii=False)[:300] if payload else ""
                agent_name = payload.get("agent_name", "") if isinstance(payload, dict) else ""
                status = payload.get("status", "") if isinstance(payload, dict) else ""
                result = payload.get("result", "") if isinstance(payload, dict) else ""

                subagent_events.append(f"{evt_type}:{agent_name}:{status}")
                print(f"[{ts}] AGENT_EVENT({evt_type}): {agent_name} status={status}")
                if result:
                    result_str = str(result)[:400]
                    print(f"[{ts}]   RESULT: {result_str}")
                    if "report" in result_str.lower() or "报告" in result_str:
                        report_paths.append(result_str)
                agent_stages.append(f"{agent_name}:{evt_type}:{status}")

            elif event == "turn_end":
                if current_delta.strip():
                    turn_texts.append(current_delta.strip())
                    preview = current_delta.strip()[:500]
                    print(f"[{ts}] TURN_END: {preview}")
                    if "report" in preview.lower() or "报告" in preview:
                        report_paths.append(preview)
                    current_delta = ""
                else:
                    print(f"[{ts}] TURN_END")

            elif event == "error":
                err_str = json.dumps(msg, ensure_ascii=False)[:300]
                errors.append(err_str)
                print(f"[{ts}] ERROR: {err_str}")

            elif event in ("attached", "pong", "session_updated"):
                pass  # control events, skip

            else:
                # Other events
                evt_str = json.dumps(msg, ensure_ascii=False)[:200]
                if "error" in evt_str.lower() or "fail" in evt_str.lower():
                    errors.append(evt_str)
                    print(f"[{ts}] ERROR_IN_{event}: {evt_str}")
                elif event:
                    print(f"[{ts}] {event}: {evt_str[:150]}")

    # Summary
    elapsed = time.time() - start
    print("\n" + "=" * 70)
    print("SCAN TEST SUMMARY")
    print("=" * 70)
    print(f"Duration: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"Total WS messages: {msg_count}")
    print(f"Tool calls: {len(tool_calls)}")
    print(f"Subagent events: {len(subagent_events)}")
    print(f"Agent stages: {agent_stages}")
    print(f"Report paths found: {len(report_paths)}")
    print(f"Errors found: {len(errors)}")
    if errors:
        print("\n--- ERRORS ---")
        for e in errors:
            print(f"  ✗ {e}")
    else:
        print("\n✓ No tool errors detected!")
    if tool_calls:
        print(f"\n--- TOOL CALLS ({len(tool_calls)}) ---")
        for tc in tool_calls:
            print(f"  → {tc}")
    if turn_texts:
        print(f"\n--- TURN TEXTS ({len(turn_texts)}) ---")
        for i, tt in enumerate(turn_texts):
            print(f"  [{i}] {tt[:300]}")
    if report_paths:
        print("\n--- REPORT ---")
        for rp in report_paths:
            print(f"  → {rp[:300]}")


if __name__ == "__main__":
    asyncio.run(run_scan())
