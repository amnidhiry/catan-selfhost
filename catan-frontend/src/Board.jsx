/**
 * Board.jsx — flat top-down SVG island, BGA-style.
 *
 * Interactivity rule: clickable spots come ONLY from state.playable_actions
 * (server-validated). The board never guesses legality client-side.
 */
import React, { useMemo } from "react";
import {
  computeLayout,
  tileCenter,
  hexPoints,
  nodePosition,
  pipCount,
  HEX_SIZE,
} from "./hexGeometry";

const TERRAIN = {
  WOOD: "var(--forest)",
  BRICK: "var(--hills)",
  SHEEP: "var(--pasture)",
  WHEAT: "var(--fields)",
  ORE: "var(--mountains)",
  null: "var(--desert)",
};

/**
 * Drop-in terrain art: put a PNG at public/assets/tiles/<filename> and it
 * appears automatically, no code changes. Until then, SVG <image> simply
 * renders nothing on a 404 (unlike <img>, no broken-icon glyph), so the flat
 * TERRAIN color underneath shows through untouched. See
 * public/assets/tiles/README.md for exact filenames and sourcing links.
 */
const TERRAIN_TEXTURE = {
  WOOD: "/assets/tiles/forest.png",
  BRICK: "/assets/tiles/hills.png",
  SHEEP: "/assets/tiles/pasture.png",
  WHEAT: "/assets/tiles/fields.png",
  ORE: "/assets/tiles/mountains.png",
  null: "/assets/tiles/desert.png",
};
const PLAYER = {
  RED: "#c0392b",
  BLUE: "#2c5f8a",
  ORANGE: "#d68227",
  WHITE: "#efe9dc",
};

const RES_ICON = { WOOD: "🪵", BRICK: "🧱", SHEEP: "🐑", WHEAT: "🌾", ORE: "🪨" };

// Standard die pip layout on a 3x3 grid (offsets in [-1,0,1]).
const PIPS = {
  1: [[0, 0]],
  2: [[-1, -1], [1, 1]],
  3: [[-1, -1], [0, 0], [1, 1]],
  4: [[-1, -1], [1, -1], [-1, 1], [1, 1]],
  5: [[-1, -1], [1, -1], [0, 0], [-1, 1], [1, 1]],
  6: [[-1, -1], [1, -1], [-1, 0], [1, 0], [-1, 1], [1, 1]],
};

function Die({ x, y, value, size }) {
  const off = size * 0.26;
  return (
    <g transform={`translate(${x},${y})`}>
      <rect x={-size / 2} y={-size / 2} width={size} height={size} rx={size * 0.18}
            fill="var(--parchment)" stroke="var(--ink)" strokeWidth={size * 0.05} />
      {(PIPS[value] ?? []).map(([px, py], i) => (
        <circle key={i} cx={px * off} cy={py * off} r={size * 0.1} fill="var(--ink)" />
      ))}
    </g>
  );
}

function NumberToken({ n, hot }) {
  if (n == null) return null;
  const pips = pipCount(n);
  return (
    <g>
      <circle r={17} fill="var(--parchment)" stroke="var(--ink-soft)" strokeWidth={1.5} />
      <text y={2} textAnchor="middle" fontSize={hot ? 17 : 14} fontWeight={700}
            fill={hot ? "var(--hot-number)" : "var(--ink)"}>{n}</text>
      <g fill={hot ? "var(--hot-number)" : "var(--ink)"}>
        {Array.from({ length: pips }, (_, i) => (
          <circle key={i} cx={(i - (pips - 1) / 2) * 5} cy={10} r={1.6} />
        ))}
      </g>
    </g>
  );
}

function PortBoat({ nodes, resource, nodePx, islandCenter }) {
  // Sit the boat just seaward of the midpoint of its two landing nodes.
  const [a, b] = nodes.map((id) => nodePx[id]);
  if (!a || !b) return null;
  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  const away = Math.atan2(mid.y - islandCenter.y, mid.x - islandCenter.x);
  const x = mid.x + Math.cos(away) * HEX_SIZE * 0.85;
  const y = mid.y + Math.sin(away) * HEX_SIZE * 0.85;
  return (
    <g transform={`translate(${x},${y})`}>
      <line x1={a.x - x} y1={a.y - y} x2={0} y2={0} stroke="var(--rope)" strokeDasharray="3 3" />
      <line x1={b.x - x} y1={b.y - y} x2={0} y2={0} stroke="var(--rope)" strokeDasharray="3 3" />
      <path d="M -14 2 Q 0 12 14 2 L 10 -2 L -10 -2 Z" fill="var(--boat)" stroke="var(--ink-soft)" />
      <text y={-6} textAnchor="middle" fontSize={resource ? 11 : 9} fontWeight={700} fill="var(--ink)">
        {resource ? `2:1 ${RES_ICON[resource] ?? resource[0]}` : "3:1"}
      </text>
    </g>
  );
}

export default function Board({ state, client, onChooseVictim }) {
  const { board, playable_actions } = state;
  const layout = useMemo(() => computeLayout(board.tiles), [board.tiles]);
  const { nodePx, viewBox } = layout;

  const islandCenter = useMemo(() => {
    const cs = board.tiles.map((t) => tileCenter(t.coordinate));
    return {
      x: cs.reduce((s, c) => s + c.x, 0) / cs.length,
      y: cs.reduce((s, c) => s + c.y, 0) / cs.length,
    };
  }, [board.tiles]);

  // --- derive clickable targets from server-validated actions -------------
  const targets = useMemo(() => {
    const t = { settlementNodes: new Set(), cityNodes: new Set(), roadEdges: [], robberHexes: new Map() };
    for (const a of playable_actions ?? []) {
      if (a.type === "BUILD_SETTLEMENT") t.settlementNodes.add(a.value);
      if (a.type === "BUILD_CITY") t.cityNodes.add(a.value);
      if (a.type === "BUILD_ROAD") t.roadEdges.push(a.value);
      if (a.type === "MOVE_ROBBER") {
        // One action per (hex, victim) pair — collect victims per hex so a
        // click on a multi-victim hex can prompt instead of guessing.
        const key = JSON.stringify(a.value[0]);
        if (!t.robberHexes.has(key)) t.robberHexes.set(key, { coordinate: a.value[0], victims: [] });
        if (a.value[1] != null) t.robberHexes.get(key).victims.push(a.value[1]);
      }
    }
    return t;
  }, [playable_actions]);

  const edgeKey = (e) => [...e].sort((x, y) => x - y).join("-");
  const builtRoads = new Map(board.roads.map((r) => [edgeKey(r.edge), r.color]));

  return (
    <svg className="board" viewBox={viewBox}>
      {/* sea */}
      <rect x={-9999} y={-9999} width={99999} height={99999} fill="var(--sea)" />

      {/* island: sand halo under all tiles, then terrain */}
      {board.tiles.map((t) => {
        const c = tileCenter(t.coordinate);
        return <polygon key={`sand-${t.id}`} points={hexPoints(c)} fill="var(--sand)"
                        stroke="var(--sand)" strokeWidth={HEX_SIZE * 0.45} strokeLinejoin="round" />;
      })}
      {board.tiles.map((t) => {
        const c = tileCenter(t.coordinate);
        const isRobber = JSON.stringify(t.coordinate) === JSON.stringify(board.robber);
        const robberEntry = targets.robberHexes.get(JSON.stringify(t.coordinate));
        const robberTarget = robberEntry != null;
        const robberClick = !robberTarget ? undefined : () => {
          const { coordinate, victims } = robberEntry;
          if (victims.length > 1) onChooseVictim(coordinate, victims);
          else client.moveRobber(coordinate, victims[0] ?? null);
        };
        const clipId = `hex-clip-${t.id}`;
        return (
          <g key={t.id}
             className={robberTarget ? "clickable" : undefined}
             onClick={robberClick}>
            {/* Flat color first — this is what shows if no PNG has been dropped in yet. */}
            <polygon points={hexPoints(c)} fill={TERRAIN[t.resource]}
                     stroke="var(--sand)" strokeWidth={4} strokeLinejoin="round" />
            {/* Optional texture layer: renders nothing (no broken-image glyph)
                until a matching file exists in public/assets/tiles/. */}
            <clipPath id={clipId}>
              <polygon points={hexPoints(c)} />
            </clipPath>
            <image
              href={TERRAIN_TEXTURE[t.resource]}
              x={c.x - HEX_SIZE} y={c.y - HEX_SIZE}
              width={HEX_SIZE * 2} height={HEX_SIZE * 2}
              preserveAspectRatio="xMidYMid slice"
              clipPath={`url(#${clipId})`}
              onError={(e) => e.currentTarget.remove()}
            />
            <g transform={`translate(${c.x},${c.y})`}>
              {/* Lift the number token clear of the robber pawn when present,
                  so both stay readable. */}
              <g transform={isRobber ? "translate(0,-20)" : undefined}>
                <NumberToken n={t.number} hot={t.number === 6 || t.number === 8} />
              </g>
              {isRobber && (
                <g>
                  <ellipse cx={0} cy={15} rx={11} ry={3.5} fill="rgba(0,0,0,0.28)" />
                  {/* Pawn centred on the tile: head at y≈-13, base at y≈14. */}
                  <path d="M 0 -13 a 5.5 5.5 0 1 1 0.1 0 M -8 -1 Q 0 -9 8 -1 L 10 14 L -10 14 Z"
                        fill="var(--robber)" stroke="var(--ink)" strokeWidth={1.5} strokeLinejoin="round" />
                </g>
              )}
              {robberTarget && <circle r={26} className="pulse" fill="none" stroke="var(--hint)" strokeWidth={3} />}
            </g>
          </g>
        );
      })}

      {/* ports */}
      {board.ports.map((p) => (
        <PortBoat key={p.id} nodes={p.nodes} resource={p.resource}
                  nodePx={nodePx} islandCenter={islandCenter} />
      ))}

      {/* roads: built, then buildable hints */}
      {board.roads.map((r) => {
        const [a, b] = r.edge.map((id) => nodePx[id]);
        return <line key={edgeKey(r.edge)} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                     stroke={PLAYER[r.color]} strokeWidth={9} strokeLinecap="round" />;
      })}
      {targets.roadEdges.map((e) => {
        if (builtRoads.has(edgeKey(e))) return null;
        const [a, b] = e.map((id) => nodePx[id]);
        return <line key={`hint-${edgeKey(e)}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                     className="clickable pulse" stroke="var(--hint)" strokeWidth={9}
                     strokeLinecap="round" opacity={0.55}
                     onClick={() => client.placeRoad(e)} />;
      })}

      {/* buildings + buildable node hints */}
      {board.buildings.map((b) => {
        const p = nodePx[b.node_id];
        return b.type === "SETTLEMENT" ? (
          <path key={b.node_id} transform={`translate(${p.x},${p.y})`}
                d="M -9 8 L -9 -3 L 0 -11 L 9 -3 L 9 8 Z"
                fill={PLAYER[b.color]} stroke="var(--ink)" strokeWidth={1.5} />
        ) : (
          <path key={b.node_id} transform={`translate(${p.x},${p.y})`}
                d="M -11 9 L -11 -2 L -4 -8 L -4 -13 L 3 -13 L 3 -4 L 11 -4 L 11 9 Z"
                fill={PLAYER[b.color]} stroke="var(--ink)" strokeWidth={1.5} />
        );
      })}
      {[...targets.settlementNodes].map((id) => {
        const p = nodePx[id];
        return <circle key={`sn-${id}`} cx={p.x} cy={p.y} r={11} className="clickable pulse"
                       fill="var(--hint)" opacity={0.6}
                       onClick={() => client.placeSettlement(id)} />;
      })}
      {[...targets.cityNodes].map((id) => {
        const p = nodePx[id];
        return <circle key={`cn-${id}`} cx={p.x} cy={p.y} r={13} className="clickable pulse"
                       fill="none" stroke="var(--hint)" strokeWidth={4}
                       onClick={() => client.placeCity(id)} />;
      })}

      {/* Dice readout, bottom-right of the board. Remounts on each new roll
          (key changes) so the pop animation re-fires. */}
      {state.last_roll && (() => {
        const [vx, vy, vw, vh] = viewBox.split(" ").map(Number);
        const S = 46, gap = 12, pad = 30;
        const rightX = vx + vw - pad - S / 2;
        const y = vy + vh - pad - S / 2;
        const [d1, d2] = state.last_roll;
        return (
          <g key={`roll-${d1}-${d2}`} className="dice-readout">
            <Die x={rightX - S - gap} y={y} value={d1} size={S} />
            <Die x={rightX} y={y} value={d2} size={S} />
          </g>
        );
      })()}
    </svg>
  );
}
