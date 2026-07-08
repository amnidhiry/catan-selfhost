# Self-Hosted Catan

A self-hostable, LAN-friendly game of Catan you run yourself and play with friends
in the browser — no accounts, no internet round-trips, no ads. Built on the
[`catanatron`](https://github.com/bcollazo/catanatron) rules engine.

- **Backend** — FastAPI + WebSocket server wrapping `catanatron_core`
  ([`catan-server/`](catan-server/)).
- **Frontend** — React + Vite SVG board served by nginx
  ([`catan-frontend/`](catan-frontend/)).
- **Wire protocol** — a single documented contract both sides implement
  ([`docs/websocket_event_schema.md`](docs/websocket_event_schema.md)).

## Player counts

| Mode | Players | Board | Win |
|---|---|---|---|
| **Duel** (`mini_2p`) | 2 | 7-hex island, 3 ports | 8 VP |
| **Standard** | 3–4 | classic 19-hex | 10 VP |

**Bots.** The host can add AI opponents (powered by catanatron's bots) to fill
seats — they count as players, so 2 humans + 1–2 bots gives you a full-board
standard game, the best-feeling way to play with only two people. Difficulty:
*Normal* (AlphaBeta search, plays a strong game, sub-second moves) or *Easy*
(random). Bots also let 3 friends play a 4-player game.

> **5–6 players is not supported yet.** The catanatron engine is hard-capped at
> 4 players (its `Color` enum has only RED/BLUE/ORANGE/WHITE). Supporting 5–6
> requires forking the engine to add colors, a larger map template, and the
> "special building phase." Tracked in [Roadmap](#roadmap).

**House rules.** The host can toggle *Generous start* (collect starting
resources from **both** initial settlements, not just the second — a deviation
from official rules) before starting.

## Quick start (LAN)

Requires [Docker](https://docs.docker.com/get-docker/) with Compose.

```bash
docker compose up -d --build
```

Then, on the host machine, find your LAN IP:

```bash
# macOS
ipconfig getifaddr en0
# Linux
hostname -I | awk '{print $1}'
```

Everyone on the same network opens **`http://<that-ip>:8080`**. One person clicks
*Host a new island*, shares the 4-letter room code, and the rest *Join* with it.
The host picks the mode and starts once enough seats are filled.

The frontend container serves the app **and** reverse-proxies `/rooms` + `/ws` to
the backend, so players only ever need that one URL and port.

To stop: `docker compose down` (game snapshots persist in the `catan_rooms`
volume; add `-v` to wipe them).

### Homelab / Traefik variant

If you already run Traefik (e.g. behind Tailscale) and want a hostname instead of
a raw port:

```bash
docker compose -f docker-compose.homelab.yml up -d --build
```

Edit the `Host()` rule in that file first. There is **no auth beyond room codes** —
keep it on an internal-only entrypoint.

## Development (without Docker)

**Backend:**

```bash
cd catan-server
pip install fastapi "uvicorn[standard]" \
  "git+https://github.com/bcollazo/catanatron.git"
python tests/test_smoke.py        # drives full games end-to-end
uvicorn server.main:app --reload  # http://localhost:8000
```

> The Docker image pins catanatron to `master` on purpose: the PyPI release lacks
> the domestic-trade actions (`OFFER`/`ACCEPT`/`CONFIRM_TRADE`) this project uses.

**Frontend:**

```bash
cd catan-frontend
npm install
npm run dev                       # http://localhost:5173, proxies to :8000
```

## How it works

- **Rooms & reconnect** — one asyncio lock per room around every `game.execute()`
  keeps state single-writer correct. A dropped socket is a *disconnect*, not a
  *leave*: seats are keyed by a `rejoin_token` (stored in `localStorage`) so you
  can refresh or lose Wi-Fi and rejoin your seat mid-game.
- **Hidden information** — the server never ships raw game state. Every message
  passes through `serialize_for(game, viewer)`, which reduces opponents' hands to
  counts and hides VP cards. See [`catan-server/server/serializer.py`](catan-server/server/serializer.py).
- **Legal moves** — the board only lets you click spots the server returned in
  `playable_actions`; nothing is validated client-side.
- **Persistence** — each room is pickled to `/data` after every action, so a
  container restart doesn't end game night.

Full message-by-message protocol:
[`docs/websocket_event_schema.md`](docs/websocket_event_schema.md).

## Repository layout

```
.
├── docker-compose.yml            # LAN deploy (primary) — both services
├── docker-compose.homelab.yml    # Traefik/Tailscale deploy
├── docs/
│   └── websocket_event_schema.md # the wire contract
├── catan-server/                 # FastAPI + WebSocket backend
│   ├── server/                   # rooms, serializer, game_config, main
│   └── tests/test_smoke.py
└── catan-frontend/               # React + Vite + nginx
    ├── src/                      # App, Board, TradePanel, catanClient
    └── nginx.conf                # serves build + proxies to backend
```

## Roadmap

- **5–6 players** — fork catanatron: extend the `Color` enum, add a 5–6 player
  `MapTemplate`, and implement the special building phase.
- **Longest-road tie-after-break** edge case: add a unit test.
- **Per-player trade targeting** — offers currently go to the whole table.
