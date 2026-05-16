#!/usr/bin/env bash
# 一键部署钓鱼邮件检测 Lua 到 rspamd 并自检
# 用法：sudo bash /home/administrator/VAPT3/.trellis/tasks/05-13-phishing-email-workflow/deploy_phishing_lua.sh
set -u

REPO_LUA=/home/administrator/VAPT3/.trellis/tasks/05-13-phishing-email-workflow/rspamd.local.lua
TARGET_LUA=/etc/rspamd/lua.local.d/ai_phishing.lua
ORPHAN_LUA=/etc/rspamd/rspamd.local.lua
OLD_PLUGIN_LUA=/etc/rspamd/plugins.d/my_ai_check.lua
OLD_PLUGIN_CONF=/etc/rspamd/local.d/my_ai_check.conf

step() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m+\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31mx\033[0m %s\n' "$*"; }

[ "$EUID" -eq 0 ] || { err "请用 sudo 运行：sudo bash $0"; exit 2; }

step "1/6 校验仓库 lua 存在 + 端口为 18791"
[ -f "$REPO_LUA" ] || { err "找不到 $REPO_LUA"; exit 1; }
if grep -q ':18791/api/workflows/wf_6ce140c2/run' "$REPO_LUA"; then
  ok "仓库 lua 端口为 18791，wf_id=wf_6ce140c2"
else
  err "仓库 lua 端口/wf_id 异常，请检查："
  grep -n 'workflow_run_url' "$REPO_LUA"
  exit 1
fi

step "2/6 拷贝 lua 到 rspamd 自动加载目录"
install -m 0644 -o _rspamd -g _rspamd "$REPO_LUA" "$TARGET_LUA" \
  || { err "拷贝失败"; exit 1; }
ok "已拷贝到 $TARGET_LUA"

step "3/6 清理孤儿/占位文件"
for f in "$ORPHAN_LUA" "$OLD_PLUGIN_LUA" "$OLD_PLUGIN_CONF"; do
  if [ -e "$f" ]; then
    rm -f "$f" && ok "已删除 $f"
  fi
done

step "4/6 rspamadm configtest（校验 lua 语法）"
if rspamadm configtest 2>&1 | tail -n 5; then
  ok "configtest 通过"
else
  err "configtest 失败，请按上方报错修复"
  exit 1
fi

step "5/6 reload rspamd"
systemctl reload rspamd \
  && ok "已 reload" \
  || { err "reload 失败，看 systemctl status rspamd"; exit 1; }
sleep 2

step "6/6 检查 lua 是否被加载（startup 日志）"
journalctl -u rspamd --since '1 minute ago' --no-pager 2>/dev/null \
  | grep -iE 'AI_PHISHING|ai_phishing|lua.local|lua_error|lua_failed|cannot load' \
  | tail -n 30
echo
echo "---- /var/log/rspamd/rspamd.log 最近 50 行 ----"
tail -n 50 /var/log/rspamd/rspamd.log 2>/dev/null \
  | grep -iE 'AI_PHISHING|ai_phishing|lua|error' \
  | tail -n 20

echo
ok "部署完成。下一步：另开终端发测试邮件，并实时盯日志"
echo
echo "  # 实时盯 rspamd 日志（Ctrl+C 终止）："
echo "  sudo tail -f /var/log/rspamd/rspamd.log | grep --line-buffered -iE 'AI_PHISHING|workflow|18791|secbot|phish'"
echo
echo "  # 实时盯 secbot 工作流 run 记录："
echo "  tail -f /home/administrator/.secbot/workspace/workflows/runs.jsonl"
echo
echo "  # 发测试邮件（rspamd 评分 >=4 才会触发 LLM 分支）："
echo "  swaks --to v@gdmsa.cn --from attacker@phish.example --server 127.0.0.1:25 \\"
echo "        --header 'Subject: 【紧急】账户冻结' --body 'Please click http://login.example to verify'"
