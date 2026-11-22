#!/usr/bin/env bash
# 授权完成后自动部署到 GitHub Pages
set -uo pipefail
cd /home/user/Doubao/chats/38435942269034754
LOG=site/deploy.log
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
: > "$LOG"

# 1) 等设备授权（最长 14 分钟）
ok=0
for i in $(seq 1 84); do
  if gh auth status >/dev/null 2>&1; then ok=1; break; fi
  sleep 10
done
if [ "$ok" != 1 ]; then say "FAIL 未检测到授权，请重新发码"; exit 1; fi
say "AUTH 已授权"

LOGIN=$(gh api user -q .login 2>>"$LOG")
[ -z "$LOGIN" ] && { say "FAIL 取不到用户名"; exit 1; }
say "USER $LOGIN"

# 2) 建仓库并推送（已存在则复用）
cd site
if ! git remote get-url origin >/dev/null 2>&1; then
  gh repo create portfolio --public --source=. --description "杨之涵 · 作品陈列网站" >>"$LOG" 2>&1 \
    || say "WARN 建仓返回非零（可能已存在）"
  git remote get-url origin >/dev/null 2>&1 || {
    gh api -X POST user/repos -f name=portfolio -f description="杨之涵 · 作品陈列网站" -F private=false >>"$LOG" 2>&1
    git remote add origin "https://github.com/$LOGIN/portfolio.git"
  }
fi
git config credential.helper store
git -c credential.helper= push -q -u origin main >>"$LOG" 2>&1 || {
  say "PUSH 用 gh token 重试"; gh auth setup-git; git push -q -u origin main >>"$LOG" 2>&1 || { say "FAIL 推送失败"; exit 1; }
}
say "PUSH 完成"

# 3) 开启 Pages（根目录 / main 分支）
gh api -X POST "repos/$LOGIN/portfolio/pages" \
  --input <(printf '{"name":"ci","build_type":"legacy","source":{"branch":"main","path":"/"}}') >>"$LOG" 2>&1 \
  || gh api -X PUT "repos/$LOGIN/portfolio/pages" \
       --input <(printf '{"build_type":"legacy","source":{"branch":"main","path":"/"}}') >>"$LOG" 2>&1 \
  || say "WARN Pages 接口返回非零（可能已开启）"

URL="https://$LOGIN.github.io/portfolio/"
say "URL $URL"

# 4) 轮询构建状态（最长 5 分钟）
for i in $(seq 1 30); do
  ST=$(gh api "repos/$LOGIN/portfolio/pages" -q .status 2>/dev/null || echo unknown)
  say "PAGES status=$ST"
  [ "$ST" = "built" ] && break
  sleep 10
done
CODE=$(curl -s -o /dev/null -m 20 -w '%{http_code}' "$URL" || echo 000)
say "CHECK $URL -> HTTP $CODE"
say "DONE"
