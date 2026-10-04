#!/usr/bin/env bash
# selfsec 一键部署。适合直接粘贴到服务器终端里跑（不需要 SSH，控制台远程连接即可）。
# 幂等：重复执行安全。

set -euo pipefail

REPO="https://github.com/ZhuqiushiCasual/lifesec.git"
DIR="$HOME/selfsec"

echo "==> 1/6  停掉占用 8000 端口的旧栈"
docker ps --format '  运行中: {{.Names}}  {{.Ports}}' || true
for d in "$HOME" /opt /srv /www /root; do
  f="$d/docker-compose.yml"
  if [ -f "$f" ] && ! grep -q "selfsec-api" "$f" 2>/dev/null; then
    echo "  发现旧 compose：$f"
    (cd "$d" && docker compose down) || true
  fi
done

echo "==> 2/6  拉取代码"
if [ -d "$DIR/.git" ]; then
  cd "$DIR" && git pull --ff-only
else
  git clone "$REPO" "$DIR" && cd "$DIR"
fi

echo "==> 3/6  检查 backend/.env"
if [ ! -f backend/.env ]; then
  cat > backend/.env <<'EOF'
OPENAI_API_KEY=PUT_YOUR_KEY_HERE
API_TOKEN=PUT_A_RANDOM_STRING_HERE
EOF
  chmod 600 backend/.env
  echo "  已生成模板"
fi
if grep -q "PUT_YOUR_KEY_HERE\|PUT_A_RANDOM_STRING_HERE" backend/.env; then
  echo
  echo "  !! backend/.env 还没填。请编辑后重新运行本脚本："
  echo "       vi $DIR/backend/.env"
  echo "     API_TOKEN 不能留空（8000 是公网端口，留空等于对全网开放）"
  exit 1
fi

echo "==> 4/6  构建并启动（首次约 1-3 分钟）"
docker compose up -d --build

echo "==> 5/6  等待就绪"
ok=0
for i in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then ok=1; echo "  就绪（第 ${i} 次探测）"; break; fi
  sleep 3
done
[ "$ok" = 1 ] || { echo "  超时未就绪，看日志：cd $DIR && docker compose logs --tail=50 api"; exit 1; }

echo "==> 6/6  自检"
curl -s http://127.0.0.1:8000/health; echo
docker compose ps

IP=$(curl -s -m 5 ifconfig.me || echo "<服务器公网IP>")
echo
echo "完成。手机浏览器访问：  http://$IP:8000"
echo "查看日志：              cd $DIR && docker compose logs -f api"
