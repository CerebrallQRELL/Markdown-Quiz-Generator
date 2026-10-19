#!/bin/sh
set -eu
cd "$(dirname "$0")"
command -v docker >/dev/null || { echo 'Install Docker Engine and its Compose plugin first.'; exit 1; }
docker compose version >/dev/null
if [ ! -f .env ]; then
  umask 077
  token=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
  printf 'QUIZ_API_TOKEN=%s\nOLLAMA_MODEL=qwen2.5-coder:7b\n' "$token" > .env
fi
docker pull python:3.13-alpine
docker compose up -d --build
# Retry startup without requiring curl on the server.
ready=0
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if docker compose exec -T ollama ollama list >/dev/null 2>&1; then ready=1; break; fi
  sleep 3
done
[ "$ready" = 1 ] || { echo 'Ollama did not become ready; inspect docker compose logs.'; exit 1; }
model=$(sed -n 's/^OLLAMA_MODEL=//p' .env)
docker compose exec -T ollama ollama pull "${model:-qwen2.5-coder:7b}"
echo 'Ready. Token is in deployment/.env. Connect through an SSH tunnel or HTTPS reverse proxy; see DEPLOYMENT.md.'
