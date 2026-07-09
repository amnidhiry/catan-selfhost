"""Extend catanatron's Color enum from 4 to 6 members, enabling 5-6 players.

catanatron's core game state is player-count agnostic — it's all `len(colors)`
and index-based `P0..Pn` — so the ONLY thing capping player count at 4 is the
`Color` enum having just RED/BLUE/ORANGE/WHITE. `aenum.extend_enum` adds members
to the existing enum in place (no fork, no monkeypatched copy), so every existing
`Color` reference across the engine sees the new members.

Import this module for its side effect before using Color.GREEN / Color.BROWN.
It is idempotent.
"""
import aenum

from catanatron.models.player import Color

EXTRA_COLORS = ("GREEN", "BROWN")

for _name in EXTRA_COLORS:
    if _name not in Color.__members__:
        aenum.extend_enum(Color, _name, _name)
