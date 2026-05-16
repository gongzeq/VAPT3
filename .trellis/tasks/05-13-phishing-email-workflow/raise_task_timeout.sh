#!/usr/bin/env bash
# Raise rspamd task_timeout from 8s -> 20s so AI_PHISHING LLM (~13s) can finish.
# Uses local.d/options.inc (rspamd's official override-merge location).
set -e

LOCALD=/etc/rspamd/local.d
OUT=$LOCALD/options.inc

mkdir -p "$LOCALD"

cat > "$OUT" <<'EOF'
# Override task_timeout so the AI_PHISHING_DETECT lua callback (which calls
# secbot LLM, ~13s) can complete before rspamd cleans up the task.
task_timeout = 20s;
EOF

chown root:_rspamd "$OUT" 2>/dev/null || true
chmod 0644 "$OUT"

echo "[1/3] wrote $OUT:"
cat "$OUT"

echo
echo "[2/3] configtest..."
rspamadm configtest

echo
echo "[3/3] reload..."
systemctl reload rspamd
sleep 1
systemctl is-active rspamd

echo
echo "Effective task_timeout in running config:"
rspamadm configdump 2>/dev/null | grep -E "^\s*task_timeout" | head -3
