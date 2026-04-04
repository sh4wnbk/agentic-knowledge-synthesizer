import requests
import json
from config import OHIO_BBOX, OKLAHOMA_BBOX

def test_usgs_reach(name, bbox):
    url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    params = {
        "format": "geojson",
        "starttime": "2026-03-01", # Last 30 days
        "minmagnitude": "1.5",     # Lower threshold for testing
        "minlatitude": bbox["minlatitude"],
        "maxlatitude": bbox["maxlatitude"],
        "minlongitude": bbox["minlongitude"],
        "maxlongitude": bbox["maxlongitude"]
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    count = data.get("metadata", {}).get("count", 0)
    print(f"[VERIFY] {name}: Found {count} events at M1.5+")

test_usgs_reach("Ohio", OHIO_BBOX)
test_usgs_reach("Oklahoma", OKLAHOMA_BBOX)