#!/usr/bin/env bash
# Levanta el server en un puerto libre con una DB SQLite fresca, corre el flujo
# completo por CLI (incluido tick + players) y apaga el server al terminar.
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${PORT:-8099}"
PY=".venv/bin/python"
CLI=".venv/bin/ogame-cli"
DB="demo.db"

export DATABASE_URL="sqlite+aiosqlite:///./${DB}"
export JWT_SECRET="${JWT_SECRET:-demo-secret-key-at-least-32-bytes-long!!}"
export NPC_BRAIN="${NPC_BRAIN:-rules}"   # 'llm' para usar OpenRouter
export API_URL="http://localhost:${PORT}"

rm -f "$DB"

echo "==> Iniciando server en ${API_URL} (NPC_BRAIN=${NPC_BRAIN})"
.venv/bin/uvicorn app.main:app --port "$PORT" >/tmp/ogame_server.log 2>&1 &
SVPID=$!
trap 'kill $SVPID 2>/dev/null || true' EXIT

echo -n "==> Esperando /health "
for _ in $(seq 1 40); do
  if curl -sf "${API_URL}/health" >/dev/null 2>&1; then echo "OK"; break; fi
  echo -n "."; sleep 0.5
done
curl -sf "${API_URL}/health" >/dev/null 2>&1 || { echo " FALLÓ"; cat /tmp/ogame_server.log; exit 1; }

U="alice_$(date +%s)"
echo "==> register ($U)";        $CLI register "$U" secret123 >/dev/null && echo "ok"
echo "==> onboard (mars/martian)"; $CLI onboard milky_way mars martian >/dev/null && echo "ok"
echo "==> build mina de hierro"; $CLI build 1 mine iron
echo "==> train 3 trabajadores"; $CLI train 1 worker 3
echo "==> tick (nacen y juegan las NPC)"; $CLI tick
echo "==> players (scoreboard)"; $CLI players
echo "==> me (estado del jugador)"; $CLI me

echo "==> Demo OK. Server log en /tmp/ogame_server.log"
