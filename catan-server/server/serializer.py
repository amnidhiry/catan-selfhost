"""Per-player state serialization — the hidden-information boundary.

RULE: never send raw game.state over the wire. Everything a client receives
passes through serialize_for(game, viewer_color). Opponents' hands are
reduced to counts; VP cards stay hidden (VICTORY_POINTS is public score,
ACTUAL_VICTORY_POINTS includes hidden VP cards and is private).

Pattern follows JSettlers2's server->client model: per-player views, counts
only for others.
"""
from typing import Optional

from catanatron import Game
from catanatron.models.player import Color
from catanatron.models.enums import RESOURCES, DEVELOPMENT_CARDS, ActionType

DEV_CARD_TYPES = list(DEVELOPMENT_CARDS)


def _pkey(state, color: Color) -> str:
    index = state.color_to_index[color]
    return f"P{index}"


def serialize_board(game: Game) -> dict:
    """Public board info: tiles, numbers, ports, robber. Same for everyone."""
    board = game.state.board
    tiles = []
    for coordinate, tile in board.map.land_tiles.items():
        tiles.append(
            {
                "id": tile.id,
                "coordinate": coordinate,
                "resource": tile.resource,  # None => desert
                "number": tile.number,
                "nodes": {ref.value: nid for ref, nid in tile.nodes.items()},
                "edges": {ref.value: list(eid) for ref, eid in tile.edges.items()},
            }
        )
    ports = []
    for port in board.map.ports_by_id.values():
        ports.append(
            {
                "id": port.id,
                "resource": port.resource,  # None => 3:1 generic
                "direction": port.direction.value,
                "nodes": sorted(
                    set(port.nodes.values()) & set(board.map.land_nodes)
                ),
            }
        )
    return {
        "tiles": tiles,
        "ports": ports,
        "robber": board.robber_coordinate,
        "buildings": [
            {"node_id": nid, "color": c.value, "type": btype}
            for nid, (c, btype) in board.buildings.items()
        ],
        # board.roads stores each road bidirectionally ((a,b) and (b,a) both
        # map to the same road). Dedupe on the canonical sorted-edge key so
        # each road is sent once. Wire format is unchanged: {edge: [a,b], color}.
        "roads": [
            {"edge": list(edge), "color": c.value}
            for edge, c in {
                tuple(sorted(edge)): c for edge, c in board.roads.items()
            }.items()
        ],
    }


def serialize_public_player(game: Game, color: Color) -> dict:
    """What everyone may know about a player (hand *counts*, public VPs)."""
    state = game.state
    key = _pkey(state, color)
    ps = state.player_state
    resource_count = sum(ps[f"{key}_{r}_IN_HAND"] for r in RESOURCES)
    dev_count = sum(ps[f"{key}_{d}_IN_HAND"] for d in DEV_CARD_TYPES)
    return {
        "color": color.value,
        "public_victory_points": ps[f"{key}_VICTORY_POINTS"],
        "resource_count": resource_count,
        "dev_card_count": dev_count,
        "played_knights": ps[f"{key}_PLAYED_KNIGHT"],
        "has_longest_road": ps[f"{key}_HAS_ROAD"],
        "has_largest_army": ps[f"{key}_HAS_ARMY"],
        "roads_available": ps[f"{key}_ROADS_AVAILABLE"],
        "settlements_available": ps[f"{key}_SETTLEMENTS_AVAILABLE"],
        "cities_available": ps[f"{key}_CITIES_AVAILABLE"],
    }


def serialize_private_hand(game: Game, color: Color) -> dict:
    """Only ever sent to `color`'s own socket."""
    state = game.state
    key = _pkey(state, color)
    ps = state.player_state
    return {
        "resources": {r: ps[f"{key}_{r}_IN_HAND"] for r in RESOURCES},
        "dev_cards": {d: ps[f"{key}_{d}_IN_HAND"] for d in DEV_CARD_TYPES},
        "actual_victory_points": ps[f"{key}_ACTUAL_VICTORY_POINTS"],
    }


def discard_remaining(game: Game, color: Color) -> int:
    """How many cards `color` must discard right now (0 when not discarding).

    catanatron discards a random half of the hand in one DISCARD action (there
    is no per-card choice in the engine), so this is purely for display: the
    number the current discarder is about to lose. The old per-player
    `state.discard_counts` array was removed from the engine — derive it.
    """
    state = game.state
    if not state.is_discarding or state.current_color() != color:
        return 0
    key = _pkey(state, color)
    hand = sum(state.player_state[f"{key}_{r}_IN_HAND"] for r in RESOURCES)
    return hand // 2


def last_roll(game: Game) -> Optional[list]:
    """The two dice faces of the most recent roll, or None (e.g. during setup,
    before anyone has rolled). catanatron rolls 2d6 and records the pair as the
    ROLL action's value — we surface both faces so the UI can show real dice."""
    for record in reversed(game.state.action_records):
        if record.action.action_type == ActionType.ROLL:
            return list(record.action.value)
    return None


def serialize_playable_actions(game: Game, color: Color) -> list[dict]:
    """Valid actions for `color` right now — drives UI highlighting.

    Empty list if it's not this player's decision point.
    """
    if game.state.current_color() != color:
        return []
    return [
        {"type": a.action_type.value, "value": _jsonable(a.value)}
        for a in game.playable_actions
    ]


def _jsonable(value):
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, Color):
        return value.value
    return value


def serialize_for(game: Game, viewer: Color, seating: list[Color]) -> dict:
    """Complete state snapshot as `viewer` is allowed to see it."""
    state = game.state
    return {
        "board": serialize_board(game),
        "players": [serialize_public_player(game, c) for c in seating],
        "your_color": viewer.value,
        "your_hand": serialize_private_hand(game, viewer),
        "current_player": state.current_color().value,
        # Whose TURN it is — differs from current_player while a trade is
        # being decided (current_player rotates through the deciders).
        "turn_player": state.colors[state.current_turn_index].value,
        "current_prompt": state.current_prompt.value,
        # How many cards YOU must discard (7-roll). 0 when not discarding.
        "discard_remaining": discard_remaining(game, viewer),
        # Standing offer, publicly visible while resolving:
        # first 10 slots = give/get freqdecks (WOOD,BRICK,SHEEP,WHEAT,ORE x2).
        "current_trade": list(state.current_trade[:10])
        if state.is_resolving_trade
        else None,
        "playable_actions": serialize_playable_actions(game, viewer),
        # Two dice faces of the most recent roll (null during setup).
        "last_roll": last_roll(game),
        "winner": game.winning_color().value if game.winning_color() else None,
    }
