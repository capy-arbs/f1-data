"""Point system normalization for cross-era comparisons."""

from config import POINT_SYSTEMS


def get_point_system_for_year(year: int) -> dict[int, int]:
    """Return the point system that was active in a given year."""
    if year >= 2010:
        return POINT_SYSTEMS["2010-present"]
    elif year >= 2003:
        return POINT_SYSTEMS["2003-2009"]
    elif year >= 1991:
        return POINT_SYSTEMS["1991-2002"]
    elif year >= 1961:
        return POINT_SYSTEMS["1961-1990"]
    else:
        return POINT_SYSTEMS["1950-1960"]


def normalize_points(position: int | None, target_system: str = "2010-present") -> float:
    """Calculate points for a finish position under a given system."""
    if position is None:
        return 0.0
    system = POINT_SYSTEMS.get(target_system, POINT_SYSTEMS["2010-present"])
    return float(system.get(position, 0))
