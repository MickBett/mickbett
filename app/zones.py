"""Shared shot-zone classification, used by both the API (zone-breakdown
table) and the chart renderer (zone-map image).

Zone layout follows the reference design (Hudl FastScout shot charts):
2PT shots are split by *distance* from the hoop -- Paint/Restricted Area,
Short Mid-Range, Long Mid-Range (each mid-range tier further split L/R) --
while 3PT shots are split by *angle* -- Corner / Wing / Top, pivoting from
the baseline centre (100, 50), same convention as before (0 deg = along
the baseline/corner, 90 deg = straight out from the hoop/top of the key).
Shot type (2pt/3pt) itself is taken directly from the feed, never re-derived
geometrically. That gives exactly 10 regions.
"""
import math

BUCKETS = ["0-8", "8-18", "18+"]

ZONE_ORDER = [
    "corner_3_L", "wing_3_L", "top_3", "wing_3_R", "corner_3_R",
    "paint", "short_corner_L", "short_corner_R", "mid_L", "mid_R",
]

ZONE_LABELS = {
    "corner_3_L": "Corner 3 (L)", "wing_3_L": "Wing 3 (L)", "top_3": "Top 3",
    "wing_3_R": "Wing 3 (R)", "corner_3_R": "Corner 3 (R)",
    "paint": "Paint / Restricted Area",
    "short_corner_L": "Short Corner (L)", "short_corner_R": "Short Corner (R)",
    "mid_L": "Mid-Range (L)", "mid_R": "Mid-Range (R)",
}


def mirror_point(x, y):
    """Mirror a shot taken at the far basket onto the single hoop (x>=50
    side) that the whole app renders everything against."""
    if x < 50:
        return 100 - x, 100 - y
    return x, y


LANE_HALF_WIDTH = 17.0   # lane box is 34 wide, centred
LANE_DEPTH = 16.0        # lane box extends 16 out from the baseline
SHORT_CORNER_DEPTH = 9.0  # baseline-adjacent band, outside the lane, for "short corner" 2s


def zone_for(x, y, action_type):
    """Classify one shot (raw, un-mirrored x/y as stored) into one of the
    10 zone keys in ZONE_ORDER."""
    x, y = mirror_point(x, y)
    dx = 100 - x        # distance out from the baseline ("depth")
    dy = y - 50          # signed distance from the court centreline
    side = "L" if dy < 0 else "R"

    if action_type == "3pt":
        theta = 90.0 if dx == 0 and dy == 0 else math.degrees(math.atan2(dx, abs(dy)))
        if theta >= 67.5:
            return "top_3"
        if theta >= 22.5:
            return f"wing_3_{side}"
        return f"corner_3_{side}"

    # 2pt: paint (the lane box) / short corner (shallow band beside the lane)
    # / mid-range (everything else inside the arc), matching the reference layout.
    if dx <= LANE_DEPTH and abs(dy) <= LANE_HALF_WIDTH:
        return "paint"
    if dx <= SHORT_CORNER_DEPTH:
        return f"short_corner_{side}"
    return f"mid_{side}"


def bucket_for(elapsed):
    if elapsed is None:
        return None
    if elapsed < 8:
        return "0-8"
    if elapsed < 18:
        return "8-18"
    return "18+"


def empty_ma():
    return {"m": 0, "a": 0}


def pct(m, a):
    return round(m / a * 100, 1) if a else None


def aggregate_zones(shot_rows):
    """shot_rows: iterable of objects/rows with x, y, made, action_type,
    shot_clock_used (sqlite3.Row or dict). Returns, per zone key, an
    'overall' makes/attempts total plus one per shot-clock bucket."""
    agg = {z: {"overall": empty_ma(), **{b: empty_ma() for b in BUCKETS}} for z in ZONE_ORDER}
    for r in shot_rows:
        if r["action_type"] not in ("2pt", "3pt"):
            continue
        zone = zone_for(r["x"], r["y"], r["action_type"])
        made = r["made"] or 0
        agg[zone]["overall"]["a"] += 1
        agg[zone]["overall"]["m"] += made
        b = bucket_for(r["shot_clock_used"])
        if b:
            agg[zone][b]["a"] += 1
            agg[zone][b]["m"] += made
    return agg


def zones_as_list(agg):
    out = []
    for z in ZONE_ORDER:
        row = agg[z]
        entry = {"zone": z, "label": ZONE_LABELS[z]}
        for key in ["overall"] + BUCKETS:
            m, a = row[key]["m"], row[key]["a"]
            entry[key] = {"m": m, "a": a, "pct": pct(m, a)}
        out.append(entry)
    return out
