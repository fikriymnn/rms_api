from math import asin, cos, radians, sin, sqrt


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Jarak haversine dalam meter."""
    r = 6371000.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    )
    return 2 * r * asin(sqrt(a))
