"""Game mode configurations.

- MINI_2P_TEMPLATE: 7-hex board with 3 ports (2x generic 3:1, 1x wheat 2:1),
  validated so all port nodes land on real coastal intersections. 2p, 8 VP.
- Expansion (5-6p): a correct 37-tile board built in expansion_board.py, which
  also patches catanatron's global road graph so the larger board wires up
  correctly while leaving Standard/Duel identical (task #9).
"""
from dataclasses import dataclass
from typing import Callable, Optional

from catanatron.models.map import (
    MapTemplate,
    CatanMap,
    Port,
    MINI_MAP_TEMPLATE,
    BASE_MAP_TEMPLATE,
)
from catanatron.models.coordinate_system import Direction
from catanatron.models.enums import WHEAT

from .expansion_board import build_expansion_map


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
    map_template: Optional[MapTemplate] = None
    # Custom-geometry boards use a builder (built via from_tiles) instead of a
    # template — they can't use the official coast-following number spiral.
    map_builder: Optional[Callable[[], CatanMap]] = None
    number_placement: str = "official_spiral"
    hidden: bool = False  # hidden modes aren't offered and can't be started

    def build_map(self) -> CatanMap:
        if self.map_builder is not None:
            return self.map_builder()
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
        map_builder=build_expansion_map,
    ),
    # Note: the official 5-6 "special building phase" is not modelled — the
    # bigger board plays with standard turn order (see README roadmap).
}
