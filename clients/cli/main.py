"""Reference CLI client. Proves the game is 100% API-driven.

Usage:
    ogame-cli register <user> <pass>
    ogame-cli login <user> <pass>
    ogame-cli catalog
    ogame-cli onboard <galaxy> <planet> <race>
    ogame-cli me
    ogame-cli build <base_id> <building_key> [target_mineral]
    ogame-cli train <base_id> <unit_key> [quantity]
    ogame-cli attack <target_base_id> <force>   # force = "soldier:10,tank:2"
    ogame-cli reports
    ogame-cli recall <mission_id>               # retirar una flota en vuelo
    ogame-cli moons                             # lunas alcanzables
    ogame-cli expedition <moon_key>
    ogame-cli players                           # scoreboard (incl. NPCs) y sus bases
    ogame-cli ranking                           # tabla de posiciones
    ogame-cli research <tech_key>               # investigar tecnología
    ogame-cli alliances                         # listar alianzas
    ogame-cli alliance-create <nombre> <tag> [tipo]  # crear (tipo: full|defensive|nonaggression)
    ogame-cli alliance-join <id>                # unirse
    ogame-cli alliance-leave                    # salir
    ogame-cli alliance-transfer <to_id> <mineral> <cantidad>  # comercio entre aliados
    ogame-cli tick                              # avanzar el mundo ahora (turnos NPC)
    ogame-cli notifications                     # ver notificaciones
    ogame-cli read                              # marcar todas como leídas

Env: API_URL (default http://localhost:8000). Token cached in ~/.ogame_token.
"""
import json
import os
import sys
from pathlib import Path

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8000")
TOKEN_FILE = Path.home() / ".ogame_token"


def _token() -> str | None:
    return TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else None


def _headers() -> dict:
    tok = _token()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _show(resp: httpx.Response) -> None:
    try:
        print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
    except ValueError:
        print(resp.text)
    if resp.is_error:
        sys.exit(1)


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    cmd, rest = args[0], args[1:]

    with httpx.Client(base_url=API_URL, timeout=15) as client:
        if cmd == "register":
            r = client.post(
                "/api/v1/auth/register", json={"username": rest[0], "password": rest[1]}
            )
            if not r.is_error:
                TOKEN_FILE.write_text(r.json()["access_token"])
            _show(r)
        elif cmd == "login":
            r = client.post("/api/v1/auth/login", json={"username": rest[0], "password": rest[1]})
            if not r.is_error:
                TOKEN_FILE.write_text(r.json()["access_token"])
            _show(r)
        elif cmd == "catalog":
            _show(client.get("/api/v1/catalog"))
        elif cmd == "onboard":
            _show(
                client.post(
                    "/api/v1/players/onboard",
                    headers=_headers(),
                    json={"galaxy_key": rest[0], "planet_key": rest[1], "race_key": rest[2]},
                )
            )
        elif cmd == "me":
            _show(client.get("/api/v1/players/me", headers=_headers()))
        elif cmd == "build":
            payload = {"building_key": rest[1]}
            if len(rest) > 2:
                payload["target_mineral"] = rest[2]
            _show(client.post(f"/api/v1/bases/{rest[0]}/build", headers=_headers(), json=payload))
        elif cmd == "train":
            payload = {"unit_key": rest[1]}
            if len(rest) > 2:
                payload["quantity"] = int(rest[2])
            _show(client.post(f"/api/v1/bases/{rest[0]}/train", headers=_headers(), json=payload))
        elif cmd == "attack":
            force = {}
            for part in rest[1].split(","):
                unit, qty = part.split(":")
                force[unit] = int(qty)
            _show(
                client.post(
                    "/api/v1/combat/attack",
                    headers=_headers(),
                    json={"target_base_id": int(rest[0]), "force": force},
                )
            )
        elif cmd == "reports":
            _show(client.get("/api/v1/combat/reports", headers=_headers()))
        elif cmd == "recall":
            _show(
                client.post(f"/api/v1/combat/missions/{rest[0]}/recall", headers=_headers())
            )
        elif cmd == "moons":
            _show(client.get("/api/v1/expeditions/moons", headers=_headers()))
        elif cmd == "expedition":
            _show(
                client.post(
                    "/api/v1/expeditions", headers=_headers(), json={"moon_key": rest[0]}
                )
            )
        elif cmd == "players":
            _show(client.get("/api/v1/players", headers=_headers()))
        elif cmd == "ranking":
            _show(client.get("/api/v1/players/ranking", headers=_headers()))
        elif cmd == "research":
            _show(client.post("/api/v1/research", headers=_headers(), json={"tech_key": rest[0]}))
        elif cmd == "alliances":
            _show(client.get("/api/v1/alliances", headers=_headers()))
        elif cmd == "alliance-ranking":
            _show(client.get("/api/v1/alliances/ranking", headers=_headers()))
        elif cmd == "alliance-create":
            body = {"name": rest[0], "tag": rest[1]}
            if len(rest) > 2:
                body["type"] = rest[2]
            _show(client.post("/api/v1/alliances", headers=_headers(), json=body))
        elif cmd == "alliance-join":
            _show(client.post(f"/api/v1/alliances/{rest[0]}/join", headers=_headers()))
        elif cmd == "alliance-leave":
            _show(client.post("/api/v1/alliances/leave", headers=_headers()))
        elif cmd == "alliance-transfer":
            _show(client.post("/api/v1/alliances/transfer", headers=_headers(),
                json={"to_player_id": int(rest[0]), "mineral": rest[1], "amount": float(rest[2])}))
        elif cmd == "tick":
            _show(client.post("/api/v1/admin/tick", headers=_headers()))
        elif cmd == "notifications":
            _show(client.get("/api/v1/notifications", headers=_headers()))
        elif cmd == "read":
            _show(client.post("/api/v1/notifications/read", headers=_headers(), json={}))
        else:
            print(f"Comando desconocido: {cmd}")
            print(__doc__)
            sys.exit(1)


if __name__ == "__main__":
    main()
