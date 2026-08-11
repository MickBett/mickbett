"""Search outward from a known-good CEBL match id to find how far the CEBL
season's ids extend in each direction, by sampling every Nth id and checking
team names."""
import sys, json
sys.path.insert(0, "/Users/mickbett/season-tracker")
from app.fetcher import fetch_game_json, FetchError

ANCHOR = 2798835
CEBL_KEYWORDS = [
    "Honey Badgers", "Surge", "Stingers", "Alliance", "River Lions",
    "BlackJacks", "Black Jacks", "Mamba", "Shooting Stars", "Bandits",
    "Sea Bears", "Rattlers", "Rattler",
]

def check(mid):
    try:
        raw, _ = fetch_game_json(str(mid))
        data = json.loads(raw.decode("utf-8-sig"))
        n1 = data["tm"]["1"]["name"]
        n2 = data["tm"]["2"]["name"]
        is_cebl = any(k in n1 for k in CEBL_KEYWORDS) or any(k in n2 for k in CEBL_KEYWORDS)
        return f"{'CEBL' if is_cebl else 'other'}: {n1} vs {n2}"
    except FetchError as e:
        return f"error: {e}"
    except Exception as e:
        return f"error: {e}"

# sample every 50 ids, 1000 in each direction from the anchor
for offset in [-1000, -700, -500, -300, -150, -50, 0, 50, 150, 300, 500, 700, 1000]:
    mid = ANCHOR + offset
    print(f"{mid:>10} ({offset:+6}): {check(mid)}")
