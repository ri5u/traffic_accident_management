"""Plain-float geometry helpers (no GeoDjango / PostGIS — see NOTES.md)."""
import math

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1, lng1, lat2, lng2):
    """Great-circle distance in metres between two lat/lng points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bounding_box(lat, lng, radius_m):
    """Cheap lat/lng box used to pre-filter rows in SQL before exact haversine."""
    dlat = math.degrees(radius_m / EARTH_RADIUS_M)
    dlng = math.degrees(radius_m / (EARTH_RADIUS_M * max(math.cos(math.radians(lat)), 1e-6)))
    return lat - dlat, lat + dlat, lng - dlng, lng + dlng


def point_to_segment_m(plat, plng, alat, alng, blat, blng):
    """
    Approximate distance (m) from point P to segment AB using a local
    equirectangular projection — accurate to well under 1% for city-scale
    segments, which is all a route check needs.
    """
    ref = math.radians((alat + blat + plat) / 3)
    kx = EARTH_RADIUS_M * math.cos(ref) * math.pi / 180
    ky = EARTH_RADIUS_M * math.pi / 180
    ax, ay = alng * kx, alat * ky
    bx, by = blng * kx, blat * ky
    px, py = plng * kx, plat * ky
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def point_to_polyline_m(plat, plng, points):
    if len(points) == 1:
        return haversine_m(plat, plng, points[0][0], points[0][1])
    return min(
        point_to_segment_m(plat, plng, a[0], a[1], b[0], b[1]) for a, b in zip(points, points[1:])
    )
