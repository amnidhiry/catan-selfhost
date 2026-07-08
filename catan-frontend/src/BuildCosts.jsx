/**
 * BuildCosts.jsx — collapsible "Building costs" reference.
 *
 * Pure reference UI: a vertical tab fixed to the right edge of the board that
 * expands into a parchment panel. No game state, no client — always toggleable
 * regardless of whose turn it is. Uses the same resource emoji as the hand.
 */
import React, { useState } from "react";

const ICON = { WOOD: "🪵", BRICK: "🧱", SHEEP: "🐑", WHEAT: "🌾", ORE: "🪨" };

// [label, victory points, [resource, count]...]
const COSTS = [
  ["Road", "0", { WOOD: 1, BRICK: 1 }],
  ["Settlement", "1", { WOOD: 1, BRICK: 1, WHEAT: 1, SHEEP: 1 }],
  ["City", "2", { WHEAT: 2, ORE: 3 }],
  ["Development card", "?", { SHEEP: 1, WHEAT: 1, ORE: 1 }],
];

function CostIcons({ cost }) {
  return (
    <span className="cost-icons">
      {Object.entries(cost).flatMap(([res, n]) =>
        Array.from({ length: n }, (_, i) => (
          <span key={`${res}-${i}`} className="cost-icon" title={res}>{ICON[res]}</span>
        ))
      )}
    </span>
  );
}

export default function BuildCosts() {
  const [open, setOpen] = useState(false);

  if (!open) {
    return (
      <button className="costs-tab" onClick={() => setOpen(true)} aria-label="Show building costs">
        Build costs
      </button>
    );
  }

  return (
    <div className="costs-panel" role="dialog" aria-label="Building costs">
      <div className="costs-head">
        <b>Building costs</b>
        <button className="costs-close" onClick={() => setOpen(false)} aria-label="Close">×</button>
      </div>
      <table className="costs-table">
        <tbody>
          {COSTS.map(([label, vp, cost]) => (
            <tr key={label}>
              <td className="cost-name">{label}</td>
              <td className="cost-vp" title="victory points">{vp} VP</td>
              <td><CostIcons cost={cost} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
