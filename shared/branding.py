"""Brand constants. Use these wherever the backend writes the app name
(docs titles, emails, notification text...) so the brand stays consistent.

Source of truth for the artwork: `design/brand/` (see its README.md).
"""

from shared.settings import get_shared_settings

APP_NAME = "BrAInBox"
TAGLINE = "Study smarter. Fix what matters."

# Brand colours
PRIMARY = "#4F46E5"  # indigo
SECONDARY = "#0EA5A4"  # teal
INK = "#1E1B4B"  # dark text
ACCENT_MINT = "#6EE7B7"
ACCENT_AMBER = "#FCD34D"

# Static brand files served by both services under /static/brand/
FAVICON_32_PATH = "/static/brand/favicon_32.png"
FAVICON_192_PATH = "/static/brand/favicon_192.png"
ICON_SVG_PATH = "/static/brand/brainbox-icon.svg"

# Logo URL comes from the LOGO_URL setting (defaults to the static logo path).
LOGO_URL = get_shared_settings().LOGO_URL
