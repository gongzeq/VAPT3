"""Patch step1.stdin in the wf_6ce140c2 instance, and reproduce step3
command construction to see exactly which URL trips the SSRF guard."""
import base64
import json
import re
import shlex
from pathlib import Path

WF_PATH = Path('/home/administrator/.secbot/workspace/workflows/workflows.json')

# ---------- 1) Patch step1 stdin (wrap urls in "...") ----------
data = json.loads(WF_PATH.read_text())
items = data.get('items') if isinstance(data, dict) else data
patched = 0
for wf in items:
    if wf.get('id') != 'wf_6ce140c2':
        continue
    for s in wf.get('steps', []):
        if s.get('id') == 'step1':
            old = s['args'].get('stdin', '')
            new = old.replace('"urls": ${inputs.urls}', '"urls": "${inputs.urls}"')
            if new != old:
                s['args']['stdin'] = new
                patched += 1
                print('[step1.stdin] BEFORE:', old)
                print('[step1.stdin] AFTER :', new)
WF_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
print(f'patched {patched} step1.stdin\n')

# ---------- 2) Reproduce step3 command and scan for URLs ----------
# Use the latest run's actual interpolated stdin to be realistic.
runs_path = Path('/home/administrator/.secbot/workspace/workflows/runs.jsonl')
last = runs_path.read_text().splitlines()[-1]
run = json.loads(last)
step1_parsed = (run.get('stepResults', {}).get('step1', {}) or {}).get('output', {}).get('parsed') or {}
step2_parsed = (run.get('stepResults', {}).get('step2', {}) or {}).get('output', {}).get('parsed') or {}
rspamd_score = run.get('inputs', {}).get('rspamd_score', '0')

# Same template as templates.py / instance step3
stdin_str = (
    '{"step1": ' + json.dumps(step1_parsed, ensure_ascii=False)
    + ', "step2": ' + json.dumps(step2_parsed, ensure_ascii=False)
    + ', "rspamd_score": "' + str(rspamd_score) + '"}'
)
print(f'rendered step3 stdin (len={len(stdin_str)}):')
print(stdin_str[:400], '...\n')

# Same code as in instance step3.args.code
code = ''
for wf in items:
    if wf.get('id') == 'wf_6ce140c2':
        for s in wf.get('steps', []):
            if s.get('id') == 'step3':
                code = s['args'].get('code', '')

# Build command exactly like _build_command (kind=python, with stdin):
encoded = base64.b64encode(stdin_str.encode('utf-8')).decode('ascii')
body = f'python3 -c {shlex.quote(code)}'
command = f"printf %s {shlex.quote(encoded)} | base64 -d | {body}"

print(f'final command length: {len(command)}')

# Scan URLs in command using the SAME regex as security/network.py
URL_RE = re.compile(r"https?://[^\s\"'`;|<>]+", re.IGNORECASE)
hits = list(URL_RE.finditer(command))
print(f'URLs matched in final command: {len(hits)}')
for m in hits[:10]:
    pos = m.start()
    ctx = command[max(0, pos - 30):min(len(command), pos + 100)]
    # which segment? base64 part vs code part
    prefix = command[:pos]
    in_base64 = "printf %s '" in prefix and "' | base64" not in prefix
    print(f'  URL: {m.group()!r}  pos={pos}  in_base64_arg={in_base64}')
    print(f'    ctx: ...{ctx!r}...')
