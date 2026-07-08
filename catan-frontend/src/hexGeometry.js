/**
 * hexGeometry.js — catanatron cube coordinates -> SVG pixel space.
 *
 * catanatron uses pointy-top hexes: tile neighbors lie E/W/NE/NW/SE/SW and
 * vertices (nodes) sit at N/NE/SE/S/SW/NW. Serialized tiles carry
 * { coordinate: [x,y,z], nodes: {NORTH: id, ...} } so we compute every
 * node's pixel position from its owning tiles — no separate node table needed.
 */

export const HEX_SIZE = 60; // center -> vertex, px

/** cube (x,y,z) -> axial (q=x, r=z) -> pixel, pointy-top orientation */
export function tileCenter([x, , z]) {
  return {
    x: HEX_SIZE * Math.sqrt(3) * (x + z / 2),
    y: HEX_SIZE * 1.5 * z,
  };
}

/** Vertex angles for pointy-top hexes, by catanatron NodeRef name. */
const NODE_ANGLE = {
  NORTH: -90,
  NORTHEAST: -30,
  SOUTHEAST: 30,
  SOUTH: 90,
  SOUTHWEST: 150,
  NORTHWEST: 210,
};

export function nodePosition(center, nodeRef) {
  const a = (NODE_ANGLE[nodeRef] * Math.PI) / 180;
  return {
    x: center.x + HEX_SIZE * Math.cos(a),
    y: center.y + HEX_SIZE * Math.sin(a),
  };
}

/** SVG points attr for one hex outline. */
export function hexPoints(center) {
  return Object.keys(NODE_ANGLE)
    .map((ref) => {
      const p = nodePosition(center, ref);
      return `${p.x},${p.y}`;
    })
    .join(" ");
}

/**
 * Build lookup tables from the serialized board:
 *   nodePx:  nodeId -> {x, y}
 *   bounds:  viewBox that fits all tiles with padding
 */
export function computeLayout(tiles) {
  const nodePx = {};
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

  for (const tile of tiles) {
    const c = tileCenter(tile.coordinate);
    for (const [ref, nodeId] of Object.entries(tile.nodes)) {
      nodePx[nodeId] = nodePosition(c, ref);
    }
    minX = Math.min(minX, c.x); maxX = Math.max(maxX, c.x);
    minY = Math.min(minY, c.y); maxY = Math.max(maxY, c.y);
  }
  const pad = HEX_SIZE * 2.2; // room for the sea + port boats
  return {
    nodePx,
    viewBox: `${minX - pad} ${minY - pad} ${maxX - minX + 2 * pad} ${maxY - minY + 2 * pad}`,
  };
}

/** Number-token pips: probability out of 36 for 2d6. */
export function pipCount(n) {
  return n == null ? 0 : 6 - Math.abs(7 - n);
}
