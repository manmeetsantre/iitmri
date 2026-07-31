"""
Builds two families of variables and merges them onto all 6 datasets:

MULTI-SCALE AMENITY CATCHMENT (how much is nearby at a walk vs a drive):
    n_poi_500m   -- # of POIs (any of the 8 OSM categories) within 500 m
                    (the "walk-in" catchment -- who can stroll over)
    n_poi_3km    -- # of POIs within 3000 m
                    (the "drive-to" catchment -- the wider area people drive from)
  These bracket the existing n_poi_1km, so by construction
    n_poi_500m  <=  n_poi_1km  <=  n_poi_3km    (a nesting sanity check).

ANCHOR x COMPETITION (does a big demand-anchor cushion a restaurant against its
rivals?):
    near_mall        -- 1 if at least one mall within 1 km, else 0
    near_university  -- 1 if at least one university within 1 km, else 0
                        (derived from the existing n_malls_1km / n_universities_1km
                        counts, so "near" = same 1 km convention as the rest.)
    mall_competition_interaction        -- near_mall * num_neighbors
    university_competition_interaction  -- near_university * num_neighbors
  The interaction terms are the whole point: num_neighbors is the (time-varying)
  local competition, and the product lets a survival model test whether being next
  to an anchor changes how much competition hurts. num_neighbors varies week to week,
  so these interaction columns are time-varying even though the flags are static.

Only the two multi-scale counts need a spatial recompute (from osm_poi_raw.csv +
restaurant coordinates). The anchor flags and interactions are arithmetic on columns
that already exist in the datasets (n_malls_1km, n_universities_1km, num_neighbors).
"""
import numpy as np
import pandas as pd
import pyreadr
import rdata

SRC_ROOT = "/Users/MANMEETSANTRE/Desktop/restaurantri/YelpJSON"
OUT_ROOT = "/Users/MANMEETSANTRE/Downloads/restaurant-agglomeration-main/new_variables"
CITIES = ["Tucson", "Tampa", "Indianapolis", "Nashville", "Philadelphia"]

EARTH_RADIUS_M = 6371000.0

NEW_COLS = ["n_poi_500m", "n_poi_3km", "near_mall", "near_university",
            "mall_competition_interaction", "university_competition_interaction"]


def haversine_cross(lat1, lon1, lat2, lon2):
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


def build_multiscale_lookup(poi):
    frames = []
    for city in CITIES:
        rest = load_restaurants(city)
        rlat, rlon = rest["latitude"].to_numpy(), rest["longitude"].to_numpy()
        cp = poi[poi["city"] == city]
        d = haversine_cross(rlat, rlon, cp["latitude"].to_numpy(), cp["longitude"].to_numpy())
        rest["n_poi_500m"] = (d <= 500.0).sum(axis=1).astype(int)
        rest["n_poi_3km"] = (d <= 3000.0).sum(axis=1).astype(int)
        print(f"{city}: n_poi_500m mean={rest['n_poi_500m'].mean():.2f} | "
              f"n_poi_3km mean={rest['n_poi_3km'].mean():.2f}")
        frames.append(rest[["business_id", "n_poi_500m", "n_poi_3km"]])
    return pd.concat(frames, ignore_index=True)


def main():
    poi = pd.read_csv(f"{OUT_ROOT}/osm_poi_raw.csv")
    print("Building multi-scale POI counts...")
    ms = build_multiscale_lookup(poi)

    for name in CITIES + ["AllCities_MERGED"]:
        print(f"\n==== {name} ====")
        csv_path = f"{OUT_ROOT}/LATEST_{name}_FULL_DATA.csv"
        rdata_path = f"{OUT_ROOT}/LATEST_t_data_{name}.RData"

        t_data = pd.read_csv(csv_path)
        before_n = len(t_data)
        before_cols = [c for c in t_data.columns if c not in NEW_COLS]
        t_data = t_data[before_cols]

        # multi-scale counts (merge by business_id)
        t_data = t_data.merge(ms, on="business_id", how="left")
        # anchor flags from existing 1 km counts
        t_data["near_mall"] = (t_data["n_malls_1km"] >= 1).astype(int)
        t_data["near_university"] = (t_data["n_universities_1km"] >= 1).astype(int)
        # interactions with (time-varying) competition
        t_data["mall_competition_interaction"] = t_data["near_mall"] * t_data["num_neighbors"]
        t_data["university_competition_interaction"] = t_data["near_university"] * t_data["num_neighbors"]

        # reorder new cols to the documented order
        t_data = t_data[before_cols + NEW_COLS]

        assert len(t_data) == before_n, "row count changed!"
        assert list(t_data.columns) == before_cols + NEW_COLS, "column set changed unexpectedly"
        for c in NEW_COLS:
            assert t_data[c].isna().sum() == 0, f"unexpected NAs in {c}"
        # nesting sanity: 500m <= 1km <= 3km, every row
        assert (t_data["n_poi_500m"] <= t_data["n_poi_1km"]).all(), "n_poi_500m > n_poi_1km somewhere!"
        assert (t_data["n_poi_1km"] <= t_data["n_poi_3km"]).all(), "n_poi_1km > n_poi_3km somewhere!"
        assert t_data["near_mall"].isin([0, 1]).all() and t_data["near_university"].isin([0, 1]).all()
        assert t_data.duplicated(subset=["business_id", "week"]).sum() == 0, "duplicates introduced!"

        print(f"  rows: {len(t_data)}, cols: {len(t_data.columns)}, "
              f"near_mall={t_data['near_mall'].mean():.2%} near_university={t_data['near_university'].mean():.2%}")

        t_data.to_csv(csv_path, index=False)
        pyreadr.write_rdata(rdata_path, t_data, df_name="t_data", compress="gzip")
        print(f"  saved {csv_path}")

    print("\nDONE")


if __name__ == "__main__":
    main()
