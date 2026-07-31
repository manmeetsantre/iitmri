"""
Builds distance-decay ACCESSIBILITY variables (Hansen 1959 accessibility index)
and merges them onto all 6 datasets.

The idea: instead of counting POIs inside a hard 1000 m circle (where a place at
999 m counts as 1 and one at 1001 m counts as 0), each nearby place is given a
"closeness weight" that fades smoothly with distance:

        weight = exp( -distance / d0 )        with d0 = 1000 m

    distance   weight
        0 m     1.00
     1000 m     0.37
     2000 m     0.14
     3000 m     0.05

The accessibility score for a restaurant is the SUM of these weights over the
relevant set of places. Close places contribute a lot, far places fade toward 0,
and there is no arbitrary cutoff. This is the standard Hansen accessibility index
used in spatial economics / geography.

New columns (6), all static per restaurant (POIs are fixed; the restaurant set is
the full set of restaurants in the city -- a spatial density measure, NOT the
time-varying active competition, which is already captured by num_neighbors):

    amenity_access      -- sum of exp(-d/d0) over ALL POIs in the city
    mall_access         -- ... over shop=mall POIs
    university_access   -- ... over amenity=university POIs
    tourist_access      -- ... over tourism attraction+museum+zoo+theme_park POIs
    park_access         -- ... over named leisure=park POIs
    competition_access  -- ... over OTHER restaurants (self excluded)

Design choices (defensible, documented):
  - d0 = 1000 m: keeps these comparable to the existing 1 km count/neighbour
    variables and is a normal "walkable neighbourhood" scale.
  - Per-category accessibility (not one blended amenity score) so a regression can
    learn each category's own weight, instead of us hard-coding that a mall matters
    more than a park.
  - Earth radius 6,371,000 m (same haversine constant as the other spatial scripts).
  - competition_access uses ALL restaurants in the city (a static location-density
    measure). Time-varying active competition is a separate, existing variable
    (num_neighbors).

Limitations (same family as the other POI variables):
  - Straight-line distance, not walking/driving distance.
  - POIs limited to each city's municipal boundary (edge effects).
  - Current (2026) OSM snapshot applied to all panel years.
"""
import numpy as np
import pandas as pd
import pyreadr
import rdata

SRC_ROOT = "/Users/MANMEETSANTRE/Desktop/restaurantri/YelpJSON"
OUT_ROOT = "/Users/MANMEETSANTRE/Downloads/restaurant-agglomeration-main/new_variables"
CITIES = ["Tucson", "Tampa", "Indianapolis", "Nashville", "Philadelphia"]

EARTH_RADIUS_M = 6371000.0
D0 = 1000.0  # decay scale in metres

TOURIST_CATS = {"attraction", "museum", "zoo", "theme_park"}
NEW_COLS = ["amenity_access", "mall_access", "university_access",
            "tourist_access", "park_access", "competition_access"]


def haversine_cross(lat1, lon1, lat2, lon2):
    """Distance matrix (m) between two point sets: len(lat1) x len(lat2)."""
    la1, lo1 = np.radians(lat1)[:, None], np.radians(lon1)[:, None]
    la2, lo2 = np.radians(lat2)[None, :], np.radians(lon2)[None, :]
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return EARTH_RADIUS_M * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def access_to(rlat, rlon, plat, plon):
    """Sum of exp(-d/D0) from each restaurant to the given set of points."""
    if len(plat) == 0:
        return np.zeros(len(rlat))
    d = haversine_cross(rlat, rlon, plat, plon)
    return np.exp(-d / D0).sum(axis=1)


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
        cp = poi[poi["city"] == city]

        malls = cp[cp["category"] == "mall"]
        unis = cp[cp["category"] == "university"]
        tour = cp[cp["category"].isin(TOURIST_CATS)]
        parks = cp[cp["category"] == "park"]

        rest["amenity_access"] = np.round(access_to(rlat, rlon, cp["latitude"].to_numpy(), cp["longitude"].to_numpy()), 4)
        rest["mall_access"] = np.round(access_to(rlat, rlon, malls["latitude"].to_numpy(), malls["longitude"].to_numpy()), 4)
        rest["university_access"] = np.round(access_to(rlat, rlon, unis["latitude"].to_numpy(), unis["longitude"].to_numpy()), 4)
        rest["tourist_access"] = np.round(access_to(rlat, rlon, tour["latitude"].to_numpy(), tour["longitude"].to_numpy()), 4)
        rest["park_access"] = np.round(access_to(rlat, rlon, parks["latitude"].to_numpy(), parks["longitude"].to_numpy()), 4)

        # competition_access: over other restaurants (exclude self -> diagonal weight 1)
        d_rr = haversine_cross(rlat, rlon, rlat, rlon)
        w = np.exp(-d_rr / D0)
        np.fill_diagonal(w, 0.0)
        rest["competition_access"] = np.round(w.sum(axis=1), 4)

        print(f"{city}: {len(rest)} restaurants | "
              f"amenity_access mean={rest['amenity_access'].mean():.2f} max={rest['amenity_access'].max():.2f} | "
              f"competition_access mean={rest['competition_access'].mean():.2f} max={rest['competition_access'].max():.2f}")
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
            assert t_data[c].isna().sum() == 0, f"unexpected NAs in {c}"
        # amenity_access (all POIs) must be >= any single-category access, every row
        for c in ["mall_access", "university_access", "tourist_access", "park_access"]:
            assert (t_data["amenity_access"] >= t_data[c] - 1e-6).all(), f"amenity_access < {c} somewhere!"
        assert t_data.duplicated(subset=["business_id", "week"]).sum() == 0, "duplicates introduced!"

        print(f"  rows: {len(t_data)}, cols: {len(t_data.columns)}, "
              f"amenity_access range: {t_data['amenity_access'].min():.2f}-{t_data['amenity_access'].max():.2f}")

        t_data.to_csv(csv_path, index=False)
        pyreadr.write_rdata(rdata_path, t_data, df_name="t_data", compress="gzip")
        print(f"  saved {csv_path}")

    print("\nDONE")


if __name__ == "__main__":
    main()
