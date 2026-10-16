"""Settings every model of this project shares (all optional; see blendpipe.runner for the full list)."""

# Every model's spec starts from these; a model's own SPEC overrides them.
DEFAULTS = dict(kb=64, tris=2000)

# Named looks for materials: blendpipe.material(name, colour, finish="wood").
FINISHES = {
    "wood": dict(rough=0.75),
    "metal": dict(rough=0.35, metal=1.0),
    "matte": dict(rough=0.9),
    "flame": dict(rough=0.5, emit="#ffb347", strength=6.0),
}

# Tint roles: materials built as greys that the app recolours. The review sheets preview them in these colours.
TINTS = {"team": "#2a4f9e", "skin": "#d9a882", "accent": "#a8322a"}

# Everything under the output folder together.
TOTAL_KB = 1024
