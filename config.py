"""Central configuration for the F1 Analytics Dashboard."""

import os

# API
API_BASE_URL = "https://api.jolpi.ca/ergast/f1"
API_RATE_LIMIT_DELAY = 0.5  # seconds between API calls

# Database
DB_PATH = os.path.join(os.path.dirname(__file__), "f1_data.db")

# Historical F1 point systems
POINT_SYSTEMS = {
    "2010-present": {1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 2, 10: 1},
    "2003-2009": {1: 10, 2: 8, 3: 6, 4: 5, 5: 4, 6: 3, 7: 2, 8: 1},
    "1991-2002": {1: 10, 2: 6, 3: 4, 4: 3, 5: 2, 6: 1},
    "1961-1990": {1: 9, 2: 6, 3: 4, 4: 3, 5: 2, 6: 1},
    "1950-1960": {1: 8, 2: 6, 3: 4, 4: 3, 5: 2},
}

# Team colors — current + historical constructors
TEAM_COLORS = {
    # Current grid (2024-2026)
    "red_bull": "#3671C6",
    "ferrari": "#E8002D",
    "mercedes": "#27F4D2",
    "mclaren": "#FF8000",
    "aston_martin": "#229971",
    "alpine": "#FF87BC",
    "williams": "#64C4FF",
    "haas": "#B6BABD",
    "rb": "#6692FF",
    "sauber": "#52E252",
    # Recent / rebranded
    "alphatauri": "#4E7C9B",
    "alfa": "#B12025",
    "renault": "#FFF500",
    "racing_point": "#F596C8",
    "force_india": "#FF80C7",
    "toro_rosso": "#469BFF",
    # Classic teams
    "lotus_f1": "#FFB800",
    "brawn": "#C8FF00",
    "jordan": "#F5D000",
    "benetton": "#00B050",
    "tyrrell": "#0048BA",
    "brabham": "#00A550",
    "minardi": "#FFD700",
    "jaguar": "#006400",
    "toyota": "#CC0000",
    "bmw_sauber": "#0066CC",
    "honda": "#FFFFFF",
    "manor": "#E2001A",
    "marussia": "#6E0000",
    "caterham": "#005030",
    "hrt": "#968C6D",
    "lotus_racing": "#DAA520",
    "virgin": "#CC0000",
}

# Plotly defaults
PLOTLY_TEMPLATE = "plotly_dark"
