#!/usr/bin/env python3
"""Debug test: send scan request and capture ALL WS events including tool results."""
import asyncio
import json
import time
import websockets

WS_URL = "ws://127.0.0.1:8765/"
SCAN_MSG = "扫描http://111.228.2.47:8080，不扫描其他端口"

async def run():
    print(f"[{time.strftime('%H:%M:%S')}] Connecting...")
    async with websockets.connect(WS_URL, max_size=50*1024*1024) as ws:
        await ws.send(json.dumps({"content": SCAN_MSG}))
        print(f"[{time.strftime('%H:%M:%S')}] Sent: {SCAN_MSG}")
        print("="*70)
        
        start = time.time()
        msg_count = 0
        
        while time.time() - start < 900:  # 15 min max
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=90)
            except asyncio.TimeoutError:
                print(f"[{time.strftime('%H:%M:%S')}] No message for 90s, stopping")
                break
            
            msg_count += 1
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[{msg_count}] NON-JSON: {raw[:200]}")
                continue
            
            event = msg.get("event", "")
            ts = time.strftime("%H:%M:%S")
            
            if event == "delta":
                content = msg.get("content", "")
                # Show all deltas that mention key terms
                if any(kw in content for kw in ["create_agent", "Subagent", "subagent", "started", 
                                                  "concurrency", "failed", "error", "unknown",
                                                  "crawl", "katana", "limit"]):
                    print(f"[{ts}] DELTA: {content[:300]}")
                    
            elif event == "activity_event":
                category = msg.get("category", "")
                agent = msg.get("agent", "")
                step = msg.get("step", "")
                
                if category == "tool_result":
                    # Show ALL tool results
                    print(f"[{ts}] TOOL_RESULT [{agent}]: {step[:500]}")
                elif category == "tool_call":
                    print(f"[{ts}] TOOL_CALL [{agent}]: {step[:200]}")
                elif "subagent" in category.lower() or "spawn" in category.lower():
                    print(f"[{ts}] SUBAGENT [{category}] [{agent}]: {step[:300]}")
                    
            elif event == "agent_event":
                evt_type = msg.get("type", "")
                payload = msg.get("payload", {})
                if evt_type in ("subagent_spawned", "subagent_done", "agent_status"):
                    print(f"[{ts}] AGENT_EVENT({evt_type}): {json.dumps(payload, ensure_ascii=False)[:400]}")
                    
            elif event == "message":
                text = msg.get("text", msg.get("content", ""))
                kind = msg.get("kind", "")
                if text and len(str(text)) > 3:
                    print(f"[{ts}] MESSAGE({kind}): {str(text)[:300]}")
                    
            elif event == "turn_end":
                print(f"[{ts}] TURN_END")
                
            elif event in ("ready", "stream_end", "attached", "pong", "session_updated"):
                pass  # skip
            else:
                if event:
                    print(f"[{ts}] {event}: {json.dumps(msg, ensure_ascii=False)[:200]}")
        
        print(f"\nTotal messages: {msg_count}")

if __name__ == "__main__":
    asyncio.run(run())
