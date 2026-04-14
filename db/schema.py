"""Database schema definition and initialization."""

from db.connection import get_db

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS seasons (
    year INTEGER PRIMARY KEY,
    url TEXT
);

CREATE TABLE IF NOT EXISTS circuits (
    circuit_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    locality TEXT,
    country TEXT,
    lat REAL,
    lng REAL,
    url TEXT
);

CREATE TABLE IF NOT EXISTS drivers (
    driver_id TEXT PRIMARY KEY,
    number INTEGER,
    code TEXT,
    given_name TEXT NOT NULL,
    family_name TEXT NOT NULL,
    date_of_birth TEXT,
    nationality TEXT,
    url TEXT
);

CREATE TABLE IF NOT EXISTS constructors (
    constructor_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    nationality TEXT,
    url TEXT
);

CREATE TABLE IF NOT EXISTS races (
    race_id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    round INTEGER NOT NULL,
    race_name TEXT NOT NULL,
    circuit_id TEXT NOT NULL REFERENCES circuits(circuit_id),
    date TEXT NOT NULL,
    time TEXT,
    UNIQUE(season, round)
);

CREATE TABLE IF NOT EXISTS results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id INTEGER NOT NULL REFERENCES races(race_id),
    driver_id TEXT NOT NULL REFERENCES drivers(driver_id),
    constructor_id TEXT NOT NULL REFERENCES constructors(constructor_id),
    grid INTEGER,
    position INTEGER,
    position_text TEXT,
    points REAL NOT NULL DEFAULT 0,
    laps INTEGER,
    status TEXT,
    time_millis INTEGER,
    time_text TEXT,
    fastest_lap_rank INTEGER,
    fastest_lap_time TEXT,
    fastest_lap_speed REAL,
    UNIQUE(race_id, driver_id)
);

CREATE TABLE IF NOT EXISTS sprint_results (
    sprint_result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id INTEGER NOT NULL REFERENCES races(race_id),
    driver_id TEXT NOT NULL REFERENCES drivers(driver_id),
    constructor_id TEXT NOT NULL REFERENCES constructors(constructor_id),
    grid INTEGER,
    position INTEGER,
    position_text TEXT,
    points REAL NOT NULL DEFAULT 0,
    laps INTEGER,
    status TEXT,
    time_text TEXT,
    UNIQUE(race_id, driver_id)
);

CREATE TABLE IF NOT EXISTS qualifying (
    qual_id INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id INTEGER NOT NULL REFERENCES races(race_id),
    driver_id TEXT NOT NULL REFERENCES drivers(driver_id),
    constructor_id TEXT NOT NULL REFERENCES constructors(constructor_id),
    position INTEGER,
    q1 TEXT,
    q2 TEXT,
    q3 TEXT,
    UNIQUE(race_id, driver_id)
);

CREATE TABLE IF NOT EXISTS pit_stops (
    pit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id INTEGER NOT NULL REFERENCES races(race_id),
    driver_id TEXT NOT NULL REFERENCES drivers(driver_id),
    stop_number INTEGER NOT NULL,
    lap INTEGER,
    time_of_day TEXT,
    duration TEXT,
    duration_ms REAL,
    UNIQUE(race_id, driver_id, stop_number)
);

CREATE TABLE IF NOT EXISTS driver_standings (
    standing_id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    round INTEGER NOT NULL,
    driver_id TEXT NOT NULL REFERENCES drivers(driver_id),
    constructor_id TEXT NOT NULL REFERENCES constructors(constructor_id),
    position INTEGER NOT NULL,
    points REAL NOT NULL,
    wins INTEGER NOT NULL,
    UNIQUE(season, round, driver_id)
);

CREATE TABLE IF NOT EXISTS constructor_standings (
    standing_id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    round INTEGER NOT NULL,
    constructor_id TEXT NOT NULL REFERENCES constructors(constructor_id),
    position INTEGER NOT NULL,
    points REAL NOT NULL,
    wins INTEGER NOT NULL,
    UNIQUE(season, round, constructor_id)
);

CREATE TABLE IF NOT EXISTS fetch_log (
    endpoint TEXT NOT NULL,
    season INTEGER,
    round INTEGER,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    record_count INTEGER,
    PRIMARY KEY (endpoint, season, round)
);

CREATE INDEX IF NOT EXISTS idx_results_driver ON results(driver_id);
CREATE INDEX IF NOT EXISTS idx_results_race ON results(race_id);
CREATE INDEX IF NOT EXISTS idx_results_constructor ON results(constructor_id);
CREATE INDEX IF NOT EXISTS idx_races_season ON races(season);
CREATE INDEX IF NOT EXISTS idx_driver_standings_season ON driver_standings(season, round);
CREATE INDEX IF NOT EXISTS idx_constructor_standings_season ON constructor_standings(season, round);
CREATE INDEX IF NOT EXISTS idx_pit_stops_race ON pit_stops(race_id);
CREATE INDEX IF NOT EXISTS idx_qualifying_race ON qualifying(race_id);
CREATE INDEX IF NOT EXISTS idx_sprint_results_race ON sprint_results(race_id);
"""


def init_db():
    """Create all tables and indexes if they don't exist."""
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
