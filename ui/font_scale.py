"""Application-wide, non-cumulative stylesheet font scaling."""

import re


FONT_SCALE_FACTORS = {"small": 0.9, "medium": 1.0, "large": 1.2}


def normalize_font_scale(value: object) -> str:
    """Return a supported scale name, falling back to the default."""
    scale = str(value or "").strip().lower()
    return scale if scale in FONT_SCALE_FACTORS else "medium"


def scale_stylesheet_font_sizes(stylesheet: str, scale: object) -> str:
    """Scale pixel font declarations from an unchanged source stylesheet."""
    factor = FONT_SCALE_FACTORS[normalize_font_scale(scale)]
    if factor == 1.0:
        return stylesheet

    def replace(match: re.Match[str]) -> str:
        size = max(1, round(int(match.group(1)) * factor))
        return f"font-size: {size}px"

    return re.sub(r"font-size\s*:\s*(\d+)px", replace, stylesheet, flags=re.IGNORECASE)


def apply_font_scale(app, scale: object, base_stylesheet: str | None = None) -> str:
    """Apply a scale without compounding previous applications."""
    if base_stylesheet is not None:
        app._quiz_base_stylesheet = base_stylesheet
    source = getattr(app, "_quiz_base_stylesheet", app.styleSheet())
    scaled = scale_stylesheet_font_sizes(source, scale)
    app.setStyleSheet(scaled)
    return scaled
