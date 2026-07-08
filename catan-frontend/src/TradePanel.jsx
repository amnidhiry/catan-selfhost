/**
 * TradePanel.jsx — domestic + bank trading UI.
 *
 * Follows the engine's sequential trade state machine (verified by trace):
 *   1. Turn owner builds an offer (OFFER_TRADE, validated server-side).
 *   2. current_player rotates through opponents with prompt DECIDE_TRADE;
 *      each sees Accept (only if affordable — the server omits it otherwise)
 *      and Reject. Everyone else just watches the standing offer.
 *   3. If someone accepted, the offerer gets DECIDE_ACCEPTEES: Confirm with a
 *      chosen acceptee, or Cancel. (JSettlers2 pattern: offerer always keeps
 *      final say — an accept is a commitment to trade, not the trade itself.)
 *
 * Bank trades are listed directly from server-validated MARITIME_TRADE
 * actions rather than free-built, so port rates (4:1/3:1/2:1) are always
 * correct with zero client-side rate logic.
 */
import React, { useMemo, useState } from "react";

const RESOURCES = ["WOOD", "BRICK", "SHEEP", "WHEAT", "ORE"];
const ICON = { WOOD: "🪵", BRICK: "🧱", SHEEP: "🐑", WHEAT: "🌾", ORE: "🪨" };

function deckToText(deck10, from) {
  // deck10: [give x5, get x5] from the offerer's perspective
  const part = (slice) =>
    slice
      .map((n, i) => (n > 0 ? `${n}${ICON[RESOURCES[i]]}` : null))
      .filter(Boolean)
      .join(" ") || "nothing";
  return { gives: part(deck10.slice(0, 5)), wants: part(deck10.slice(5)) };
}

function Stepper({ label, value, max, onChange }) {
  return (
    <div className="stepper">
      <span>{ICON[label]}</span>
      <button aria-label={`less ${label}`} disabled={value <= 0}
              onClick={() => onChange(value - 1)}>−</button>
      <b>{value}</b>
      <button aria-label={`more ${label}`} disabled={value >= max}
              onClick={() => onChange(value + 1)}>+</button>
    </div>
  );
}

function OfferBuilder({ hand, client, onClose }) {
  const [give, setGive] = useState({});
  const [get, setGet] = useState({});
  const giveTotal = Object.values(give).reduce((a, b) => a + b, 0);
  const getTotal = Object.values(get).reduce((a, b) => a + b, 0);
  // Official rule: no gifting, and no like-for-like — mirror the server's
  // is_valid_trade check so the button disables instead of erroring.
  const overlap = RESOURCES.some((r) => (give[r] ?? 0) > 0 && (get[r] ?? 0) > 0);
  const valid = giveTotal > 0 && getTotal > 0 && !overlap;

  return (
    <div className="offer-builder">
      <div className="offer-cols">
        <fieldset>
          <legend>You give</legend>
          {RESOURCES.map((r) => (
            <Stepper key={r} label={r} value={give[r] ?? 0}
                     max={hand.resources[r] ?? 0}
                     onChange={(v) => setGive({ ...give, [r]: v })} />
          ))}
        </fieldset>
        <fieldset>
          <legend>You want</legend>
          {RESOURCES.map((r) => (
            <Stepper key={r} label={r} value={get[r] ?? 0} max={19}
                     onChange={(v) => setGet({ ...get, [r]: v })} />
          ))}
        </fieldset>
      </div>
      {overlap && <p className="trade-note">Can't offer and ask for the same resource.</p>}
      <div className="offer-actions">
        <button className="primary" disabled={!valid}
                onClick={() => { client.makeOffer(give, get); onClose(); }}>
          Propose to the table
        </button>
        <button onClick={onClose}>Never mind</button>
      </div>
    </div>
  );
}

function BankTrades({ actions, client }) {
  const trades = useMemo(
    () => actions.filter((a) => a.type === "MARITIME_TRADE"),
    [actions]
  );
  if (!trades.length) return null;
  return (
    <details className="bank-trades">
      <summary>Bank &amp; ports ({trades.length})</summary>
      <div className="bank-list">
        {trades.map((a, i) => {
          // MARITIME value: give-listdeck then get; render compactly
          const t = deckToText(freqdeckOf(a.value), null);
          return (
            <button key={i} onClick={() => client._send("bank_trade", { freqdeck: a.value })}>
              {t.gives} → {t.wants}
            </button>
          );
        })}
      </div>
    </details>
  );
}

/** MARITIME_TRADE values arrive as the engine emitted them; normalize to a
 *  10-slot count deck for display regardless of tuple flavor. */
function freqdeckOf(value) {
  if (value.length === 10 && value.every((v) => typeof v === "number")) return value;
  // listdeck flavor: e.g. ["WOOD","WOOD","WOOD","WOOD",null,...,"ORE"] — count them
  const deck = Array(10).fill(0);
  value.forEach((r, idx) => {
    if (r == null) return;
    const half = idx < value.length - 1 ? 0 : 5; // last slot = requested card
    deck[half + RESOURCES.indexOf(r)] += 1;
  });
  return deck;
}

export default function TradePanel({ state, client, names }) {
  const [building, setBuilding] = useState(false);
  const actions = state.playable_actions ?? [];
  const types = new Set(actions.map((a) => a.type));
  const isMyTurn = state.turn_player === state.your_color;
  const iAmDeciding = state.current_player === state.your_color;
  const nameOf = (c) => names?.[c]?.name ?? c;

  // --- 3. offerer resolves acceptees -------------------------------------
  if (state.current_prompt === "DECIDE_ACCEPTEES" && iAmDeciding) {
    const confirms = actions.filter((a) => a.type === "CONFIRM_TRADE");
    return (
      <div className="trade-panel urgent">
        <b>Your offer was accepted.</b>
        {confirms.map((a, i) => (
          <button key={i} className="primary"
                  onClick={() => client.confirmOffer(a.value)}>
            Trade with {nameOf(a.value[a.value.length - 1])}
          </button>
        ))}
        <button onClick={() => client.cancelOffer()}>Cancel the offer</button>
      </div>
    );
  }

  // --- 2. an offer is on the table ----------------------------------------
  if (state.current_trade) {
    const t = deckToText(state.current_trade);
    const canAccept = types.has("ACCEPT_TRADE");
    const canReject = types.has("REJECT_TRADE");
    return (
      <div className={`trade-panel ${iAmDeciding ? "urgent" : ""}`}>
        <b>{nameOf(state.turn_player)} offers:</b>
        <span className="trade-line">{t.gives} <em>for</em> {t.wants}</span>
        {iAmDeciding && canReject ? (
          <div className="offer-actions">
            {canAccept ? (
              <button className="primary"
                      onClick={() => client.acceptOffer(actions.find(a => a.type === "ACCEPT_TRADE").value)}>
                Accept
              </button>
            ) : (
              <span className="trade-note">You can't afford this trade.</span>
            )}
            <button onClick={() => client.rejectOffer(actions.find(a => a.type === "REJECT_TRADE").value)}>
              Decline
            </button>
          </div>
        ) : (
          <span className="trade-note">
            waiting for {nameOf(state.current_player)}…
          </span>
        )}
      </div>
    );
  }

  // --- 1. my turn: open the builder / bank list ---------------------------
  if (!isMyTurn || state.current_prompt !== "PLAY_TURN") return null;
  return (
    <div className="trade-panel">
      {building ? (
        <OfferBuilder hand={state.your_hand} client={client}
                      onClose={() => setBuilding(false)} />
      ) : (
        <button onClick={() => setBuilding(true)}
                disabled={!types.has("END_TURN") /* i.e. haven't rolled yet */}>
          Offer a trade
        </button>
      )}
      <BankTrades actions={actions} client={client} />
    </div>
  );
}
