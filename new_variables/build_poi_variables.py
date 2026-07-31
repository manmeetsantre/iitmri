"""
Builds two restaurant-level POI variables from osm_poi_raw.csv and merges them
onto all 6 prepared datasets:

    dist_nearest_mall    -- distance in meters from the restaurant to the
                            closest mall in its city (straight-line/haversine).
    n_tourist_spots_1km  -- number of tourist POIs (attraction + museum + zoo +
                            theme_park) within 1000m of the restaurant.

Method:
  1. Restaurant coordinates come from the raw business_<City>.RData files
     (latitude/longitude, present for every restaurant including food trucks).
  2. POI coordinates come from osm_poi_raw.csv (pulled by pull_osm_poi.py from
     OpenStreetMap's free Overpass API).
  3. For each city, compute the haversine distance matrix restaurants x POIs
     (Earth radius 6,371,000 m -- same constant as the heterogeneity scripts).
  4. dist_nearest_mall = min distance to any mall in the same city.
     n_tourist_spots_1km = count of tourist POIs at distance <= 1000 m.
  5. Merge onto the 6 datasets by business_id (both variables are static,
     one value per restaurant, repeated across its weekly rows).

Notes / disclosed limitations:
  - "Tourist spots" = OSM categories attraction, museum, zoo, theme_park.
    The park/stadium/university/mall categories are NOT counted as tourist
    spots (parks dominate the POI file and would swamp the count; malls are
    already covered by their own variable).
  - Distances are straight-line, not walking/driving distance.
  - POIs outside the city's municipal boundary are not in the reference file,
    so a mall just across the city line is invisible to dist_nearest_mall --
    values near the city edge can be overestimates.
  - The OSM "attraction" tag includes some minor items (murals etc.), so
    n_tourist_spots_1km counts small attractions alongside major ones.
"""
import numpy as np
import pandas as pd
import pyreadr
import rdata

SRC_ROOT = "/Users/MANMEETSANTRE/Desktop/restaurantri/YelpJSON"
OUT_ROOT = "/Users/MANMEETSANTRE/Downloads/restaurant-agglomeration-main/new_variables"
CITIES = ["Tucson", "Tampa", "Indianapolis", "Nashville", "Philadelphia"]

EARTH_RADIUS_M = 6371000.0
TOURIST_CATS = {"attraction", "museum", "zoo", "theme_park"}
RADIUS_M = 1000.0

NEW_COLS = ["dist_nearest_mall", "n_tourist_spots_1km"]


def haversine_cross(lat1, lon1, lat2, lon2):
    """Distance matrix (meters) between two point sets: len(lat1) x len(lat2)."""
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
        city_poi = poi[poi["city"] == city]
        malls = city_poi[city_poi["category"] == "mall"]
        tourist = city_poi[city_poi["category"].isin(TOURIST_CATS)]

        d_mall = haversine_cross(rest["latitude"].to_numpy(), rest["longitude"].to_numpy(),
                                 malls["latitude"].to_numpy(), malls["longitude"].to_numpy())
        d_tour = haversine_cross(rest["latitude"].to_numpy(), rest["longitude"].to_numpy(),
                                 tourist["latitude"].to_numpy(), tourist["longitude"].to_numpy())

        rest["dist_nearest_mall"] = d_mall.min(axis=1).round(1)
        rest["n_tourist_spots_1km"] = (d_tour <= RADIUS_M).sum(axis=1).astype(int)

        print(f"{city}: {len(rest)} restaurants | {len(malls)} malls, {len(tourist)} tourist POIs | "
              f"dist_nearest_mall median={rest['dist_nearest_mall'].median():.0f}m | "
              f"n_tourist_spots_1km mean={rest['n_tourist_spots_1km'].mean():.2f} max={rest['n_tourist_spots_1km'].max()}")
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
        for c in NEW_COLS:
            assert t_data[c].isna().sum() == 0, f"NAs introduced in {c}"
        assert t_data.duplicated(subset=["business_id", "week"]).sum() == 0, "duplicates introduced!"

        print(f"  rows: {len(t_data)}, cols: {len(t_data.columns)}, "
              f"dist_nearest_mall range: {t_data['dist_nearest_mall'].min():.0f}-{t_data['dist_nearest_mall'].max():.0f}m, "
              f"n_tourist_spots_1km range: {t_data['n_tourist_spots_1km'].min()}-{t_data['n_tourist_spots_1km'].max()}")

        t_data.to_csv(csv_path, index=False)
        pyreadr.write_rdata(rdata_path, t_data, df_name="t_data", compress="gzip")
        print(f"  saved {csv_path}")

    print("\nDONE")


if __name__ == "__main__":
    main()
