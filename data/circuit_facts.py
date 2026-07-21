"""Wikipedia-sourced first-Grand-Prix facts per circuit.

The Jolpica/Ergast data only covers the F1 World Championship (1950–today),
but many circuits hosted Grands Prix before that — Spa's first Belgian GP was
1925. This is static history that never changes, so it's curated here rather
than fetched. Source: each circuit's English Wikipedia article (researched
2026-07-07). Non-championship F1 races count (Imola 1963, Interlagos 1972);
other disciplines don't (Losail's 2004 motorcycle GP, Suzuka's 1962 opener).

Keyed by Ergast circuit_id. Circuits whose first Grand Prix WAS their first
championship F1 race are omitted — the DB already has that year.
"""

FIRST_GRAND_PRIX = {
    "albert_park": (1953, "1953 Australian Grand Prix (pre-championship); F1 era from 1996"),
    "bremgarten": (1934, "1934 Swiss Grand Prix (pre-championship)"),
    "galvez": (1952, "1952 Buenos Aires Grand Prix (non-championship, Formula Libre); championship from 1953"),
    "imola": (1963, "1963 non-championship F1 race, won by Jim Clark; championship from 1980"),
    "indianapolis": (1911, "First Indianapolis 500; it counted toward the F1 championship 1950–1960"),
    "interlagos": (1972, "1972 Brazilian Grand Prix (non-championship); championship from 1973"),
    "monaco": (1929, "1929 Monaco Grand Prix (pre-championship)"),
    "monza": (1922, "1922 Italian Grand Prix (pre-championship)"),
    "nurburgring": (1927, "1927 German Grand Prix (pre-championship)"),
    "pedralbes": (1946, "1946 Penya Rhin Grand Prix (pre-championship)"),
    "reims": (1926, "1926 Grand Prix de la Marne (pre-championship)"),
    "rodriguez": (1962, "1962 Mexican Grand Prix (non-championship); championship from 1963"),
    "silverstone": (1948, "1948 British Grand Prix (pre-championship)"),
    "spa": (1925, "1925 Belgian Grand Prix (pre-championship)"),
    "zandvoort": (1949, "1949 Grote Prijs van Zandvoort, the circuit's first race named a Grand Prix (the 1948 opener was the non-GP Prijs van Zandvoort); Dutch GP from 1950"),
}
