"""Server-rendered shot-chart images (season-wide, i.e. every game imported
so far for a given team or player).

Court orientation follows the Hudl FastScout reference: hoop at the TOP of
the image, baseline across the top, the arc opening downward toward
half-court. Internally, shots are still stored/mirrored in the original
(hoop-on-the-right) coordinate system used by the rest of the app; `_top()`
swaps (x, y) -> (y, x) at draw time to produce that orientation, since
swapping the two axes is exactly the transform that rotates "hoop on the
right" into "hoop on top".
"""
import io
import math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors as mcolors
from matplotlib.patches import Rectangle, Arc, Circle, Wedge, RegularPolygon, FancyBboxPatch, Polygon
from matplotlib.transforms import Bbox

from . import db
from . import zones as zonemod

MAKE = "#1baf7a"
MISS = "#e34948"
INK = "#0b0b0b"
INK2 = "#52514e"
SURFACE = "#fcfcfb"

# Flat-color court styling (matches the Hudl FastScout reference): pale mint
# court, cream-highlighted paint, black line art, white zone dividers.
COURT_BG = "#dcebe0"
PAINT_BG = "#f3ead9"
LINE_BLACK = "#181818"
DIVIDER_WHITE = "#ffffff"
LABEL_BG = "#f2f2ef"

# Hoop position in the ORIGINAL (hoop-right) coordinate space; _top() below
# swaps it to (50, 94) for drawing.
HOOP = (94.0, 50.0)
HOOP_TOP = (50.0, 94.0)

# 3PT boundary (drawing units, from the hoop) -- an ELLIPSE rather than a
# true circle: wide sideways (ARC_R_W, how far out the corners/wings reach)
# but shallower toward half-court (ARC_R_D, how deep the top-of-the-key
# point goes), so the arc stays close to the free-throw circle instead of
# leaving a big empty gap at the top, per request.
ARC_R_W = 38.0
ARC_R_D = 24.0

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "text.color": INK,
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
})


def _mirror(rows):
    out = []
    for r in rows:
        x, y = r["x"], r["y"]
        if x is None or y is None:
            continue
        if x < 50:
            x, y = 100 - x, 100 - y
        out.append({**dict(r), "x": x, "y": y})
    return out


def _top(x, y):
    """Swap into hoop-at-top drawing coordinates."""
    return y, x


# --------------------------------------------------------------- court ----
def _draw_court_bg(ax):
    """Flat mint court background + cream paint/restricted-area highlight --
    used everywhere except the zone map, which colours each region itself."""
    ax.add_patch(FancyBboxPatch((0, 50), 100, 50, boxstyle="round,pad=0,rounding_size=3",
                                 facecolor=COURT_BG, edgecolor="none", zorder=0))
    ax.add_patch(Rectangle((33, 84), 34, 16, facecolor=PAINT_BG, edgecolor="none", zorder=1))
    ax.add_patch(Wedge(HOOP_TOP, 4, 180, 360, facecolor=PAINT_BG, edgecolor="none", zorder=1))


def _draw_court_lines(ax):
    lw = 1.6
    # court boundary (rounded outer corners, baseline + sidelines) + half-court line
    ax.add_patch(FancyBboxPatch((0, 50), 100, 50, boxstyle="round,pad=0,rounding_size=3",
                                 facecolor="none", edgecolor=LINE_BLACK, lw=lw, zorder=2))
    ax.plot([0, 100], [50, 50], color=LINE_BLACK, lw=1, linestyle="--", zorder=2)
    # key / paint outline
    ax.add_patch(Rectangle((33, 84), 34, 16, fill=False, edgecolor=LINE_BLACK, lw=lw, zorder=3))
    # lane hash marks (rebound markers), one per side
    ax.plot([33, 31.3], [92, 92], color=LINE_BLACK, lw=lw, zorder=3)
    ax.plot([67, 68.7], [92, 92], color=LINE_BLACK, lw=lw, zorder=3)
    # lane blocks (small filled squares at the restricted-area line level)
    ax.add_patch(Rectangle((32.1, 89.6), 1.4, 1.1, facecolor=LINE_BLACK, edgecolor="none", zorder=3))
    ax.add_patch(Rectangle((66.5, 89.6), 1.4, 1.1, facecolor=LINE_BLACK, edgecolor="none", zorder=3))
    # free-throw line + circle (bottom half only, solid -- matches reference)
    ax.plot([33, 67], [84, 84], color=LINE_BLACK, lw=lw, zorder=3)
    ax.add_patch(Arc((50, 84), 18, 18, angle=0, theta1=180, theta2=360, color=LINE_BLACK, lw=lw, zorder=3))
    # restricted-area arc, bulging toward half-court (away from baseline)
    ax.add_patch(Arc(HOOP_TOP, 8, 8, angle=0, theta1=180, theta2=360, color=LINE_BLACK, lw=lw, zorder=3))
    # 3PT arc (elliptical: wide sideways, shallower toward half-court) --
    # only the natural bottom half, where it's actually curving. At its own
    # widest point the ellipse's tangent is already vertical, so a straight
    # line picks up there with zero kink and runs up to the baseline --
    # a real court's corner-3 line meets the baseline at a clean right
    # angle, not as a curve trailing off into it at a shallow angle.
    lw_3pt = lw + 0.6  # the 2PT/3PT boundary -- worth making unmistakable
    ax.add_patch(Arc(HOOP_TOP, ARC_R_W * 2, ARC_R_D * 2, angle=0, theta1=180, theta2=360,
                      color=LINE_BLACK, lw=lw_3pt, zorder=6))
    ax.plot([50 - ARC_R_W, 50 - ARC_R_W], [94, 100], color=LINE_BLACK, lw=lw_3pt, zorder=6)
    ax.plot([50 + ARC_R_W, 50 + ARC_R_W], [94, 100], color=LINE_BLACK, lw=lw_3pt, zorder=6)
    # backboard, small connector, and hoop
    ax.plot([44, 56], [97, 97], color=LINE_BLACK, lw=2.4, zorder=4, solid_capstyle="butt")
    ax.add_patch(Polygon([[48.7, 97], [51.3, 97], [50.6, 95.3], [49.4, 95.3]],
                          closed=True, facecolor=LINE_BLACK, edgecolor="none", zorder=4))
    ax.add_patch(Circle(HOOP_TOP, 1.1, fill=False, edgecolor=LINE_BLACK, lw=1.8, zorder=4))


def _draw_court(ax):
    ax.set_facecolor(SURFACE)
    _draw_court_bg(ax)
    _draw_court_lines(ax)
    ax.set_xlim(-2, 102)
    ax.set_ylim(48, 102)
    ax.set_aspect(28.0 / 15.0)
    ax.axis("off")


def _plot_shots(ax, shots, dot=34):
    made = [_top(s["x"], s["y"]) for s in shots if s["made"] == 1]
    missed = [_top(s["x"], s["y"]) for s in shots if s["made"] == 0]
    if missed:
        ax.scatter([p[0] for p in missed], [p[1] for p in missed],
                   marker="x", s=dot, color=MISS, linewidths=1.6, alpha=0.9, zorder=3)
    if made:
        ax.scatter([p[0] for p in made], [p[1] for p in made],
                   marker="o", s=dot, facecolor=MAKE, edgecolor="white", linewidths=0.6,
                   alpha=0.9, zorder=4)


def _fg_str(shots):
    m = sum(1 for s in shots if s["made"] == 1)
    a = len(shots)
    pct = (m / a * 100) if a else 0
    return f"{m}/{a} ({pct:.0f}%)"


def _render(title, subtitle, shots):
    fig = plt.figure(figsize=(6.2, 6.6))
    fig.text(0.5, 0.97, title, fontsize=14, fontweight="bold", ha="center", color=INK)
    fig.text(0.5, 0.935, subtitle, fontsize=10.5, ha="center", color=INK2)
    ax = fig.add_axes([0.06, 0.09, 0.88, 0.80])
    _draw_court(ax)
    _plot_shots(ax, shots, dot=40)
    twos = [s for s in shots if s["action_type"] == "2pt"]
    threes = [s for s in shots if s["action_type"] == "3pt"]
    ax.text(50, 45, f"2PT: {_fg_str(twos)}    3PT: {_fg_str(threes)}",
            ha="center", fontsize=10, color=INK2)
    ax.scatter([8], [98.5], marker="o", s=40, facecolor=MAKE, edgecolor="white")
    ax.text(12, 98.5, "Make", fontsize=8.5, va="center", color=INK2)
    ax.scatter([8], [95.5], marker="x", s=40, color=MISS, linewidths=1.6)
    ax.text(12, 95.5, "Miss", fontsize=8.5, va="center", color=INK2)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------- hexbin --
# Red -> pale -> green diverging heat scale, same red/green as the Make/Miss
# dots elsewhere, for a continuous (edge-to-edge, "co-joined") hex mosaic
# instead of separate variable-sized markers.
SHOT_HEAT_CMAP = mcolors.LinearSegmentedColormap.from_list(
    "shot_heat", [MISS, "#f7f2e4", MAKE]
)
SHOT_HEAT_LO, SHOT_HEAT_HI = 0.15, 0.65  # make-rate mapped across the red->green ramp


def _draw_shot_hexbin(ax, shots, gridsize=20):
    """A true co-joined hex heatmap: every cell in the shot area is the same
    size and touches its neighbours (matplotlib's native hexbin mosaic,
    left untouched rather than redrawn as separate markers), coloured red
    -> green by that cell's make rate. Cells built from very few shots fade
    toward transparent instead of shouting as loud as well-sampled ones."""
    if not shots:
        return
    px = [_top(s["x"], s["y"])[0] for s in shots]
    py = [_top(s["x"], s["y"])[1] for s in shots]
    made = [s["made"] or 0 for s in shots]
    extent = (0, 100, 50, 100)

    hb_n = ax.hexbin(px, py, gridsize=gridsize, extent=extent, mincnt=1)
    counts = hb_n.get_array()
    hb_n.remove()
    if len(counts) == 0:
        return

    # zorder sits BELOW the court line art (drawn at zorder 2-4 in
    # _draw_court_lines) so the 3PT line, paint outline etc. stay crisp on
    # top of the heat instead of getting muddied under it -- the clearest
    # possible cue for which side of the arc (2PT vs 3PT) a cell is on.
    hb = ax.hexbin(px, py, C=made, gridsize=gridsize, extent=extent, mincnt=1,
                    reduce_C_function=np.mean, cmap=SHOT_HEAT_CMAP,
                    vmin=SHOT_HEAT_LO, vmax=SHOT_HEAT_HI, linewidths=0, zorder=1.5)
    max_count = max(counts.max(), 1)
    alpha = 0.35 + 0.6 * np.minimum(1.0, counts / max(4.0, max_count * 0.5))
    hb.set_alpha(alpha)


def _shot_hexbin_legend(ax):
    ax.text(6, 63, "COLD (MISSES)", fontsize=7.5, color=INK2, ha="left")
    ax.text(38, 63, "HOT (MAKES)", fontsize=7.5, color=INK2, ha="right")
    n = 30
    for i in range(n):
        t = i / (n - 1)
        cx = 8 + i * ((36 - 8) / (n - 1))
        ax.add_patch(RegularPolygon((cx, 59), numVertices=6, radius=0.85, orientation=0,
                                     facecolor=SHOT_HEAT_CMAP(t), edgecolor="none"))
    ax.text(6, 54, "Faint = few shots taken from that spot", fontsize=7.5, color=INK2, ha="left")


def _render_hexmap(title, subtitle, shots):
    fig = plt.figure(figsize=(6.2, 6.9))
    fig.text(0.5, 0.975, title, fontsize=14, fontweight="bold", ha="center", color=INK)
    fig.text(0.5, 0.94, subtitle, fontsize=10.5, ha="center", color=INK2)
    ax = fig.add_axes([0.06, 0.08, 0.88, 0.82])
    _draw_court(ax)
    _draw_shot_hexbin(ax, shots)
    _shot_hexbin_legend(ax)
    twos = [s for s in shots if s["action_type"] == "2pt"]
    threes = [s for s in shots if s["action_type"] == "3pt"]
    ax.text(50, 45, f"2PT: {_fg_str(twos)}    3PT: {_fg_str(threes)}",
            ha="center", fontsize=10, color=INK2)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def render_team_shotchart(team_id: int) -> bytes:
    conn = db.get_conn()
    team = conn.execute("SELECT name FROM teams WHERE id = ?", (team_id,)).fetchone()
    rows = conn.execute(
        "SELECT x, y, made, action_type FROM shots WHERE team_id = ?", (team_id,)
    ).fetchall()
    games = conn.execute(
        "SELECT COUNT(*) c FROM team_game_stats WHERE team_id = ?", (team_id,)
    ).fetchone()["c"]
    conn.close()
    name = team["name"] if team else f"Team {team_id}"
    return _render_hexmap(name, f"Season shot chart — {games} game(s)", _mirror(rows))


def render_player_shotchart(player_id: int) -> bytes:
    conn = db.get_conn()
    player = conn.execute(
        "SELECT p.name, t.name AS team FROM players p JOIN teams t ON t.id=p.team_id WHERE p.id = ?",
        (player_id,),
    ).fetchone()
    rows = conn.execute(
        "SELECT x, y, made, action_type FROM shots WHERE player_id = ?", (player_id,)
    ).fetchall()
    games = conn.execute(
        "SELECT COUNT(DISTINCT game_id) c FROM player_game_stats WHERE player_id = ?", (player_id,)
    ).fetchone()["c"]
    conn.close()
    name = player["name"] if player else f"Player {player_id}"
    team = player["team"] if player else ""
    return _render_hexmap(name, f"{team} — season shot chart — {games} game(s)", _mirror(rows))


# ---------------------------------------------------------- zone map ----
def _radial_point(theta_deg, side, r, from_r=0.0):
    """Point at radius r (measured from `from_r` outward along the ray),
    angle theta_deg (0=corner/along baseline, 90=top of key), on the given
    side, pivoting from the hoop -- in TOP-drawing coordinates."""
    theta = math.radians(theta_deg)
    dx = r * math.sin(theta)
    dy = r * math.cos(theta)
    plot_y = 100 - dx
    plot_x = 50 - dy if side == "L" else 50 + dy
    return plot_x, plot_y


def _ray_arc_exit_r(theta_deg, side, r_max=90.0, step=0.25):
    """Walk outward along a (baseline-pivoted) ray until it first leaves the
    elliptical 3PT boundary, so the angular divider lines can start right at
    the arc instead of cutting across the 2PT zones inside it."""
    theta = math.radians(theta_deg)
    r = 0.0
    while r < r_max:
        r += step
        dx = r * math.sin(theta)
        dy = r * math.cos(theta)
        plot_y = 100 - dx
        plot_x = 50 - dy if side == "L" else 50 + dy
        ox, oy = plot_y, plot_x  # inverse of _top()
        ellipse = ((ox - HOOP[0]) / ARC_R_D) ** 2 + ((oy - HOOP[1]) / ARC_R_W) ** 2
        if ellipse > 1.0:
            return r
    return r_max


def _draw_zone_guides(ax):
    lw = 1.4
    # short-corner / mid-range split: a band at SHORT_CORNER_DEPTH out from
    # the baseline, running from the lane edge out toward the wing.
    y_split = 100 - zonemod.SHORT_CORNER_DEPTH
    ax.plot([15, 33], [y_split, y_split], color=DIVIDER_WHITE, lw=lw, zorder=5)
    ax.plot([67, 85], [y_split, y_split], color=DIVIDER_WHITE, lw=lw, zorder=5)
    # 3PT angular boundaries (corner/wing, wing/top) -- 3PT territory only,
    # starting right at the arc rather than cutting across the 2PT zones.
    for theta in (22.5, 67.5):
        for side in ("L", "R"):
            r0 = _ray_arc_exit_r(theta, side)
            x0, y0 = _radial_point(theta, side, r0)
            x1, y1 = _radial_point(theta, side, 90)
            ax.plot([x0, x1], [y0, y1], color=DIVIDER_WHITE, lw=lw, zorder=5)


def _pill(ax, x, y, text, fontsize=8.6, facecolor=LABEL_BG, textcolor=INK):
    ax.text(x, y, text, ha="center", va="center", fontsize=fontsize, fontweight="bold",
            color=textcolor, zorder=8,
            bbox=dict(boxstyle="round,pad=0.28", facecolor=facecolor, edgecolor="none", alpha=0.96))


# Region shading: relative to this team/player's OWN overall 2PT% and 3PT%
# (2PT and 3PT are judged against separate baselines, since they naturally
# shoot at very different rates) -- green for at/above that average (graded
# by how far above), light red for below it, and full red for the single
# worst zone within each group.
ZONE_2PT = {"paint", "short_corner_L", "short_corner_R", "mid_L", "mid_R"}
ZONE_3PT = {"corner_3_L", "corner_3_R", "wing_3_L", "wing_3_R", "top_3"}
GREEN_CMAP = cm.get_cmap("Greens")
GREEN_SPAN = 20.0       # pct points above average that reach full-strength green
LIGHT_RED = "#f2a6a2"   # below average, but not the worst
WORST_RED = "#c81e1e"   # the single coldest zone in its group (matches RANK_RED)
ZONE_NEUTRAL = "#e4e4de"  # no attempts in that zone yet


def _zone_group_stats(agg, defense=False):
    """Weighted overall pct + the single worst zone, computed separately for
    the 2PT zones and the 3PT zones. In defense mode "worst" means the zone
    opponents shoot the BEST from (highest pct allowed), the mirror image of
    the offensive reading."""
    def stats_for(keys):
        tot_m = tot_a = 0
        pcts = {}
        for k in keys:
            row = agg[k]["overall"]
            tot_m += row["m"]
            tot_a += row["a"]
            p = zonemod.pct(row["m"], row["a"])
            if p is not None:
                pcts[k] = p
        avg = (tot_m / tot_a * 100) if tot_a else None
        worst = (max(pcts, key=pcts.get) if defense else min(pcts, key=pcts.get)) if pcts else None
        return avg, worst

    return {"2pt": stats_for(ZONE_2PT), "3pt": stats_for(ZONE_3PT)}


def _zone_relative_color(zone_key, pct, group_stats, defense=False, alpha=0.8):
    """Offense: green = shoots at/above its own average from that zone.
    Defense: green = HOLDS opponents to at/below average from that zone --
    lower opponent FG% is the good outcome, so the comparison flips."""
    if pct is None:
        return mcolors.to_rgba(ZONE_NEUTRAL, alpha)
    avg, worst = group_stats["3pt"] if zone_key in ZONE_3PT else group_stats["2pt"]
    if zone_key == worst:
        return mcolors.to_rgba(WORST_RED, alpha)
    if avg is None:
        return mcolors.to_rgba(LIGHT_RED, alpha)
    good = (pct <= avg) if defense else (pct >= avg)
    if good:
        t = max(0.0, min(1.0, abs(pct - avg) / GREEN_SPAN))
        return GREEN_CMAP(0.30 + 0.60 * t)[:3] + (alpha,)
    return mcolors.to_rgba(LIGHT_RED, alpha)


def _zone_masks(n=320):
    """Classify every point of an n x n raster covering the court (TOP-plot
    coordinates) into one of the 10 zone keys -- geometry-only (elliptical
    ARC_R_W/ARC_R_D boundary), matching zones.zone_for's own thresholds, so
    fills/centroids always line up exactly with the drawn court lines."""
    plot_xs = np.linspace(0, 100, n)
    plot_ys = np.linspace(50, 100, n)
    PX, PY = np.meshgrid(plot_xs, plot_ys)  # PX=plot_x (cols), PY=plot_y (rows)
    OX, OY = PY, PX  # inverse of _top(): orig_x = plot_y, orig_y = plot_x

    dx = 100.0 - OX  # depth from baseline
    dy = OY - 50.0   # signed width offset
    ellipse = ((OX - HOOP[0]) / ARC_R_D) ** 2 + ((OY - HOOP[1]) / ARC_R_W) ** 2
    theta = np.degrees(np.arctan2(dx, np.abs(dy) + 1e-9))
    side_l = dy < 0

    inside_arc = ellipse <= 1.0
    is_paint = inside_arc & (dx <= zonemod.LANE_DEPTH) & (np.abs(dy) <= zonemod.LANE_HALF_WIDTH)
    is_short = inside_arc & ~is_paint & (dx <= zonemod.SHORT_CORNER_DEPTH)
    is_mid = inside_arc & ~is_paint & ~is_short
    is_top3 = ~inside_arc & (theta >= 67.5)
    is_wing3 = ~inside_arc & (theta >= 22.5) & (theta < 67.5)
    is_corner3 = ~inside_arc & (theta < 22.5)

    masks = {
        "paint": is_paint,
        "short_corner_L": is_short & side_l, "short_corner_R": is_short & ~side_l,
        "mid_L": is_mid & side_l, "mid_R": is_mid & ~side_l,
        "corner_3_L": is_corner3 & side_l, "corner_3_R": is_corner3 & ~side_l,
        "wing_3_L": is_wing3 & side_l, "wing_3_R": is_wing3 & ~side_l,
        "top_3": is_top3,
    }
    return PX, PY, masks


def _zone_centroids(masks, PX, PY):
    """Centre-of-mass point (in TOP-plot coordinates) of each zone's actual
    rasterised shape, so labels always land inside their own region no
    matter how the arc/zone geometry changes."""
    out = {}
    for zone_key, mask in masks.items():
        if mask.any():
            out[zone_key] = (float(PX[mask].mean()), float(PY[mask].mean()))
        else:
            out[zone_key] = (50.0, 75.0)
    return out


def _draw_zone_fills(ax, masks, colors, PX, PY, n):
    """Paint each of the 10 zone regions with its own colour, rasterised so
    the fill boundaries always line up exactly with the drawn arc/paint/
    short-corner lines. Drawn before the line art so the black lines render
    cleanly on top."""
    img = np.empty((n, n, 4))
    img[...] = mcolors.to_rgba(SURFACE)
    for zone_key, mask in masks.items():
        img[mask] = colors[zone_key]

    im = ax.imshow(img, extent=(0, 100, 50, 100), origin="lower", zorder=0.4, aspect="auto")
    clip_shape = FancyBboxPatch((0, 50), 100, 50, boxstyle="round,pad=0,rounding_size=3",
                                 transform=ax.transData)
    im.set_clip_path(clip_shape)


MIN_ZONE_ATTEMPTS = {"team": 15, "player": 5}


def _entity_zone_ma(rows, id_col):
    """rows: sqlite Rows with id_col, x, y, made, action_type (every shot,
    every entity). Returns {entity_id: {zone_key: {'m':.., 'a':..}}}."""
    out = {}
    for r in rows:
        if r["action_type"] not in ("2pt", "3pt") or r["x"] is None or r["y"] is None:
            continue
        eid = r[id_col]
        if eid is None:
            continue
        zone = zonemod.zone_for(r["x"], r["y"], r["action_type"])
        entry = out.setdefault(eid, {z: {"m": 0, "a": 0} for z in zonemod.ZONE_ORDER})[zone]
        entry["a"] += 1
        entry["m"] += r["made"] or 0
    return out


def _league_zone_ranks(entity, target_id, defense=False):
    """Rank target_id's FG% in each zone against every OTHER team (if
    entity='team') or every other PLAYER (if entity='player') league-wide --
    teams are only ever compared to teams, players only ever to players --
    so a player's chart can never read as a reshuffled team ranking.
    In defense mode, ranks each team's OPPONENTS' shooting in that zone
    (lower allowed FG% = rank #1, the best defense), never mixed with the
    offensive rankings. Returns {zone_key: (rank, pool_size)}; rank is None
    if target_id didn't meet the minimum-attempts bar for that zone."""
    id_col = "team_id" if entity == "team" else "player_id"
    min_a = MIN_ZONE_ATTEMPTS[entity]
    conn = db.get_conn()
    if defense:
        rows = conn.execute(
            """
            SELECT CASE WHEN s.team_id = g.team1_id THEN g.team2_id ELSE g.team1_id END AS team_id,
                   s.x, s.y, s.made, s.action_type
            FROM shots s JOIN games g ON g.id = s.game_id
            """
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {id_col}, x, y, made, action_type FROM shots WHERE {id_col} IS NOT NULL"
        ).fetchall()
    conn.close()
    per_entity = _entity_zone_ma(rows, id_col)

    out = {}
    for zone in zonemod.ZONE_ORDER:
        entries = [
            (eid, zonemod.pct(zma[zone]["m"], zma[zone]["a"]))
            for eid, zma in per_entity.items() if zma[zone]["a"] >= min_a
        ]
        entries.sort(key=lambda kv: kv[1], reverse=not defense)
        pool = len(entries)
        rank = next((i for i, (eid, _) in enumerate(entries, 1) if eid == target_id), None)
        out[zone] = (rank, pool)
    return out


def _draw_zone_map(ax, agg, entity, target_id, defense=False):
    ax.set_facecolor(SURFACE)

    def pct_of(zone_key):
        row = agg[zone_key]["overall"]
        return zonemod.pct(row["m"], row["a"])

    n = 320
    PX, PY, masks = _zone_masks(n)
    group_stats = _zone_group_stats(agg, defense)
    colors = {z: _zone_relative_color(z, pct_of(z), group_stats, defense) for z in zonemod.ZONE_ORDER}
    centroids = _zone_centroids(masks, PX, PY)
    ranks = _league_zone_ranks(entity, target_id, defense)

    _draw_zone_fills(ax, masks, colors, PX, PY, n)
    _draw_court_lines(ax)
    ax.set_xlim(-2, 102)
    ax.set_ylim(48, 102)
    ax.set_aspect(28.0 / 15.0)
    ax.axis("off")
    _draw_zone_guides(ax)

    for zone_key in zonemod.ZONE_ORDER:
        overall = agg[zone_key]["overall"]
        m, a = overall["m"], overall["a"]
        p = zonemod.pct(m, a)
        x, y = centroids[zone_key]
        _pill(ax, x, y + 3.1, f"{m}/{a}" if a else "0/0", fontsize=8.0)
        _pill(ax, x, y, f"{p:.1f}%" if p is not None else "—", fontsize=8.0)
        rank, pool = ranks.get(zone_key, (None, 0))
        label = f"#{rank}/{pool} {'teams' if entity == 'team' else 'players'}" if rank else "—"
        _pill(ax, x, y - 3.1, label, fontsize=7.6, textcolor=WORST_RED)


def _render_zonemap(title, subtitle, shot_rows, entity, target_id, defense=False):
    agg = zonemod.aggregate_zones(shot_rows)
    fig = plt.figure(figsize=(6.6, 6.9))
    fig.text(0.5, 0.975, title, fontsize=14, fontweight="bold", ha="center", color=INK)
    fig.text(0.5, 0.94, subtitle, fontsize=10.5, ha="center", color=INK2)
    ax = fig.add_axes([0.05, 0.05, 0.90, 0.84])
    _draw_zone_map(ax, agg, entity, target_id, defense)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def render_team_zonemap(team_id: int) -> bytes:
    conn = db.get_conn()
    team = conn.execute("SELECT name FROM teams WHERE id = ?", (team_id,)).fetchone()
    rows = conn.execute(
        "SELECT x, y, made, action_type, shot_clock_used FROM shots WHERE team_id = ?", (team_id,)
    ).fetchall()
    games = conn.execute(
        "SELECT COUNT(*) c FROM team_game_stats WHERE team_id = ?", (team_id,)
    ).fetchone()["c"]
    conn.close()
    name = team["name"] if team else f"Team {team_id}"
    return _render_zonemap(name, f"Season zone breakdown — {games} game(s)", rows, "team", team_id)


# Opponent shots in every game this team played -- "defense" numbers.
_AGAINST_SHOTS_SQL = """
    SELECT s.x, s.y, s.made, s.action_type, s.shot_clock_used
    FROM shots s JOIN games g ON g.id = s.game_id
    WHERE (g.team1_id = ? OR g.team2_id = ?) AND s.team_id != ?
"""


def render_team_shotchart_against(team_id: int) -> bytes:
    conn = db.get_conn()
    team = conn.execute("SELECT name FROM teams WHERE id = ?", (team_id,)).fetchone()
    rows = conn.execute(_AGAINST_SHOTS_SQL, (team_id, team_id, team_id)).fetchall()
    games = conn.execute(
        "SELECT COUNT(*) c FROM team_game_stats WHERE team_id = ?", (team_id,)
    ).fetchone()["c"]
    conn.close()
    name = team["name"] if team else f"Team {team_id}"
    return _render_hexmap(f"{name} — Opponents", f"Shots allowed — {games} game(s)", _mirror(rows))


def render_team_zonemap_against(team_id: int) -> bytes:
    conn = db.get_conn()
    team = conn.execute("SELECT name FROM teams WHERE id = ?", (team_id,)).fetchone()
    rows = conn.execute(_AGAINST_SHOTS_SQL, (team_id, team_id, team_id)).fetchall()
    games = conn.execute(
        "SELECT COUNT(*) c FROM team_game_stats WHERE team_id = ?", (team_id,)
    ).fetchone()["c"]
    conn.close()
    name = team["name"] if team else f"Team {team_id}"
    return _render_zonemap(f"{name} — Opponents", f"Shots allowed — {games} game(s)",
                            rows, "team", team_id, defense=True)


def render_player_zonemap(player_id: int) -> bytes:
    conn = db.get_conn()
    player = conn.execute(
        "SELECT p.name, t.name AS team FROM players p JOIN teams t ON t.id=p.team_id WHERE p.id = ?",
        (player_id,),
    ).fetchone()
    rows = conn.execute(
        "SELECT x, y, made, action_type, shot_clock_used FROM shots WHERE player_id = ?", (player_id,)
    ).fetchall()
    games = conn.execute(
        "SELECT COUNT(DISTINCT game_id) c FROM player_game_stats WHERE player_id = ?", (player_id,)
    ).fetchone()["c"]
    conn.close()
    name = player["name"] if player else f"Player {player_id}"
    team = player["team"] if player else ""
    return _render_zonemap(name, f"{team} — season zone breakdown — {games} game(s)", rows, "player", player_id)
