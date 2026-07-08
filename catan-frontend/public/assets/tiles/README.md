# Terrain tile art

Drop PNGs here with these EXACT filenames — Board.jsx references them by name,
no code changes needed once they're in place. Square images work best (they
get clipped to the hex shape automatically); ~512x512px is plenty.

    forest.png      WOOD tiles
    hills.png       BRICK tiles
    pasture.png     SHEEP tiles
    fields.png      WHEAT tiles
    mountains.png   ORE tiles
    desert.png      the single desert tile (no resource, no number)

Until a file exists, that terrain silently falls back to its flat CSS color
(see --forest, --hills, etc. in styles.css) — nothing breaks, it just looks
plain until you drop the art in.

Good free/open sources: kenney.nl (CC0), opengameart.org (hex tile terrain,
CC0/CC-BY), itch.io (search "hex terrain assets" for painterly styles closer
to a physical board look).
