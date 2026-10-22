"""Colour schemes and logos selectable on the admin settings page.

Each scheme becomes CSS custom properties on <html> (see scheme_css and the base templates),
which both stylesheets use:
    c1..c3 - the button/text gradient; c4 - an extra stop for the animated survey background
    glow   - RGB of the coloured shadows; shade - RGB of the dark card shadow

Adding a scheme: add an entry here; it shows up on the settings page automatically.
Adding a logo: add its key and name to LOGOS and its <path> to logo_paths() in templates/_logo.html
(drawn on a 24x24 grid).
"""

SCHEMES = {
    "flame": {"name": "Flame", "c1": "#fd297b", "c2": "#ff5864", "c3": "#ff655b", "c4": "#ff7854",
              "glow": "253, 41, 123", "shade": "120, 0, 40"},
    "twilight": {"name": "Twilight", "c1": "#6d28d9", "c2": "#9333ea", "c3": "#c026d3", "c4": "#4f46e5",
                 "glow": "124, 58, 237", "shade": "40, 10, 90"},
    "ocean": {"name": "Ocean", "c1": "#1d4ed8", "c2": "#0284c7", "c3": "#0891b2", "c4": "#06b6d4",
              "glow": "29, 78, 216", "shade": "10, 30, 90"},
    "sunset": {"name": "Sunset", "c1": "#e11d48", "c2": "#ea580c", "c3": "#f59e0b", "c4": "#f97316",
               "glow": "234, 88, 12", "shade": "110, 30, 0"},
    "mint": {"name": "Mint", "c1": "#047857", "c2": "#059669", "c3": "#0d9488", "c4": "#10b981",
             "glow": "5, 150, 105", "shade": "0, 60, 40"},
}

# The SVG shapes live in templates/_logo.html
LOGOS = {
    "flame": "Flame",
    "heart": "Heart",
    "ghost": "Ghost",
    "sparkle": "Sparkle",
    "wine": "Wine glass",
}


def scheme_css(key):
    """Inline CSS custom properties for a scheme, for the style attribute on <html>."""
    s = SCHEMES.get(key) or SCHEMES["flame"]
    return (f"--c1:{s['c1']};--c2:{s['c2']};--c3:{s['c3']};--c4:{s['c4']};"
            f"--glow:{s['glow']};--shade:{s['shade']}")
