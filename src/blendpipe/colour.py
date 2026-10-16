"""Colours: '#rrggbb' hex (sRGB, what you write) and linear RGB(A) (what Blender wants). Pure Python."""


def _check(hex_):
    h = hex_.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"colour {hex_!r} is not '#rrggbb'")
    return h


def _to_linear(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(v):
    v = v * 12.92 if v <= 0.0031308 else 1.055 * max(v, 0.0) ** (1 / 2.4) - 0.055
    return max(0, min(255, round(v * 255)))


def srgb(hex_):
    """'#rrggbb' as the linear RGBA tuple Blender's colour inputs take."""
    h = _check(hex_)
    return (_to_linear(int(h[0:2], 16)), _to_linear(int(h[2:4], 16)), _to_linear(int(h[4:6], 16)), 1.0)


def to_hex(rgb):
    """A linear RGB(A) tuple back to '#rrggbb' (the inverse of srgb)."""
    return "#" + "".join(f"{_to_srgb(v):02x}" for v in rgb[:3])


def shade(hex_, factor):
    """hex_ made lighter (factor > 1) or darker (factor < 1): a second tone of the same colour."""
    h = _check(hex_)
    rgb = [min(255, max(0, round(int(h[i:i + 2], 16) * factor))) for i in (0, 2, 4)]
    return "#" + "".join(f"{c:02x}" for c in rgb)


def grey(value):
    """A grey of value 0..1 (as sRGB) as '#rrggbb'."""
    c = round(max(0.0, min(1.0, value)) * 255)
    return f"#{c:02x}{c:02x}{c:02x}"


def linear(c):
    """A colour as linear RGB: '#rrggbb', a grey (0..1, as sRGB) or an (r, g, b) that is already linear."""
    if isinstance(c, str):
        return srgb(c)[:3]
    if isinstance(c, (int, float)):
        return srgb(grey(c))[:3]
    return tuple(c[:3])


def mix(a, b, w):
    """Two linear colours mixed by w (0: a, 1: b)."""
    return tuple(x + (y - x) * w for x, y in zip(a, b))
