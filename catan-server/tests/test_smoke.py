"""Smoke test: drive a complete mini_2p game through Room.execute()
by always choosing the first playable action — proves the session layer,
config, and engine integrate end to end.

Also asserts the hidden-info serializer never leaks opponents' hands.
"""
import random
import sys

sys.path.insert(0, ".")

from server.rooms import Room, RoomPhase, Seat
from server.serializer import serialize_for
from catanatron.models.player import Color


def play_one_game(mode_key: str, seats: list[str]) -> Room:
    from server.rooms import SEAT_ORDER

    room = Room(code="TEST", host_token="t")
    for name, color in zip(seats, SEAT_ORDER):
        room.seats[color] = Seat(name=name, color=color, rejoin_token=name)
    room.start(mode_key)

    steps = 0
    while room.phase != RoomPhase.OVER:
        state = room.game.state
        color = state.current_color()
        action = random.choice(room.game.playable_actions)
        room.execute(color, action.action_type, action.value)
        steps += 1
        assert steps < 20000, "game did not terminate"
    return room


def test_mini_2p_completes():
    room = play_one_game("mini_2p", ["abe", "ria"])
    assert room.game.winning_color() is not None
    print(f"mini_2p winner: {room.game.winning_color()}")


def test_standard_completes():
    room = play_one_game("standard", ["a", "b", "c", "d"])
    assert room.game.winning_color() is not None
    print(f"standard winner: {room.game.winning_color()}")


# NOTE: the 5-6 "expansion" mode is currently hidden/disabled (its board's road
# graph is wrong — see task #9). Its smoke test returns once the board is fixed.


def test_bot_game_completes():
    """1 human + 1 bot: drive it with the same rule the server uses (bots decide,
    humans pick a random legal action) and confirm it plays to a winner."""
    room = Room(code="BOT", host_token="t")
    room.seats[Color.RED] = Seat(name="human", color=Color.RED, rejoin_token="h")
    room.add_bot("normal")
    room.start("mini_2p")
    assert any(s.is_bot for s in room.seats.values())

    steps = 0
    while room.phase != RoomPhase.OVER:
        color = room.game.state.current_color()
        if room.is_bot(color):
            action = room.bot_player(color).decide(
                room.game, room.game.playable_actions
            )
        else:
            action = random.choice(room.game.playable_actions)
        room.execute(action.color, action.action_type, action.value)
        steps += 1
        assert steps < 20000, "bot game did not terminate"
    assert room.game.winning_color() is not None
    print(f"bot game winner: {room.game.winning_color()}")


def test_serializer_hides_opponent_hands():
    room = Room(code="TEST", host_token="t")
    room.seats[Color.RED] = Seat("abe", Color.RED, "t1")
    room.seats[Color.BLUE] = Seat("ria", Color.BLUE, "t2")
    room.start("mini_2p")

    view = serialize_for(room.game, Color.RED, room.seating)
    assert view["your_color"] == "RED"
    assert "resources" in view["your_hand"]
    for p in view["players"]:
        # public player objects expose counts only — never per-resource dicts
        assert "resources" not in p
        assert "dev_cards" not in p
        assert "resource_count" in p
    print("serializer: opponents' hands are counts only ✓")


if __name__ == "__main__":
    random.seed(42)
    test_mini_2p_completes()
    test_standard_completes()
    test_bot_game_completes()
    test_serializer_hides_opponent_hands()
    print("ALL SMOKE TESTS PASSED")
