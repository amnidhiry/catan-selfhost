/**
 * TradePanel.jsx — bank & port (maritime) trades only.
 *
 * Domestic player-to-player trades now live in the chat feed (see ChatPanel):
 * they're non-blocking, so play never waits on a table-wide decision. Bank
 * trades stay here because they're a normal turn action: the server lists valid
 * MARITIME_TRADE actions with the correct port rate (4:1 / 3:1 / 2:1), so we
 * render them directly with zero client-side rate logic.
 */
import React, { useMemo } from "react";

const RESOURCES = ["WOOD", "BRICK", "SHEEP", "WHEAT", "ORE"];
const ICON = { WOOD: "🪵", BRICK: "🧱", SHEEP: "🐑", WHEAT: "🌾", ORE: "🪨" };

function deckToText(deck10) {
  const part = (slice) =>
    slice
      .map((n, i) => (n > 0 ? `${n}${ICON[RESOURCES[i]]}` : null))
      .filter(Boolean)
      .join(" ") || "nothing";
  return { gives: part(deck10.slice(0, 5)), wants: part(deck10.slice(5)) };
}

/** Normalize a MARITIME_TRADE value to a 10-slot count deck for display. */
function freqdeckOf(value) {
  if (value.length === 10 && value.every((v) => typeof v === "number")) return value;
  const deck = Array(10).fill(0);
  value.forEach((r, idx) => {
    if (r == null) return;
    const half = idx < value.length - 1 ? 0 : 5; // last slot = requested card
    deck[half + RESOURCES.indexOf(r)] += 1;
  });
  return deck;
}

export default function TradePanel({ state, client }) {
  const actions = state.playable_actions ?? [];
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
          const t = deckToText(freqdeckOf(a.value));
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
