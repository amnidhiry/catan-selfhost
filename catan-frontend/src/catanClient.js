/**
 * catanClient.js — WebSocket client for the self-hosted Catan backend.
 *
 * Framework-agnostic (no React imports): the UI layer subscribes via .on()
 * and calls action methods. This module owns the wire protocol so the rest
 * of the frontend never touches raw JSON or reconnection logic.
 *
 * Contract: server/main.py + websocket_event_schema.md. If you change one,
 * change the other.
 */

const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 10_000;

export class CatanClient {
  /**
   * @param {string} baseUrl e.g. "wss://catan.yourdomain.internal"
   * @param {string} roomCode 4-letter code
   */
  constructor(baseUrl, roomCode) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.roomCode = roomCode.toUpperCase();
    this.ws = null;
    this.handlers = new Map(); // eventType -> Set<fn>
    this.lastSeq = 0;
    this.reconnectAttempt = 0;
    this.intentionallyClosed = false;

    // Rejoin token survives page refreshes; keyed per room so multiple
    // tabs/rooms don't clobber each other.
    this.tokenKey = `catan_rejoin_${this.roomCode}`;
    this.playerName = null;

    // Local echo of connection status for the UI
    this.status = "disconnected"; // disconnected | connecting | connected
  }

  // ---------------------------------------------------------------- events

  /** Subscribe. Returns an unsubscribe fn (handy for React useEffect). */
  on(type, fn) {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set());
    this.handlers.get(type).add(fn);
    return () => this.handlers.get(type)?.delete(fn);
  }

  _emit(type, data) {
    this.handlers.get(type)?.forEach((fn) => fn(data));
    this.handlers.get("*")?.forEach((fn) => fn({ type, data }));
  }

  _setStatus(s) {
    if (this.status !== s) {
      this.status = s;
      this._emit("connection_status", { status: s });
    }
  }

  // ------------------------------------------------------------ connection

  /**
   * Connect and join. On reconnect, the stored rejoin token restores the
   * same seat (server treats socket drop as disconnect, not leave).
   */
  connect(playerName) {
    this.playerName = playerName ?? this.playerName;
    this.intentionallyClosed = false;
    this._setStatus("connecting");

    this.ws = new WebSocket(`${this.baseUrl}/ws/${this.roomCode}`);

    this.ws.onopen = () => {
      this.reconnectAttempt = 0;
      this._send("join_room", {
        player_name: this.playerName,
        rejoin_token: localStorage.getItem(this.tokenKey) || undefined,
      });
    };

    this.ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      const { type, seq, data } = msg;

      if (type === "joined") {
        localStorage.setItem(this.tokenKey, data.rejoin_token);
        this._setStatus("connected");
      }

      // Gap detection: state messages carry the room's monotonic seq.
      // The server always sends a FULL snapshot, so a gap is self-healing —
      // we just note it for debugging rather than requesting replay.
      if (type === "state") {
        if (seq < this.lastSeq) return; // stale/out-of-order: drop
        this.lastSeq = seq;
      }

      this._emit(type, data);
    };

    this.ws.onclose = () => {
      this._setStatus("disconnected");
      if (!this.intentionallyClosed) this._scheduleReconnect();
    };

    this.ws.onerror = () => this.ws?.close();
  }

  _scheduleReconnect() {
    const delay = Math.min(
      RECONNECT_BASE_MS * 2 ** this.reconnectAttempt,
      RECONNECT_MAX_MS
    );
    this.reconnectAttempt += 1;
    setTimeout(() => {
      if (!this.intentionallyClosed) this.connect();
    }, delay);
  }

  close() {
    this.intentionallyClosed = true;
    this.ws?.close();
  }

  /** Leaving for real (not just closing the tab): forget the seat token. */
  leaveRoom() {
    localStorage.removeItem(this.tokenKey);
    this.close();
  }

  _send(type, data = {}) {
    if (this.ws?.readyState !== WebSocket.OPEN) {
      this._emit("error", { reason: "not_connected", attempted: type });
      return;
    }
    this.ws.send(JSON.stringify({ type, data }));
  }

  // --------------------------------------------------------------- actions
  // One method per client->server event in the schema. UI calls these and
  // then waits for the next `state` broadcast — no optimistic updates in v1.

  startGame(hostToken, mode = "standard", options = {}) {
    this._send("start_game", {
      host_token: hostToken,
      mode,
      bonus_start: !!options.bonusStart,
      turn_timer: Number(options.turnTimer) || 0,
      discard_mode: options.discardMode === "random" ? "random" : "choose",
    });
  }

  /** Host-only: add a bot seat. kind ∈ {"easy","normal"}. */
  addBot(hostToken, kind = "normal") {
    this._send("add_bot", { host_token: hostToken, kind });
  }
  /** Host-only: remove a bot seat by its color. */
  removeBot(hostToken, color) {
    this._send("remove_bot", { host_token: hostToken, color });
  }

  rollDice() { this._send("roll_dice"); }
  endTurn() { this._send("end_turn"); }
  buyDevCard() { this._send("buy_dev_card"); }

  placeSettlement(nodeId) { this._send("place_piece", { piece: "settlement", node_id: nodeId }); }
  placeCity(nodeId) { this._send("place_piece", { piece: "city", node_id: nodeId }); }
  placeRoad(edge) { this._send("place_piece", { piece: "road", edge }); }

  /** @param {[number,number,number]} coordinate cube coord @param {?string} victim color name */
  moveRobber(coordinate, victim = null) {
    this._send("move_robber", { coordinate, victim });
  }

  /** Discard when over the hand limit after a 7. The engine removes a random
   *  half of the hand in one action — there is no per-card choice. */
  discard() {
    this._send("discard", {});
  }

  playKnight() { this._send("play_dev_card", { card: "knight" }); }
  playRoadBuilding() { this._send("play_dev_card", { card: "road_building" }); }
  playMonopoly(resource) { this._send("play_dev_card", { card: "monopoly", resource }); }
  playYearOfPlenty(resources) { this._send("play_dev_card", { card: "year_of_plenty", resources }); }

  // ---- trading -----------------------------------------------------------
  // freqdeck convention (matches catanatron): 10-tuple
  // [give_wood, give_brick, give_sheep, give_wheat, give_ore,
  //  get_wood,  get_brick,  get_sheep,  get_wheat,  get_ore]

  /** Helper: build a freqdeck from {wood: 2, ...} objects. */
  static freqdeck(give = {}, get = {}) {
    const order = ["WOOD", "BRICK", "SHEEP", "WHEAT", "ORE"];
    return [
      ...order.map((r) => give[r] ?? give[r.toLowerCase()] ?? 0),
      ...order.map((r) => get[r] ?? get[r.toLowerCase()] ?? 0),
    ];
  }

  bankTrade(give, get) {
    this._send("bank_trade", { freqdeck: CatanClient.freqdeck(give, get) });
  }

  // ---- chat & non-blocking player trades --------------------------------
  // Domestic trades live in the chat feed instead of catanatron's blocking
  // OFFER/DECIDE flow: propose an offer, anyone may accept (first wins) or
  // ignore it, so play never stalls waiting on the table.
  // give/get are {RESOURCE: count} objects, e.g. {WOOD: 2, ORE: 1}.

  chatSend(text) { this._send("chat_send", { text }); }
  proposeTrade(give, get) { this._send("trade_propose", { give, get }); }
  acceptTrade(offerId) { this._send("trade_accept", { offer_id: offerId }); }
  cancelTrade(offerId) { this._send("trade_cancel", { offer_id: offerId }); }
}

/**
 * Room creation (plain HTTP, not WS).
 * @returns {Promise<{code: string, host_token: string}>}
 */
export async function createRoom(baseHttpUrl) {
  const res = await fetch(`${baseHttpUrl.replace(/\/$/, "")}/rooms`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`createRoom failed: ${res.status}`);
  return res.json();
}

/* ---------------------------------------------------------------- usage ---
import { CatanClient, createRoom } from "./catanClient";

// Host flow:
const { code, host_token } = await createRoom("https://catan.internal");
const client = new CatanClient("wss://catan.internal", code);
client.on("state", (s) => render(s));                 // full filtered snapshot
client.on("room_state", (r) => renderLobby(r));
client.on("connection_status", ({status}) => setBanner(status));
client.on("error", (e) => toast(e.reason));
client.connect("Abe");
client.startGame(host_token, "mini_2p");

// Guest flow: same, minus createRoom/startGame — just enter the code.
--------------------------------------------------------------------------- */
