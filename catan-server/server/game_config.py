"""Game mode configurations, including the validated MINI_2P template.

Design provenance:
- MINI_2P_TEMPLATE: 7-hex board with 3 ports (2x generic 3:1, 1x wheat 2:1).
  Port coordinates/directions were empirically validated: all 6 port-accessible
  nodes land on real coastal intersections across 500 generated maps.
  Max settlement packing = 12 (vs 10 needed for two full player allotments).
- vps_to_win=8 for 2p compensates for the smaller board's lower total production.
"""
from dataclasses import dataclass, field
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
from catanatron.models.coordinate_system import Direction
from catanatron.models.enums import WHEAT


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


@dataclass(frozen=True)
class GameMode:
    key: str
    label: str
    min_players: int
    max_players: int
    vps_to_win: int
    map_template: MapTemplate

    def build_map(self) -> CatanMap:
        return CatanMap.from_template(self.map_template)


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
    # Future: "extended_6p" — requires new MapTemplate, special building
    # phase in the engine, and >4 entries in catanatron's Color enum.
}
