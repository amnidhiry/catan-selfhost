# Catan quick rules (bot grounding)

Condensed reference so bots answer rules questions from fact, not guesses.
Base game, as implemented here (2 = Duel small board / 3-4 = Standard).

## Goal
First player to reach the victory-point target on their turn wins
(Standard/Expansion = 10 VP, Duel = 8 VP). Settlement = 1 VP, City = 2 VP,
Longest Road = 2 VP, Largest Army = 2 VP, each Victory Point dev card = 1 VP
(hidden until you win).

## Turn order
1. Roll two dice. Every player collects resources from tiles matching the
   number, if they have a settlement (1 card) or city (2 cards) on that tile.
2. On a 7: nobody collects; every player holding more than 7 cards discards
   half (rounded down); the roller moves the robber to any tile and steals one
   random card from a player on that tile.
3. Then trade and build in any order, then end your turn.
You may also play one development card per turn (not the one you bought this
turn), before or after rolling.

## Building costs
- Road: 1 wood + 1 brick
- Settlement: 1 wood + 1 brick + 1 wheat + 1 sheep (must be 2+ edges from any
  other settlement/city — the distance rule — and connect to your road)
- City: 2 wheat + 3 ore (upgrades one of your existing settlements)
- Development card: 1 sheep + 1 wheat + 1 ore

## Development cards
- Knight: move the robber and steal, like rolling a 7. Most knights played
  (min 3) holds Largest Army (2 VP).
- Road Building: place 2 roads for free.
- Year of Plenty: take any 2 resource cards from the bank (may be the same).
- Monopoly: name a resource; every other player gives you all of theirs.
- Victory Point: +1 VP, kept hidden until you win.

## Trading
- With the bank: 4 of one resource for 1 of any (4:1).
- With a port: 3:1 at a generic port, or 2:1 at a matching-resource port, if
  you have a settlement/city on that port's node.
- With players: any deal both sides agree to (here trades are offered in chat
  and anyone may accept — you're never forced to wait on the whole table).

## Robber
Blocks the tile it sits on (no resources produced there) until moved by the
next 7 or Knight.

## Longest Road
2 VP for the longest unbroken road of 5+ segments; can be taken by another
player who builds a longer one (or if yours is cut by an opponent's settlement).
