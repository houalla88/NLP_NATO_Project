"""Jetons de la charte DataOptimization.be utilises par le rendu.

Source de verite : `assets/tokens.json` de la charte. Les valeurs sont reprises
ici parce que le moteur n'a aucune dependance d'execution et ne peut donc pas
lire un fichier de charte externe au moment du rendu. Toute divergence avec la
charte doit etre corrigee ICI, jamais dans le HTML genere.

Regle structurante rappelee : la menthe vive `#12d7b0` a un contraste de 1,85:1
sur blanc. Elle est donc reservee aux aplats, grilles et accents decoratifs. Le
texte, les liens et tout element porteur de sens utilisent `#09806c`.
"""

from __future__ import annotations

INK = "#090b10"
SURFACE = "#ffffff"
BRAND = "#12d7b0"
BRAND_DEEP = "#09806c"
BRAND_SOFT = "#72cdb8"
ACCENT = "#9c83ef"
ACCENT_DEEP = "#5439b4"

NEUTRAL = {
    "50": "#f7f8fa", "100": "#eef0f4", "200": "#dde1e8",
    "400": "#8b93a3", "600": "#525a6b", "800": "#252a35",
}

SEMANTIC = {
    "success": "#09806c", "warning": "#9a6207",
    "danger": "#b42318", "info": "#5439b4",
}

CATEGORICAL = ["#09806c", "#5439b4", "#b06400", "#1b6ca8", "#a03050", "#5a6472"]
SEQUENTIAL = ["#e6f7f3", "#a8e5d6", "#5fc9b2", "#22a68c", "#09806c", "#065445"]
DIVERGING = ["#b42318", "#e08b83", "#f2f2f2", "#7fc9b8", "#09806c"]
GRID = "#dde1e8"

EASING = "cubic-bezier(0.22, 1, 0.36, 1)"
ELEVATION_BRAND = "0 20px 48px rgba(9, 128, 108, 0.14)"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(round(c)))):02x}" for c in rgb)


def scale_color(fraction: float, stops: list[str] | None = None) -> str:
    """Couleur d'une echelle continue par interpolation lineaire entre paliers."""
    palette = stops or SEQUENTIAL
    clamped = max(0.0, min(1.0, fraction))
    if clamped >= 1.0:
        return palette[-1]
    position = clamped * (len(palette) - 1)
    low = int(position)
    weight = position - low
    start, end = _hex_to_rgb(palette[low]), _hex_to_rgb(palette[low + 1])
    return _rgb_to_hex(tuple(s + (e - s) * weight for s, e in zip(start, end)))


def readable_on(background: str) -> str:
    """Encre ou blanc, selon ce qui contraste le mieux avec le fond.

    Luminance relative WCAG. Evite le defaut le plus frequent d'une carte de
    chaleur : du texte sombre sur une cellule saturee, illisible precisement
    la ou la valeur est la plus forte.
    """
    r, g, b = (c / 255 for c in _hex_to_rgb(background))
    channels = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)
    ]
    luminance = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    contrast_white = 1.05 / (luminance + 0.05)
    contrast_ink = (luminance + 0.05) / 0.05
    return SURFACE if contrast_white >= contrast_ink else INK
