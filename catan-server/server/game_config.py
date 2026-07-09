"""Game mode configurations, including the validated MINI_2P template.

Design provenance:
- MINI_2P_TEMPLATE: 7-hex board with 3 ports (2x generic 3:1, 1x wheat 2:1).
  Port coordinates/directions were empirically validated: all 6 port-accessible
  nodes land on real coastal intersections across 500 generated maps.
  Max settlement packing = 12 (vs 10 needed for two full player allotments).
- vps_to_win=8 for 2p compensates for the smaller board's lower total production.
"""
import math
from dataclasses import dataclass
from typing import Optional

from catanatron.models.map import (
    MapTemplate,
    CatanMap,
    LandTile,
    Water,
    Port,
    MINI_MAP_TEMPLATE,
    BASE_MAP_TEMPLATE,
)
from catanatron.models.coordinate_system import Direction, UNIT_VECTORS, add
from catanatron.models.enums import WOOD, BRICK, SHEEP, WHEAT, ORE


def _build_mini_2p_template() -> MapTemplate:
    topology = dict(MINI_MAP_TEMPLATE.topology)
    # Evenly spaced (120 degrees apart), each attaching to 2 valid coastal nodes.
    topology[(1, -2, 1)] = (Port, Direction.WEST)        # generic 3:1
    topology[(-2, 1, 1)] = (Port, Direction.EAST)        # generic 3:1
    topology[(1, 1, -2)] = (Port, Direction.SOUTHWEST)   # 2:1 WHEAT
    return MapTemplate(
        numbers=list(MINI_MAP_TEMPLATE.numbers),
        port_resources=[None, None, WHEAT],
        tile_resources=list(MINI_MAP_TEMPLATE.tile_resources),
        topology=topology,
    )


MINI_2P_TEMPLATE = _build_mini_2p_template()


def _hex_distance(c) -> int:
    return (abs(c[0]) + abs(c[1]) + abs(c[2])) // 2


def _ring(radius: int):
    return [
        (x, y, -x - y)
        for x in range(-radius - 1, radius + 2)
        for y in range(-radius - 1, radius + 2)
        if _hex_distance((x, y, -x - y)) == radius
    ]


def _build_expansion_template() -> MapTemplate:
    """Symmetric 4-ring hexagon (37 land tiles) for 5-6 players, with a ring of
    water + 12 ports around it. Bigger and more symmetric than the official 30-
    tile 5-6 board, which makes port placement systematic — every port sits on
    an outer-ring water cell pointing inward at its coastal land neighbour.
    Empirically validated: all 12 ports land on real coastal nodes and full 5-
    and 6-player games complete. Uses random number placement (the official
    spiral only walks the standard board shapes)."""
    land = [c for r in (0, 1, 2, 3) for c in _ring(r)]

    def angle(c):  # order the outer ring so ports/water alternate cleanly
        q, r = c[0], c[2]
        return math.atan2(1.5 * r, math.sqrt(3) * (q + r / 2))

    def inward_dir(cell):  # a direction from this water cell toward the land mass
        for d, vec in UNIT_VECTORS.items():
            if _hex_distance(add(cell, vec)) <= 3:
                return d
        return None

    topology = {c: LandTile for c in land}
    n_ports = 0
    for i, cell in enumerate(sorted(_ring(4), key=angle)):
        d = inward_dir(cell)
        if d is not None and i % 2 == 0:
            topology[cell] = (Port, d)
            n_ports += 1
        else:
            topology[cell] = Water

    n_desert = len(land) - 35
    tile_resources = (
        [WOOD] * 7 + [BRICK] * 7 + [SHEEP] * 7 + [WHEAT] * 7 + [ORE] * 7
        + [None] * n_desert
    )
    # 35 number tokens (one per producing tile); light on 2/12, no 7.
    numbers = [
        2, 2, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 5, 6, 6, 6, 6,
        8, 8, 8, 8, 9, 9, 9, 9, 10, 10, 10, 10, 11, 11, 11, 12, 12,
    ]
    port_resources = [WOOD, BRICK, SHEEP, WHEAT, ORE] + [None] * (n_ports - 5)
    return MapTemplate(
        numbers=numbers,
        port_resources=port_resources,
        tile_resources=tile_resources,
        topology=topology,
    )


EXPANSION_TEMPLATE = _build_expansion_template()


@dataclass(frozen=True)
class GameMode:
    key: str
    label: str
    min_players: int
    max_players: int
    vps_to_win: int
    map_template: MapTemplate
    # Custom boards can't use the official coast-following spiral (it only walks
    # the standard shapes), so they place numbers randomly.
    number_placement: str = "official_spiral"

    def build_map(self) -> CatanMap:
        return CatanMap.from_template(
            self.map_template, number_placement=self.number_placement
        )


GAME_MODES: dict[str, GameMode] = {
    "standard": GameMode(
        key="standard",
        label="Standard (3-4 players)",
        min_players=3,
        max_players=4,
        vps_to_win=10,
        map_template=BASE_MAP_TEMPLATE,
    ),
    "mini_2p": GameMode(
        key="mini_2p",
        label="Duel (2 players, small island)",
        min_players=2,
        max_players=2,
        vps_to_win=8,
        map_template=MINI_2P_TEMPLATE,
    ),
    "expansion": GameMode(
        key="expansion",
        label="Expansion (5-6 players, XL island)",
        min_players=5,
        max_players=6,
        vps_to_win=10,
        map_template=EXPANSION_TEMPLATE,
        number_placement="random",
    ),
    # Note: the official 5-6 "special building phase" is not modelled — the
    # bigger board plays with standard turn order (see README roadmap).
}
