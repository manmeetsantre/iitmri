"""
Builds per-category POI count variables (how many malls / museums / attractions /
parks / universities / stadiums are within 1000 m of each restaurant), a total POI
count, and one neighbor-restaurant aggregate. Merges all onto the 6 datasets.

New columns (8):
    n_malls_1km          -- # of shop=mall POIs within 1000 m
    n_museums_1km        -- # of tourism=museum POIs within 1000 m
    n_attractions_1km    -- # of tourism=attraction POIs within 1000 m
    n_parks_1km          -- # of named leisure=park POIs within 1000 m
    n_universities_1km   -- # of amenity=university POIs within 1000 m
    n_stadiums_1km       -- # of leisure=stadium POIs within 1000 m
    n_poi_1km            -- # of POIs of ANY of the 8 categories within 1000 m
                            (the six above + zoo + theme_park)
    avg_neigh_n_poi_1km  -- mean n_poi_1km over this restaurant's NEIGHBOURING
                            restaurants (other restaurants within 1000 m, self
                            excluded). NaN if the restaurant has no neighbours.

Method (same conventions as the earlier spatial variables):
  - Restaurant coordinates from raw business_<City>.RData (every restaurant has
    lat/lon, including food trucks).
  - POI coordinates from osm_poi_raw.csv (OpenStreetMap Overpass pull).
  - Haversine distances, Earth radius 6,371,000 m.
  - 1000 m radius, matching the neighbor/cluster radius used elsewhere.
  - Counts are computed per city (POIs are only known inside each city boundary).

Disclosed limitations:
  - Straight-line distance, not walking distance.
  - POIs limited to each city's municipal boundary; a POI just across the city
    line is invisible, so counts near the city edge can be slight underestimates.
  - OSM is crowd-sourced; the attraction tag is loose (murals etc. count).
  - POIs are the current (2026) OSM snapshot applied to all panel years.
  - avg_neigh_n_poi_1km is NaN for restaurants with no neighbour within 1000 m
    (genuinely undefined -- there are no neighbours to average). This is a small
    number of isolated restaurants per city; left blank, not fabricated.
"""
import numpy as np
import pandas as pd
import pyreadr
import rdata

SRC_ROOT = "/Users/MANMEETSANTRE/Desktop/restaurantri/YelpJSON"
OUT_ROOT = "/Users/MANMEETSANTRE/Downloads/restaurant-agglomeration-main/new_variables"
CITIES = ["Tucson", "Tampa", "Indianapolis", "Nashville", "Philadelphia"]

EARTH_RADIUS_M = 6371000.0
RADIUS_M = 1000.0

# per-category count columns -> the osm category label they count
COUNT_CATS = {
    "n_malls_1km": "mall",
    "n_museums_1km": "museum",
    "n_attractions_1km": "attraction",
    "n_parks_1km": "park",
    "n_universities_1km": "university",
    "n_stadiums_1km": "stadium",
}
NEW_COLS = list(COUNT_CATS.keys()) + ["n_poi_1km", "avg_neigh_n_poi_1km"]


def haversine_cross(lat1, lon1, lat2, lon2):
    """Distance matrix (m) between two point sets: len(lat1) x len(lat2)."""
    la1, lo1 = np.radians(lat1)[:, None], np.radians(lon1)[:, None]
    la2, lo2 = np.radians(lat2)[None, :], np.radians(lon2)[None, :]
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return EARTH_RADIUS_M * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def load_restaurants(city):
    parsed = rdata.parser.parse_file(f"{SRC_ROOT}/business_{city}.RData")
    conv = rdata.conversion.convert(parsed, constructor_dict={})
    obj = conv["bus_res_city"]
    return pd.DataFrame({
        "business_id": obj["business_id"],
        "latitude": obj["latitude"].astype(float),
        "longitude": obj["longitude"].astype(float),
    })


def main():
    poi = pd.read_csv(f"{OUT_ROOT}/osm_poi_raw.csv")

    lookups = []
    for city in CITIES:
        rest = load_restaurants(city)
        rlat, rlon = rest["latitude"].to_numpy(), rest["longitude"].to_numpy()
        city_poi = poi[poi["city"] == city]

        # per-category counts within 1000 m
        for col, cat in COUNT_CATS.items():
            cp = city_poi[city_poi["category"] == cat]
            if len(cp):
                d = haversine_cross(rlat, rlon, cp["latitude"].to_numpy(), cp["longitude"].to_numpy())
                rest[col] = (d <= RADIUS_M).sum(axis=1).astype(int)
            else:
                rest[col] = 0

        # total POIs (all 8 categories) within 1000 m
        d_all = haversine_cross(rlat, rlon, city_poi["latitude"].to_numpy(), city_poi["longitude"].to_numpy())
        rest["n_poi_1km"] = (d_all <= RADIUS_M).sum(axis=1).astype(int)

        # neighbor aggregate: mean n_poi_1km over other restaurants within 1000 m
        d_rr = haversine_cross(rlat, rlon, rlat, rlon)
        neigh = (d_rr <= RADIUS_M)
        np.fill_diagonal(neigh, False)                 # exclude self
        n_neigh = neigh.sum(axis=1)
        npoi = rest["n_poi_1km"].to_numpy(dtype=float)
        neigh_sum = neigh @ npoi
        with np.errstate(invalid="ignore", divide="ignore"):
            avg = np.where(n_neigh > 0, neigh_sum / n_neigh, np.nan)
        rest["avg_neigh_n_poi_1km"] = np.round(avg, 3)

        n_isolated = int((n_neigh == 0).sum())
        print(f"{city}: {len(rest)} restaurants | n_poi_1km mean={rest['n_poi_1km'].mean():.2f} "
              f"max={rest['n_poi_1km'].max()} | isolated (no neighbour)={n_isolated}")
        for col in COUNT_CATS:
            print(f"    {col:22} mean={rest[col].mean():.2f} max={rest[col].max()}")
        lookups.append(rest[["business_id"] + NEW_COLS])

    lookup = pd.concat(lookups, ignore_index=True)

    for name in CITIES + ["AllCities_MERGED"]:
        print(f"\n==== {name} ====")
        csv_path = f"{OUT_ROOT}/LATEST_{name}_FULL_DATA.csv"
        rdata_path = f"{OUT_ROOT}/LATEST_t_data_{name}.RData"

        t_data = pd.read_csv(csv_path)
        before_n = len(t_data)
        before_cols = [c for c in t_data.columns if c not in NEW_COLS]
        t_data = t_data[before_cols]

        t_data = t_data.merge(lookup, on="business_id", how="left")

        assert len(t_data) == before_n, "row count changed!"
        assert list(t_data.columns) == before_cols + NEW_COLS, "column set changed unexpectedly"
        # count columns must have no NA (every restaurant matched); avg_neigh may have NA (isolated)
        for c in list(COUNT_CATS) + ["n_poi_1km"]:
            assert t_data[c].isna().sum() == 0, f"unexpected NAs in {c}"
        assert t_data.duplicated(subset=["business_id", "week"]).sum() == 0, "duplicates introduced!"

        n_avg_na = t_data["avg_neigh_n_poi_1km"].isna().sum()
        print(f"  rows: {len(t_data)}, cols: {len(t_data.columns)}, "
              f"avg_neigh_n_poi_1km NAs (isolated restaurants): {n_avg_na} ({100*n_avg_na/len(t_data):.2f}%)")

        t_data.to_csv(csv_path, index=False)
        pyreadr.write_rdata(rdata_path, t_data, df_name="t_data", compress="gzip")
        print(f"  saved {csv_path}")

    print("\nDONE")


if __name__ == "__main__":
    main()
