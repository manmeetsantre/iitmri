"""
Pulls POI (points of interest) data for the 5 cities from OpenStreetMap's free
Overpass API -- no API key or account needed. Saves osm_poi_raw.csv in this
folder: one row per POI with city, category, name, latitude, longitude, osm id.

Categories pulled (OSM tag -> our category label):
    shop=mall                -> mall
    tourism=attraction       -> attraction
    tourism=museum           -> museum
    tourism=zoo              -> zoo
    tourism=theme_park       -> theme_park
    leisure=stadium          -> stadium
    amenity=university       -> university
    leisure=park (named only)-> park   (unnamed parks are tiny green patches; skipped)

Notes / known limitations (disclosed, same standard as previous variables):
  - OSM is crowd-sourced (volunteer-mapped, like Wikipedia for maps). Coverage in
    big US cities is good but not guaranteed complete, and the "attraction" tag is
    loose -- it includes small items (murals, memorial aircraft) alongside major
    tourist spots. Filter by category when building model variables.
  - For area features (a mall building, a park polygon) the API returns the
    geometric center point ("out center") as its lat/lon.
  - City boundary = the city's official municipal boundary in OSM
    (admin_level=8 area with that name).
  - The Overpass public server is fair-use rate-limited; this script runs one
    combined query per city with pauses, and retries on failure.
"""
import csv
import json
import time
import urllib.parse
import urllib.request

OUT_ROOT = "/Users/MANMEETSANTRE/Downloads/restaurant-agglomeration-main/new_variables"
CITIES = ["Tucson", "Tampa", "Indianapolis", "Nashville", "Philadelphia"]

# (overpass selector, our category label)
CATEGORIES = [
    ('["shop"="mall"]', "mall"),
    ('["tourism"="attraction"]', "attraction"),
    ('["tourism"="museum"]', "museum"),
    ('["tourism"="zoo"]', "zoo"),
    ('["tourism"="theme_park"]', "theme_park"),
    ('["leisure"="stadium"]', "stadium"),
    ('["amenity"="university"]', "university"),
    ('["leisure"="park"]["name"]', "park"),
]


def overpass(query, retries=3):
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(
        "https://overpass-api.de/api/interpreter", data=data,
        headers={"User-Agent": "restaurant-research-project/1.0"},
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"    retry after error: {str(e)[:100]}")
            time.sleep(15)


def build_query(city):
    parts = []
    for sel, _ in CATEGORIES:
        parts.append(f'node{sel}(area.a);')
        parts.append(f'way{sel}(area.a);')
        parts.append(f'relation{sel}(area.a);')
    body = "".join(parts)
    return (f'[out:json][timeout:120];'
            f'area["name"="{city}"]["admin_level"="8"]->.a;'
            f'({body});out center tags;')


def categorize(tags):
    if tags.get("shop") == "mall":
        return "mall"
    t = tags.get("tourism")
    if t in ("attraction", "museum", "zoo", "theme_park"):
        return t
    if tags.get("leisure") == "stadium":
        return "stadium"
    if tags.get("amenity") == "university":
        return "university"
    if tags.get("leisure") == "park" and tags.get("name"):
        return "park"
    return None


def main():
    rows = []
    for city in CITIES:
        print(f"==== {city} ====")
        res = overpass(build_query(city))
        n_before = len(rows)
        for el in res.get("elements", []):
            tags = el.get("tags", {})
            cat = categorize(tags)
            if cat is None:
                continue
            if "lat" in el:                     # node: has its own coordinates
                lat, lon = el["lat"], el["lon"]
            elif "center" in el:                # way/relation: use geometric center
                lat, lon = el["center"]["lat"], el["center"]["lon"]
            else:
                continue
            rows.append({
                "city": city,
                "category": cat,
                "name": tags.get("name", ""),
                "latitude": lat,
                "longitude": lon,
                "osm_type": el["type"],
                "osm_id": el["id"],
            })
        by_cat = {}
        for r in rows[n_before:]:
            by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
        print(f"  {len(rows) - n_before} POIs: {by_cat}")
        time.sleep(5)  # be polite to the free public server

    out_path = f"{OUT_ROOT}/osm_poi_raw.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["city", "category", "name", "latitude", "longitude", "osm_type", "osm_id"])
        w.writeheader()
        w.writerows(rows)
    print(f"\nSaved {len(rows)} POIs to {out_path}")
    print("DONE")


if __name__ == "__main__":
    main()
