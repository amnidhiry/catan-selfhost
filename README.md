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
| **Expansion** (`expansion`) | 5–6 | 37-hex XL island, 12 ports | 10 VP |

**5–6 players.** catanatron's `Color` enum ships with only 4 members, but its
core state is player-count agnostic — so at startup we extend the enum to 6
(`aenum`, no fork; see [`colors.py`](catan-server/server/colors.py)) and add a
larger, port-validated board ([`game_config.py`](catan-server/server/game_config.py)).
The official "special building phase" isn't modelled — the expansion board plays
with standard turn order (see [Roadmap](#roadmap)).

**Bots.** The host can add AI opponents (powered by catanatron's bots) to fill
seats — they count as players, so 2 humans + 1–2 bots gives you a full-board
standard game, the best-feeling way to play with only two people. Difficulty:
*Normal* (AlphaBeta search, plays a strong game, sub-second moves) or *Easy*
(random). Bots also evaluate and accept chat trade offers (a cheap heuristic —
they take a clearly favourable, card-count-neutral swap).

**House rules.** Before starting, the host can toggle *Generous start* (collect
starting resources from **both** initial settlements) and an optional **turn
timer** (60/90/120s) that auto-ends a turn if the player stalls after rolling.

## Quick start (LAN)

Requires [Docker](https://docs.docker.com/get-docker/) with Compose. On any
machine — clone, (optionally) add an API key, and bring it up. The first build
takes a few minutes (it compiles the frontend and installs the pinned engine);
after that it's cached, so it starts fast — much like a Docker image, but built
from source so you always have the code.

```bash
git clone https://github.com/amnidhiry/catan-selfhost.git
cd catan-selfhost

# Optional: enable AI bot chat. Without this, bots still play — they just
# don't chat via Claude. The .env file is gitignored (never committed).
cp .env.example .env         # then edit .env and paste your ANTHROPIC_API_KEY

docker compose up -d --build
```

To update the machine later: `git pull && docker compose up -d --build`.

Then, on the host machine, find your LAN IP:

```bash
# macOS
ipconfig getifaddr en0
# Linux
hostname -I | awk '{print $1}'
```

Everyone on the same network opens **`http://<that-ip>:2517`**. One person clicks
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

- **5–6 special building phase** — the expansion board plays with standard turn
  order; the official post-turn "special building phase" isn't modelled yet.
- **Longest-road tie-after-break** edge case: add a unit test.
- **Per-player trade targeting** — offers currently go to the whole table.
