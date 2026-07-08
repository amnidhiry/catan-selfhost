/**
 * ChatPanel.jsx — collapsible per-session chat + non-blocking trades.
 *
 * A right-edge drawer. Beyond plain messages, players propose trades here: an
 * offer renders as a module anyone can Accept (first accept wins), or Ignore
 * (dismissed locally — the offer stays live for others). No one is blocked, so
 * play continues while offers sit on the table. Accepting triggers a server-side
 * atomic swap; the board/hands update on the next state broadcast.
 */
import React, { useEffect, useRef, useState } from "react";

const RESOURCES = ["WOOD", "BRICK", "SHEEP", "WHEAT", "ORE"];
const ICON = { WOOD: "🪵", BRICK: "🧱", SHEEP: "🐑", WHEAT: "🌾", ORE: "🪨" };

const deckText = (deck) =>
  RESOURCES.filter((r) => deck[r]).map((r) => `${deck[r]}${ICON[r]}`).join(" ") || "—";

function Stepper({ res, value, max, onChange }) {
  return (
    <div className="stepper">
      <span>{ICON[res]}</span>
      <button aria-label={`less ${res}`} disabled={value <= 0} onClick={() => onChange(value - 1)}>−</button>
      <b>{value}</b>
      <button aria-label={`more ${res}`} disabled={value >= max} onClick={() => onChange(value + 1)}>+</button>
    </div>
  );
}

function OfferBuilder({ hand, onPropose, onClose }) {
  const [give, setGive] = useState({});
  const [get, setGet] = useState({});
  const total = (o) => Object.values(o).reduce((a, b) => a + b, 0);
  const overlap = RESOURCES.some((r) => (give[r] ?? 0) > 0 && (get[r] ?? 0) > 0);
  const valid = total(give) > 0 && total(get) > 0 && !overlap;
  return (
    <div className="offer-builder">
      <div className="offer-cols">
        <fieldset>
          <legend>You give</legend>
          {RESOURCES.map((r) => (
            <Stepper key={r} res={r} value={give[r] ?? 0} max={hand.resources[r] ?? 0}
                     onChange={(v) => setGive({ ...give, [r]: v })} />
          ))}
        </fieldset>
        <fieldset>
          <legend>You want</legend>
          {RESOURCES.map((r) => (
            <Stepper key={r} res={r} value={get[r] ?? 0} max={19}
                     onChange={(v) => setGet({ ...get, [r]: v })} />
          ))}
        </fieldset>
      </div>
      {overlap && <p className="trade-note">Can't offer and ask for the same resource.</p>}
      <div className="offer-actions">
        <button className="primary" disabled={!valid} onClick={() => onPropose(give, get)}>
          Propose to the table
        </button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </div>
  );
}

function TradeModule({ entry, myColor, hand, client, onIgnore }) {
  const mine = entry.color === myColor;
  // The responder must provide what the proposer *wants* (entry.get).
  const canAfford = RESOURCES.every((r) => (hand.resources[r] ?? 0) >= (entry.get[r] ?? 0));
  return (
    <div className="chat-trade" style={{ "--seat": `var(--p-${entry.color.toLowerCase()})` }}>
      <div className="chat-trade-head">
        <span className="seat-dot" /><b>{entry.name}</b> offers a trade
      </div>
      <div className="chat-trade-body">
        <span>Gives <b>{deckText(entry.give)}</b></span>
        <span>Wants <b>{deckText(entry.get)}</b></span>
      </div>
      {entry.status === "open" ? (
        mine ? (
          <button onClick={() => client.cancelTrade(entry.id)}>Cancel offer</button>
        ) : (
          <div className="offer-actions">
            <button className="primary" disabled={!canAfford} onClick={() => client.acceptTrade(entry.id)}>
              {canAfford ? "Accept" : "Can't afford"}
            </button>
            <button onClick={() => onIgnore(entry.id)}>Ignore</button>
          </div>
        )
      ) : (
        <span className="chat-trade-status">
          {entry.status === "done" ? `✓ traded with ${entry.accepted_name}` : "offer withdrawn"}
        </span>
      )}
    </div>
  );
}

export default function ChatPanel({ chat, client, state }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [showBuilder, setShowBuilder] = useState(false);
  const [ignored, setIgnored] = useState(() => new Set());
  const seenRef = useRef(0);
  const bodyRef = useRef(null);

  const entries = chat ?? [];
  const myColor = state.your_color;
  const inSetup =
    state.current_prompt === "BUILD_INITIAL_SETTLEMENT" ||
    state.current_prompt === "BUILD_INITIAL_ROAD";
  const unread = open ? 0 : Math.max(0, entries.length - seenRef.current);

  useEffect(() => { if (open) seenRef.current = entries.length; }, [open, entries.length]);
  useEffect(() => {
    if (open && bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [entries, open, showBuilder]);

  const send = () => {
    const t = draft.trim();
    if (t) { client.chatSend(t); setDraft(""); }
  };
  const ignore = (id) => setIgnored((s) => new Set(s).add(id));

  if (!open) {
    return (
      <button className="chat-tab" onClick={() => setOpen(true)} aria-label="Open chat">
        💬 Chat{unread > 0 && <span className="chat-badge">{unread}</span>}
      </button>
    );
  }

  return (
    <div className="chat-drawer">
      <div className="chat-head">
        <b>Table chat</b>
        <button className="chat-close" onClick={() => setOpen(false)} aria-label="Close chat">×</button>
      </div>

      <div className="chat-body" ref={bodyRef}>
        {entries.length === 0 && <p className="hint-text">Say hi — or propose a trade.</p>}
        {entries.map((e) =>
          e.kind === "trade" ? (
            ignored.has(e.id) && e.status === "open" ? null : (
              <TradeModule key={e.id} entry={e} myColor={myColor}
                           hand={state.your_hand} client={client} onIgnore={ignore} />
            )
          ) : (
            <div key={e.id} className="chat-msg"
                 style={{ "--seat": `var(--p-${e.color.toLowerCase()})` }}>
              <span className="seat-dot" /><b>{e.name}:</b> {e.text}
            </div>
          )
        )}
      </div>

      {showBuilder ? (
        <OfferBuilder hand={state.your_hand}
                      onPropose={(give, get) => { client.proposeTrade(give, get); setShowBuilder(false); }}
                      onClose={() => setShowBuilder(false)} />
      ) : (
        <button className="chat-propose" disabled={inSetup} onClick={() => setShowBuilder(true)}
                title={inSetup ? "Trading opens once setup is done" : undefined}>
          🤝 Propose a trade
        </button>
      )}

      <div className="chat-input">
        <input value={draft} maxLength={400} placeholder="Message…"
               onChange={(e) => setDraft(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && send()} />
        <button onClick={send} disabled={!draft.trim()}>Send</button>
      </div>
    </div>
  );
}
