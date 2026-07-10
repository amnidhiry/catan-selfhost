"""Correct 5-6 player board (task #9 / Path A).

Root problem: catanatron's road/adjacency/longest-road logic all reads one
module-level global, ``board.STATIC_GRAPH``, built once from the 54-node
standard board. Any board with different nodes gets wrong road wiring — which
is why the first XL board drew roads as diagonals through tiles.

Fix without forking:
1. Build the expansion board as the standard 19 hexes + one outer ring (a
   symmetric 4-ring hexagon, 37 land tiles) using GEOMETRY-CANONICAL node ids
   — every physical vertex keyed by its pixel position, so shared corners merge
   correctly at any size. Feed hand-built tiles to ``CatanMap.from_tiles`` so we
   bypass catanatron's order-dependent incremental node construction entirely.
2. SEED the vertex->id map with the base board's real ids, so the inner 19
   tiles keep ids 0-53 and only the outer ring/water get new ids 54+.
3. Replace ``board.STATIC_GRAPH`` / ``NUM_NODES`` with the superset graph at
   import. Because inner ids/edges are preserved, ``subgraph({0..53})`` is still
   exactly the base graph, so Standard and Duel play identically; the expansion
   board reads the whole graph. Import this module before any Game is created.
"""
import math
import random

import networkx as nx

import catanatron.models.board as _board_mod
from catanatron.models.map import (
    CatanMap, LandTile, Water, Port, NodeRef, EdgeRef, get_edge_nodes,
    BASE_MAP_TEMPLATE,
)
from catanatron.models.coordinate_system import UNIT_VECTORS, add
from catanatron.models.enums import WOOD, BRICK, SHEEP, WHEAT, ORE

HEX = 60.0
_ANGLE = {
    NodeRef.NORTH: -90, NodeRef.NORTHEAST: -30, NodeRef.SOUTHEAST: 30,
    NodeRef.SOUTH: 90, NodeRef.SOUTHWEST: 150, NodeRef.NORTHWEST: 210,
}


def _tile_center(c):
    x, _, z = c
    return (HEX * math.sqrt(3) * (x + z / 2), HEX * 1.5 * z)


def _vertex(coord, ref):
    cx, cy = _tile_center(coord)
    a = math.radians(_ANGLE[ref])
    return (round(cx + HEX * math.cos(a), 2), round(cy + HEX * math.sin(a), 2))


def _hex_dist(c):
    return (abs(c[0]) + abs(c[1]) + abs(c[2])) // 2


def _ring(r):
    return [
        (x, y, -x - y)
        for x in range(-r - 1, r + 2)
        for y in range(-r - 1, r + 2)
        if _hex_dist((x, y, -x - y)) == r
    ]


# --- seed vertex pixel -> node id from the base board's LAND tiles (ids 0-53) ---
_BASE = CatanMap.from_template(BASE_MAP_TEMPLATE)
_SEED_IDS = {}
_MAX_BASE_ID = -1
for _coord, _tile in _BASE.land_tiles.items():
    for _ref, _nid in _tile.nodes.items():
        _SEED_IDS[_vertex(_coord, _ref)] = _nid
        _MAX_BASE_ID = max(_MAX_BASE_ID, _nid)

# Land = base 19 (rings 0-2) + ring 3 => 37 symmetric tiles. Ports/water on ring 4.
_LAND = [c for r in (0, 1, 2, 3) for c in _ring(r)]


def _angle_of(c):
    return math.atan2(1.5 * c[2], math.sqrt(3) * (c[0] + c[2] / 2))


def _inward_dir(cell):
    for d, vec in UNIT_VECTORS.items():
        if _hex_dist(add(cell, vec)) <= 3:
            return d
    return None


# Fixed topology (structure is deterministic; only resources/numbers vary/game).
_TOPOLOGY = {c: "land" for c in _LAND}
_N_PORTS = 0
for _i, _cell in enumerate(sorted(_ring(4), key=_angle_of)):
    _d = _inward_dir(_cell)
    if _d is not None and _i % 2 == 0:
        _TOPOLOGY[_cell] = ("port", _d)
        _N_PORTS += 1
    else:
        _TOPOLOGY[_cell] = "water"

_N_LAND = len(_LAND)
_N_DESERT = _N_LAND - 35  # 2 deserts, 35 producing tiles
_TILE_RESOURCES = [WOOD] * 7 + [BRICK] * 7 + [SHEEP] * 7 + [WHEAT] * 7 + [ORE] * 7 + [None] * _N_DESERT
_NUMBERS = [2, 2, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 5, 6, 6, 6, 6,
            8, 8, 8, 8, 9, 9, 9, 9, 10, 10, 10, 10, 11, 11, 11, 12, 12]
_PORT_RESOURCES = [WOOD, BRICK, SHEEP, WHEAT, ORE] + [None] * (_N_PORTS - 5)


def _node_id_assigner():
    """Deterministic vertex-pixel -> node id, seeded with the base ids so the
    inner 19 tiles keep 0-53 (every call yields the same ids -> matches the
    patched STATIC_GRAPH)."""
    vid = dict(_SEED_IDS)
    nxt = [_MAX_BASE_ID + 1]

    def nid(coord, ref):
        p = _vertex(coord, ref)
        got = vid.get(p)
        if got is None:
            got = vid[p] = nxt[0]
            nxt[0] += 1
        return got

    return nid


def build_expansion_map(seed=None) -> CatanMap:
    """A fresh 5-6 board: fixed geometry, shuffled resources/numbers/ports."""
    rng = random.Random(seed)
    tres, nums, pres = list(_TILE_RESOURCES), list(_NUMBERS), list(_PORT_RESOURCES)
    rng.shuffle(tres)
    rng.shuffle(nums)
    rng.shuffle(pres)

    nid = _node_id_assigner()
    tiles, tid, pid, land_i, num_i = {}, 0, 0, 0, 0
    for coord, kind in _TOPOLOGY.items():
        nodes = {ref: nid(coord, ref) for ref in NodeRef}
        edges = {er: tuple(nodes[r] for r in get_edge_nodes(er)) for er in EdgeRef}
        if isinstance(kind, tuple):  # ("port", direction)
            tiles[coord] = Port(pid, pres[pid], kind[1], nodes, edges)
            pid += 1
        elif kind == "land":
            res = tres[land_i]
            land_i += 1
            number = None
            if res is not None:
                number = nums[num_i]
                num_i += 1
            tiles[coord] = LandTile(tid, res, number, nodes, edges)
            tid += 1
        else:  # water
            tiles[coord] = Water(nodes, edges)
    return CatanMap.from_tiles(tiles)


def _patch_static_graph():
    """Replace the global road graph with the expansion superset (structure is
    identical every build, so a single fixed graph serves every game)."""
    sample = build_expansion_map(seed=0)
    graph = nx.Graph()
    for tile in sample.tiles.values():
        graph.add_nodes_from(tile.nodes.values())
        graph.add_edges_from(tile.edges.values())
    _board_mod.STATIC_GRAPH = graph
    _board_mod.NUM_NODES = graph.number_of_nodes()
    _board_mod.get_edges.cache_clear()
    _board_mod.get_node_distances.cache_clear()


_patch_static_graph()
