"""
Builds two more location variables and merges them onto all 6 datasets:

    poi_advantage  -- how much more amenity-rich this restaurant's spot is than
                      its neighbours' spots:
                          poi_advantage = n_poi_1km - avg_neigh_n_poi_1km
                      Positive = better-located than the restaurants around it;
                      negative = its neighbours have more nearby amenities.
                      NaN for restaurants with no neighbour within 1000 m (the
                      same isolated restaurants for which avg_neigh_n_poi_1km is
                      already NaN -- "advantage over neighbours" is undefined when
                      there are no neighbours). Pure column arithmetic on two
                      existing columns; nothing is recomputed from raw data.

    poi_diversity  -- how MANY DIFFERENT kinds of POI are near the restaurant,
                      not just how many. Shannon entropy over the mix of the 8
                      OSM POI categories within 1000 m:
                          p_c = (count of category c within 1km) / (total POIs within 1km)
                          poi_diversity = - sum_c p_c * ln(p_c)
                      0 when the restaurant has no POIs within 1 km, or when all
                      nearby POIs are the same single type (no diversity). Higher =
                      a richer mix (mall + museum + park + university ...), which
                      urban-vitality theory (Jacobs) links to steady foot traffic.
                      Computed from osm_poi_raw.csv (all 8 categories, so it is
                      consistent with n_poi_1km which also spans all 8).

Both are static per restaurant. Merged by business_id.
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
CATEGORIES = ["mall", "museum", "attraction", "park", "university", "stadium", "zoo", "theme_park"]

NEW_COLS = ["poi_advantage", "poi_diversity"]


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


def shannon_entropy(count_matrix):
    """count_matrix: rows = restaurants, cols = categories (counts within 1km).
    Returns Shannon entropy per row; 0 where the row total is 0."""
    totals = count_matrix.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        p = np.where(totals > 0, count_matrix / totals, 0.0)
        logp = np.where(p > 0, np.log(p), 0.0)   # 0*log0 := 0
    return -(p * logp).sum(axis=1)


def build_diversity_lookup(poi):
    """business_id -> poi_diversity, computed from the 8-category counts within 1km."""
    frames = []
    for city in CITIES:
        rest = load_restaurants(city)
        rlat, rlon = rest["latitude"].to_numpy(), rest["longitude"].to_numpy()
        cp = poi[poi["city"] == city]
        counts = np.zeros((len(rest), len(CATEGORIES)))
        for j, cat in enumerate(CATEGORIES):
            sub = cp[cp["category"] == cat]
            if len(sub):
                d = haversine_cross(rlat, rlon, sub["latitude"].to_numpy(), sub["longitude"].to_numpy())
                counts[:, j] = (d <= RADIUS_M).sum(axis=1)
        rest["poi_diversity"] = np.round(shannon_entropy(counts), 4)
        print(f"{city}: poi_diversity mean={rest['poi_diversity'].mean():.3f} "
              f"max={rest['poi_diversity'].max():.3f} (0 for {int((rest['poi_diversity']==0).sum())} restaurants)")
        frames.append(rest[["business_id", "poi_diversity"]])
    return pd.concat(frames, ignore_index=True)


def main():
    poi = pd.read_csv(f"{OUT_ROOT}/osm_poi_raw.csv")
    print("Building poi_diversity lookup...")
    diversity = build_diversity_lookup(poi)

    for name in CITIES + ["AllCities_MERGED"]:
        print(f"\n==== {name} ====")
        csv_path = f"{OUT_ROOT}/LATEST_{name}_FULL_DATA.csv"
        rdata_path = f"{OUT_ROOT}/LATEST_t_data_{name}.RData"

        t_data = pd.read_csv(csv_path)
        before_n = len(t_data)
        before_cols = [c for c in t_data.columns if c not in NEW_COLS]
        t_data = t_data[before_cols]

        # poi_advantage: pure arithmetic on two existing columns
        t_data["poi_advantage"] = (t_data["n_poi_1km"] - t_data["avg_neigh_n_poi_1km"]).round(3)
        # poi_diversity: merge by business_id
        t_data = t_data.merge(diversity, on="business_id", how="left")

        assert len(t_data) == before_n, "row count changed!"
        assert list(t_data.columns) == before_cols + NEW_COLS, "column set changed unexpectedly"
        assert t_data["poi_diversity"].isna().sum() == 0, "unexpected NAs in poi_diversity"
        # poi_advantage NaN only where avg_neigh_n_poi_1km is NaN (isolated restaurants)
        adv_na = t_data["poi_advantage"].isna()
        neigh_na = t_data["avg_neigh_n_poi_1km"].isna()
        assert (adv_na == neigh_na).all(), "poi_advantage NaNs do not match isolated-restaurant NaNs"
        assert t_data.duplicated(subset=["business_id", "week"]).sum() == 0, "duplicates introduced!"

        print(f"  rows: {len(t_data)}, cols: {len(t_data.columns)}, "
              f"poi_advantage NAs (isolated): {int(adv_na.sum())} ({100*adv_na.mean():.2f}%), "
              f"poi_advantage range: {t_data['poi_advantage'].min():.1f} to {t_data['poi_advantage'].max():.1f}")

        t_data.to_csv(csv_path, index=False)
        pyreadr.write_rdata(rdata_path, t_data, df_name="t_data", compress="gzip")
        print(f"  saved {csv_path}")

    print("\nDONE")


if __name__ == "__main__":
    main()
