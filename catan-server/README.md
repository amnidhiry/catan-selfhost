# Self-Hosted Catan — Backend

FastAPI + WebSocket multiplayer server on top of `catanatron_core` (pinned to a
GitHub commit — PyPI lacks domestic trade). Session state machine and trade
protocol derived from
JSettlers2. See [`../docs/websocket_event_schema.md`](../docs/websocket_event_schema.md)
for the full wire protocol. For deployment (LAN or homelab) see the
[top-level README](../README.md).

## Game modes
- `standard` — 3-4 players, 19-hex board, 10 VP
- `mini_2p` — 2 players, validated 7-hex board with 3 ports (2:1 wheat), 8 VP

Seats can be filled by **bots** (catanatron's `AlphaBetaPlayer` / `WeightedRandomPlayer`);
they count toward a mode's player range. The server drives bot turns in
`main.drive_bots` (each `decide()` runs in a thread — it's CPU-bound).

## Run locally
```bash
pip install fastapi "uvicorn[standard]" \
  "git+https://github.com/bcollazo/catanatron.git"
python tests/test_smoke.py          # full-game smoke tests
uvicorn server.main:app --reload
```

## Deploy
Deployment is orchestrated from the repo root, not here — both the backend and
frontend come up together:
```bash
docker compose up -d --build                          # LAN
docker compose -f docker-compose.homelab.yml up -d    # Traefik/Tailscale
```
This server has no auth beyond room codes; keep it on a trusted network.

## Known follow-ups
- Discard on a 7 removes a random half of the hand (the engine's only DISCARD;
  it has no per-card choice). Player-chosen discards would need to be done as a
  server-level resource mutation outside the engine.
- Domestic trade UI+protocol complete (offer/accept/reject/confirm/cancel,
  E2E verified). Offers go to all players (no per-player targeting yet).
- Longest-road tie-after-break edge case: add unit test.
- 5-6p: needs new MapTemplate + special building phase + >4 Colors in engine.
