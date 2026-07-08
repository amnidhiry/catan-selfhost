import React, { useEffect, useMemo, useState, useRef } from "react";
import { CatanClient, createRoom } from "./catanClient";
import Board from "./Board";
import TradePanel from "./TradePanel";
import ChatPanel from "./ChatPanel";
import BuildCosts from "./BuildCosts";

const RESOURCES = ["WOOD", "BRICK", "SHEEP", "WHEAT", "ORE"];
const RES_ICON = { WOOD: "🪵", BRICK: "🧱", SHEEP: "🐑", WHEAT: "🌾", ORE: "🪨" };
const DEV_ICON = {
  KNIGHT: "🐴",
  VICTORY_POINT: "🏆",
  ROAD_BUILDING: "🛤️",
  YEAR_OF_PLENTY: "🎁",
  MONOPOLY: "💰",
};

/* Signature element: room codes rendered as parchment token chips,
   the same visual language as the board's number tokens. */
function TokenCode({ code }) {
  return (
    <div className="token-code" aria-label={`Room code ${code}`}>
      {code.split("").map((ch, i) => (
        <span className="token-chip" key={i}>{ch}</span>
      ))}
    </div>
  );
}

function Lobby({ onEnter }) {
  const [name, setName] = useState(localStorage.getItem("catan_name") ?? "");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const go = async (roomCode, hostToken = null) => {
    localStorage.setItem("catan_name", name);
    onEnter({ code: roomCode, hostToken, name });
  };

  return (
    <main className="lobby">
      <h1>Island</h1>
      <p className="tagline">Trade. Build. Settle. On your own server.</p>
      <label>
        Your name
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={24} autoFocus />
      </label>
      <div className="lobby-actions">
        <button className="primary" disabled={!name || busy}
          onClick={async () => {
            setBusy(true); setErr(null);
            try {
              const r = await createRoom(window.location.origin);
              go(r.code, r.host_token);
            } catch (e) { setErr("Could not create a room. Is the server up?"); }
            setBusy(false);
          }}>
          Host a new island
        </button>
        <div className="join-row">
          <input placeholder="CODE" value={code} maxLength={4}
                 onChange={(e) => setCode(e.target.value.toUpperCase())} />
          <button disabled={!name || code.length !== 4} onClick={() => go(code)}>Join</button>
        </div>
      </div>
      {err && <p role="alert" className="error">{err}</p>}
    </main>
  );
}

function Seats({ room, isHost, onStart, onAddBot, onRemoveBot }) {
  const [mode, setMode] = useState("standard");
  const [bonusStart, setBonusStart] = useState(false);
  const [turnTimer, setTurnTimer] = useState(0);
  const [botKind, setBotKind] = useState("normal");
  const eligible = room.modes.filter(
    (m) => room.players.length >= m.min && room.players.length <= m.max
  );
  const seatsFull = room.players.length >= 4;
  return (
    <main className="seats">
      <TokenCode code={room.code} />
      <p className="hint-text">Friends join with this code.</p>
      <ul className="seat-list">
        {room.players.map((p) => (
          <li key={p.color} style={{ "--seat": `var(--p-${p.color.toLowerCase()})` }}>
            <span className="seat-dot" />
            {p.is_bot ? "🤖 " : ""}{p.name}
            {!p.connected && !p.is_bot && <span className="offline"> · reconnecting…</span>}
            {isHost && p.is_bot && (
              <button className="seat-remove" title="Remove bot"
                      onClick={() => onRemoveBot(p.color)}>✕</button>
            )}
          </li>
        ))}
      </ul>
      {isHost ? (
        <>
          <div className="bot-row">
            <select value={botKind} onChange={(e) => setBotKind(e.target.value)}
                    disabled={seatsFull}>
              <option value="normal">Normal bot</option>
              <option value="easy">Easy bot</option>
            </select>
            <button disabled={seatsFull} onClick={() => onAddBot(botKind)}>
              + Add bot
            </button>
          </div>
          <label className="house-rule" title="Official Catan pays out only the second settlement.">
            <input type="checkbox" checked={bonusStart}
                   onChange={(e) => setBonusStart(e.target.checked)} />
            Generous start — collect from both starting settlements
          </label>
          <label className="house-rule" title="After a player rolls, auto-end their turn if they don't within this time.">
            <span>Turn timer</span>
            <select value={turnTimer} onChange={(e) => setTurnTimer(Number(e.target.value))}>
              <option value={0}>Off</option>
              <option value={60}>60 seconds</option>
              <option value={90}>90 seconds</option>
              <option value={120}>120 seconds</option>
            </select>
          </label>
          <div className="start-row">
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              {room.modes.map((m) => (
                <option key={m.key} value={m.key}
                        disabled={!eligible.some((x) => x.key === m.key)}>
                  {m.label}
                </option>
              ))}
            </select>
            <button className="primary"
                    disabled={!eligible.some((x) => x.key === mode)}
                    onClick={() => onStart(mode, { bonusStart, turnTimer })}>
              Start game
            </button>
          </div>
        </>
      ) : (
        <p className="hint-text">Waiting for the host to start…</p>
      )}
    </main>
  );
}

function PlayerPanel({ players, current, waitingOn, names }) {
  return (
    <aside className="players">
      {players.map((p) => {
        const seat = names?.[p.color];
        return (
        <div key={p.color}
             className={`player-card ${p.color === current ? "active" : ""}`}
             style={{ "--seat": `var(--p-${p.color.toLowerCase()})` }}>
          <div className="player-head">
            <span className="seat-dot" />
            <strong>{seat?.is_bot ? "🤖 " : ""}{seat?.name ?? p.color}</strong>
            <span className="vp">{p.public_victory_points}★</span>
          </div>
          <div className="player-stats">
            <span title="resource cards">🂠 {p.resource_count}</span>
            <span title="development cards">🎴 {p.dev_card_count}</span>
            <span title="knights played">⚔ {p.played_knights}</span>
            {p.has_longest_road && <span title="Longest Road">🛤 +2</span>}
            {p.has_largest_army && <span title="Largest Army">🛡 +2</span>}
          </div>
          {waitingOn?.includes(p.color) && <div className="waiting">deciding…</div>}
        </div>
        );
      })}
    </aside>
  );
}

function Hand({ hand }) {
  return (
    <div className="hand">
      {RESOURCES.map((r) => (
        <span key={r} className="hand-card" data-empty={!hand.resources[r]}>
          {RES_ICON[r]} {hand.resources[r]}
        </span>
      ))}
      {Object.entries(hand.dev_cards)
        .filter(([, n]) => n > 0)
        .map(([d, n]) => (
          <span key={d} className="hand-card dev">
            {DEV_ICON[d] ?? "🎴"} {d.replaceAll("_", " ").toLowerCase()} ×{n}
          </span>
        ))}
    </div>
  );
}

function SetupBanner({ state, names }) {
  // Snake-draft guide (JSettlers2 START1A/1B/2A/2B states). Round inferred
  // from the current player's remaining settlement supply: 5 = placing their
  // first, 4 = placing their second (reverse order, grants starting resources).
  const prompt = state.current_prompt;
  if (prompt !== "BUILD_INITIAL_SETTLEMENT" && prompt !== "BUILD_INITIAL_ROAD")
    return null;
  const cur = state.players.find((p) => p.color === state.current_player);
  const piece = prompt === "BUILD_INITIAL_SETTLEMENT" ? "settlement" : "road";
  // Supply drops the moment a piece is placed, so the road step of round 1
  // already shows 4 settlements remaining: settlement -> 5 means round 1,
  // road -> 4 means round 1. (Verified against the engine's draft sequence.)
  const round =
    cur?.settlements_available === (piece === "settlement" ? 5 : 4) ? 1 : 2;
  const mine = state.current_player === state.your_color;
  const who = names?.[state.current_player]?.name ?? state.current_player;
  return (
    <div className={`setup-banner ${mine ? "urgent" : ""}`}>
      <b>Setting up the island — round {round} of 2</b>
      <span>
        {mine
          ? `Place your ${round === 1 ? "first" : "second"} ${piece} on a glowing spot.`
          : `${who} is placing their ${round === 1 ? "first" : "second"} ${piece}…`}
      </span>
      {round === 2 && (
        <span className="hint-text">
          Placement order reverses this round{mine && piece === "settlement"
            ? " — you'll collect starting resources from the hexes around this one, so choose well"
            : ""}.
        </span>
      )}
    </div>
  );
}

function DiscardPanel({ state, client }) {
  // Active only for the player currently over the hand limit after a 7.
  // The engine offers a single DISCARD action that removes a random half of
  // the hand (no per-card choice), so this is one confirm button.
  const mustDiscard = (state.playable_actions ?? []).some((a) => a.type === "DISCARD");
  if (!mustDiscard) return null;
  const n = state.discard_remaining;
  return (
    <div className="trade-panel urgent">
      <b>Robber! You must discard {n} card{n === 1 ? "" : "s"}.</b>
      <span className="trade-note">A random half of your hand is discarded.</span>
      <button className="primary" onClick={() => client.discard()}>
        Discard {n}
      </button>
    </div>
  );
}

function VictimPicker({ prompt, client, onClose }) {
  if (!prompt) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <b>Steal from whom?</b>
        <div className="offer-actions">
          {prompt.victims.map((v) => (
            <button key={v} className="primary"
                    style={{ "--seat": `var(--p-${v.toLowerCase()})` }}
                    onClick={() => { client.moveRobber(prompt.coordinate, v); onClose(); }}>
              <span className="seat-dot" /> {v}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* Gentle transient notifications of what you just received, stacked above the
   hand. Fed by diffing your_hand between server snapshots (App effect below). */
function Toasts({ toasts }) {
  if (!toasts.length) return null;
  return (
    <div className="toast-stack" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind === "vp" ? "toast-vp" : ""}`}>
          {t.kind === "gain" ? (
            <>
              <span className="toast-plus">+</span>
              {t.gains.map((g) => (
                <span key={g.r} className="toast-item">{g.n} {RES_ICON[g.r]}</span>
              ))}
              <span className="toast-label">received</span>
            </>
          ) : (
            <span>★ +{t.n} victory point{t.n === 1 ? "" : "s"}!</span>
          )}
        </div>
      ))}
    </div>
  );
}

function TurnClock({ deadline }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!deadline) return;
    const id = setInterval(() => setNow(Date.now() / 1000), 250);
    return () => clearInterval(id);
  }, [deadline]);
  if (!deadline) return null;
  const remaining = Math.max(0, Math.ceil(deadline - now));
  return (
    <div className={`turn-clock ${remaining <= 10 ? "urgent" : ""}`} title="Turn auto-ends at 0">
      ⏱ {remaining}s
    </div>
  );
}

function ActionBar({ state, client, names }) {
  const mine = useMemo(() => {
    const s = new Set((state.playable_actions ?? []).map((a) => a.type));
    return s;
  }, [state.playable_actions]);
  const myTurn = state.current_player === state.your_color;

  if (!myTurn) {
    const who = names?.[state.current_player]?.name ?? state.current_player;
    return <div className="action-bar dim">Waiting for {who}…</div>;
  }

  return (
    <div className="action-bar">
      {mine.has("ROLL") && <button className="primary" onClick={() => client.rollDice()}>Roll dice</button>}
      {mine.has("BUY_DEVELOPMENT_CARD") && <button onClick={() => client.buyDevCard()}>Buy dev card</button>}
      {mine.has("PLAY_KNIGHT_CARD") && <button onClick={() => client.playKnight()}>🐴 Play knight</button>}
      {mine.has("END_TURN") && <button onClick={() => client.endTurn()}>End turn</button>}
      {(mine.has("BUILD_SETTLEMENT") || mine.has("BUILD_ROAD") || mine.has("BUILD_CITY")) && (
        <span className="hint-text">Tap a glowing spot on the board to build.</span>
      )}
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState(null);   // {code, hostToken, name}
  const [room, setRoom] = useState(null);
  const [state, setState] = useState(null);
  const [conn, setConn] = useState("disconnected");
  const [victimPrompt, setVictimPrompt] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [chat, setChat] = useState([]);
  const clientRef = useRef(null);
  const prevHandRef = useRef(null);
  const toastIdRef = useRef(0);

  // Notify on gains: diff your_hand between snapshots (the server sends full
  // state, not events, so the delta is computed client-side).
  useEffect(() => {
    const hand = state?.your_hand;
    if (!hand) return;
    const prev = prevHandRef.current;
    const snapshot = {
      resources: { ...hand.resources },
      vp: hand.actual_victory_points ?? 0,
    };
    prevHandRef.current = snapshot;
    if (!prev) return; // first snapshot establishes a baseline silently

    const gains = RESOURCES
      .map((r) => ({ r, n: (hand.resources[r] ?? 0) - (prev.resources[r] ?? 0) }))
      .filter((g) => g.n > 0);
    const vpGain = snapshot.vp - prev.vp;

    const fresh = [];
    if (gains.length) fresh.push({ id: ++toastIdRef.current, kind: "gain", gains });
    if (vpGain > 0) fresh.push({ id: ++toastIdRef.current, kind: "vp", n: vpGain });
    if (!fresh.length) return;

    setToasts((t) => [...t, ...fresh]);
    fresh.forEach((m) =>
      setTimeout(() => setToasts((t) => t.filter((x) => x.id !== m.id)), 4200)
    );
  }, [state]);

  useEffect(() => {
    if (!session) return;
    prevHandRef.current = null; // fresh baseline per room; no spurious toasts
    const wsBase = window.location.origin.replace(/^http/, "ws");
    const client = new CatanClient(wsBase, session.code);
    clientRef.current = client;
    const offs = [
      client.on("room_state", setRoom),
      client.on("state", setState),
      client.on("chat", ({ entries }) => setChat(entries)),
      client.on("connection_status", ({ status }) => setConn(status)),
      client.on("error", (e) => console.warn("server:", e.reason)),
    ];
    client.connect(session.name);
    return () => { offs.forEach((f) => f()); client.close(); };
  }, [session]);

  // color -> {name, is_bot} from the lobby roster, for showing names in-game.
  const nameByColor = useMemo(
    () => Object.fromEntries((room?.players ?? []).map((p) => [p.color, p])),
    [room]
  );

  if (!session) return <Lobby onEnter={setSession} />;

  if (!state)
    return room ? (
      <Seats room={room} isHost={!!session.hostToken}
             onStart={(mode, options) => clientRef.current.startGame(session.hostToken, mode, options)}
             onAddBot={(kind) => clientRef.current.addBot(session.hostToken, kind)}
             onRemoveBot={(color) => clientRef.current.removeBot(session.hostToken, color)} />
    ) : (
      <main className="lobby"><p>Joining {session.code}…</p></main>
    );

  return (
    <div className="game">
      {conn !== "connected" && <div className="conn-banner">Reconnecting…</div>}
      {state.winner && (
        <div className="winner-banner">
          🏆 {nameByColor[state.winner]?.name ?? state.winner} wins the island!
        </div>
      )}
      <SetupBanner state={state} names={nameByColor} />
      <PlayerPanel players={state.players} current={state.current_player}
                   waitingOn={state.waiting_on} names={nameByColor} />
      <Board state={state} client={clientRef.current}
             onChooseVictim={(coordinate, victims) => setVictimPrompt({ coordinate, victims })} />
      <VictimPicker prompt={victimPrompt} client={clientRef.current}
                    onClose={() => setVictimPrompt(null)} />
      <BuildCosts />
      <ChatPanel chat={chat} client={clientRef.current} state={state} />
      <footer>
        <Toasts toasts={toasts} />
        <TurnClock deadline={state.turn_deadline} />
        <Hand hand={state.your_hand} />
        <DiscardPanel state={state} client={clientRef.current} />
        <TradePanel state={state} client={clientRef.current} names={nameByColor} />
        <ActionBar state={state} client={clientRef.current} names={nameByColor} />
      </footer>
    </div>
  );
}
