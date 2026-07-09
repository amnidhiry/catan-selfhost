"""AI bot chat: on-topic pre-filter, context building, and the Haiku call.

Design (task #11):
- The pre-filter (looks_on_topic) is the real abuse defense — obviously
  off-topic/adversarial messages get a canned deflection with NO API call.
- Haiku only narrates; it never decides game state. Calls are best-effort and
  degrade gracefully: no ANTHROPIC_API_KEY (or any error) -> a canned
  deflection, never a crash or a hang.
- This module is decoupled from the game objects (takes plain data) so it can
  be unit-tested without a running game or an API key.
"""
import os
import random
from pathlib import Path

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 120

# Condensed rulebook, loaded once. Grounds rules questions in fact.
try:
    RULEBOOK = (Path(__file__).parent / "rules_reference.md").read_text()
except OSError:
    RULEBOOK = "Standard base-game Catan rules apply."

# Core Catan vocabulary. Extended per-room with player/bot names (room_vocab).
GAME_KEYWORDS = {
    "catan", "trade", "trading", "road", "roads", "settlement", "settlements",
    "city", "cities", "robber", "wheat", "wood", "brick", "ore", "sheep",
    "grain", "lumber", "clay", "rock", "wool", "dice", "die", "roll", "rolled",
    "vp", "vps", "point", "points", "port", "ports", "harbor", "harbour",
    "knight", "knights", "army", "longest", "largest", "resource", "resources",
    "bank", "steal", "stole", "discard", "build", "building", "built", "buy",
    "dev", "development", "card", "cards", "monopoly", "plenty", "hex", "tile",
    "tiles", "number", "seven", "turn", "win", "winning", "won", "block",
    "blocked", "board", "island", "game", "move", "moves", "settle", "pip",
    "odds", "expansion", "cornered", "corner", "node",
}

MAX_SHORT_MESSAGE = 40  # casual short banter passes even without a keyword


def looks_on_topic(message: str, room_vocab: set = frozenset()) -> bool:
    """Permissive gate: pass short casual banter and anything mentioning game
    vocabulary; only clearly unrelated longer messages fail. Not a strict topic
    classifier — just enough to catch 'write me a poem', 'capital of France',
    'ignore previous instructions', etc."""
    text = (message or "").strip()
    if len(text) < MAX_SHORT_MESSAGE:
        return True
    words = set(text.lower().replace("?", " ").replace("!", " ").replace(".", " ").split())
    return bool(words & (GAME_KEYWORDS | set(room_vocab)))


def find_addressed_bot(text: str, bots):
    """bots: iterable of (color, persona). Return the color of the bot this
    message addresses (via @name or its name appearing in the text), else None.
    First match by seat order wins."""
    low = (text or "").lower()
    for color, persona in bots:
        name = persona.name.lower()
        if f"@{name}" in low or name in low.split() or name in low.replace(",", " ").split():
            return color
    return None


def pick_deflection(persona) -> str:
    return random.choice(persona.deflections) if persona.deflections else "Let's keep it to the game."


def build_bot_context(persona, rulebook: str, my_recent, public_state: dict, recent_chat) -> str:
    """Compact per-bot context block. `my_recent` is THIS bot's own move log
    only (never another bot's). `public_state` is public board info plus this
    bot's own exact hand (a bot may know its own cards, like any player)."""
    moves = "; ".join(my_recent) if my_recent else "none yet"
    chat = "\n".join(recent_chat) if recent_chat else "(quiet)"
    vps = ", ".join(f"{c}:{v}" for c, v in public_state.get("vps", {}).items())
    return (
        f"{rulebook}\n\n"
        f"--- Live game ---\n"
        f"Victory points — {vps}\n"
        f"Current turn: {public_state.get('current_player', '?')}\n"
        f"Your hand: {public_state.get('my_resources', 'unknown')}\n"
        f"Your recent moves: {moves}\n"
        f"Recent chat:\n{chat}\n"
    )


def haiku_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


async def get_bot_reply(persona, context: str, message: str) -> str:
    """Best-effort Haiku reply. Returns a canned deflection on ANY failure
    (missing key, network, rate limit) so the caller never hangs or crashes."""
    if not haiku_available():
        return pick_deflection(persona)
    try:
        import anthropic

        client = anthropic.AsyncAnthropic()
        resp = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=persona.system_prompt + "\n\n" + context,
            messages=[{"role": "user", "content": message[:600]}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        text = " ".join(parts).strip()
        return text or pick_deflection(persona)
    except Exception:
        return pick_deflection(persona)
