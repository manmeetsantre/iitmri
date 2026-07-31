"""
Recomputes the 3 cluster-heterogeneity variables in pure Python:
    venue_type_heterogeneity, cuisine_heterogeneity, service_style_heterogeneity

Pipeline (per city):
  1. Read raw business_<City>.RData (business_id, categories, latitude, longitude)
     directly with `rdata` -- no R computation involved, just reading the file format.
  2. Classify each restaurant into a single venue_type / cuisine / service_style label
     using the previous intern's VENUE_TYPE_MAP / CUISINE_MAP / SERVICE_STYLE_MAP
     (first matching group, in map order, wins).
  3. Greedy single-pass spatial clustering (1000m haversine radius), replicating
     build_compdata.py's cluster_restaurants().
  4. For each cluster, compute heterogeneity = |intersection of member labels| /
     |union of member labels|, separately for venue_type / cuisine / service_style,
     and broadcast that value back to every restaurant in the cluster.
  5. Merge the 3 resulting columns onto each of the 6 prepared datasets (by
     business_id), verify no NAs/duplicates introduced, and save.

venue_type / cuisine / service_style / cluster_id are intermediate-only: computed
here to derive the heterogeneity scores, but not written to the final files.
"""

import json

import numpy as np
import pandas as pd
import rdata

SRC_ROOT = "/Users/MANMEETSANTRE/Desktop/restaurantri/YelpJSON"
OUT_ROOT = "/Users/MANMEETSANTRE/Downloads/restaurant-agglomeration-main/new_variables"
RAW_JSONL_PATH = f"{SRC_ROOT}/yelp_academic_dataset_business.json"
RADIUS_M = 1000.0
EARTH_RADIUS_M = 6371000.0  # matches the previous intern's build_compdata.py exactly

CITIES = ["Tucson", "Tampa", "Indianapolis", "Nashville", "Philadelphia"]

VENUE_TYPE_MAP = {
    "Bar_Nightlife": ["Bars", "Nightlife", "Pubs", "Lounges", "Beer Bar", "Wine Bars", "Cocktail Bars", "Sports Bars", "Dive Bars", "Gastropubs"],
    "Cafe": ["Cafes", "Coffee & Tea", "Internet Cafes"],
    "Bakery_Dessert": ["Bakeries", "Desserts", "Donuts", "Ice Cream & Frozen Yogurt", "Gelato", "Patisserie/Cake Shop", "Cupcakes"],
    "Food_Truck_Street": ["Food Trucks", "Food Stands", "Street Vendors", "Pop-Up Restaurants"],
    "Grocery_Retail_Food": ["Grocery", "Delis", "Convenience Stores", "Meat Shops", "Seafood Markets", "Specialty Food", "Butcher"],
    "Entertainment_Venue": ["Music Venues", "Arts & Entertainment", "Arcades", "Museums", "Bowling", "Jazz & Blues"],
    "Hotel_Travel_Dining": ["Hotels", "Hotels & Travel", "Airport Lounges", "Resorts"],
    "Event_Catering": ["Caterers", "Event Planning & Services", "Venues & Event Spaces"],
}

CUISINE_MAP = {
    "Mexican_Latin": ["Mexican", "Tex-Mex", "Tacos", "New Mexican Cuisine", "Latin American", "Cuban", "Peruvian", "Brazilian", "Colombian", "Argentine", "Dominican", "Puerto Rican", "Empanadas"],
    "Italian": ["Italian", "Pizza", "Pasta Shops"],
    "Chinese": ["Chinese", "Szechuan", "Cantonese", "Dim Sum", "Hot Pot", "Noodles"],
    "Japanese": ["Japanese", "Sushi Bars", "Ramen", "Poke"],
    "South_Southeast_Asian": ["Indian", "Pakistani", "Thai", "Vietnamese", "Filipino", "Taiwanese", "Pan Asian", "Asian Fusion"],
    "Mediterranean_MiddleEastern": ["Mediterranean", "Greek", "Middle Eastern", "Persian/Iranian", "Turkish", "Falafel", "Halal"],
    "American": ["American (Traditional)", "American (New)", "Southern", "Soul Food", "Comfort Food", "Barbeque"],
    "Seafood": ["Seafood", "Fish & Chips", "Seafood Markets", "Live/Raw Food"],
    "Vegan_Vegetarian_Health": ["Vegan", "Vegetarian", "Gluten-Free", "Organic Stores", "Health Markets", "Juice Bars & Smoothies", "Acai Bowls"],
    "European_Other": ["French", "German", "Spanish", "Basque", "Russian", "Canadian (New)"],
    "Caribbean_African": ["Caribbean", "African", "Ethiopian"],
}

SERVICE_STYLE_MAP = {
    "Fast_Food": ["Fast Food", "Hot Dogs", "Chicken Shop"],
    "Breakfast_Brunch": ["Breakfast & Brunch", "Bagels", "Creperies"],
    "Delivery_Takeaway": ["Food Delivery Services"],
    "Buffet": ["Buffets"],
    "Food_Truck": ["Food Trucks", "Food Stands", "Street Vendors"],
    "Bar_Service": ["Bars", "Cocktail Bars", "Beer Bar", "Wine Bars", "Pubs"],
    "Cafe_Style": ["Cafes", "Coffee & Tea"],
    "Fine_Casual_Dining": ["Restaurants"],
    "Catering_Events": ["Caterers", "Event Planning & Services"],
}


def lower_map(m):
    return {k: set(v.lower() for v in vals) for k, vals in m.items()}


VENUE_TYPE_MAP_LC = lower_map(VENUE_TYPE_MAP)
CUISINE_MAP_LC = lower_map(CUISINE_MAP)
SERVICE_STYLE_MAP_LC = lower_map(SERVICE_STYLE_MAP)


def match_group(cats_lc_set, map_lc):
    for group, values_lc in map_lc.items():
        if values_lc & cats_lc_set:
            return group
    return None


def classify(categories_str):
    cats_lc = set(c.strip().lower() for c in categories_str.split(","))
    venue = match_group(cats_lc, VENUE_TYPE_MAP_LC) or "Other"
    cuisine = match_group(cats_lc, CUISINE_MAP_LC) or "Other"
    service = match_group(cats_lc, SERVICE_STYLE_MAP_LC) or "Fine_Casual_Dining"
    return venue, cuisine, service


def haversine_matrix(lat, lon):
    """Pairwise haversine distances in meters, vectorized (n x n)."""
    lat_r = np.radians(lat)
    lon_r = np.radians(lon)
    dlat = lat_r[:, None] - lat_r[None, :]
    dlon = lon_r[:, None] - lon_r[None, :]
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat_r[:, None]) * np.cos(lat_r[None, :]) * np.sin(dlon / 2.0) ** 2
    c = 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    return EARTH_RADIUS_M * c


def cluster_restaurants(lat, lon, radius_m=RADIUS_M):
    """Greedy single-pass clustering, same order-dependent method as build_compdata.py:
    iterate restaurants in order; each unassigned restaurant seeds a new cluster and
    absorbs every still-unassigned restaurant within radius_m of it."""
    n = len(lat)
    dist_mat = haversine_matrix(lat, lon)
    assigned = np.full(n, -1, dtype=int)
    cluster_id = 0
    for i in range(n):
        if assigned[i] != -1:
            continue
        within = np.where((dist_mat[i] <= radius_m) & (assigned == -1))[0]
        assigned[within] = cluster_id
        cluster_id += 1
    return assigned


def set_heterogeneity(labels):
    """|intersection of member label-sets| / |union of member label-sets|.
    Each member contributes a singleton set {its own label}."""
    labels = [l for l in labels if l is not None]
    if not labels:
        return 0.0
    sets = [{l} for l in labels]
    union = set.union(*sets)
    inter = set.intersection(*sets)
    if not union:
        return 0.0
    return len(inter) / len(union)


def load_business_raw(city):
    parsed = rdata.parser.parse_file(f"{SRC_ROOT}/business_{city}.RData")
    conv = rdata.conversion.convert(parsed, constructor_dict={})
    obj = conv["bus_res_city"]
    return pd.DataFrame({
        "business_id": obj["business_id"],
        "categories": obj["categories"],
        "latitude": obj["latitude"].astype(float),
        "longitude": obj["longitude"].astype(float),
    })


def load_raw_jsonl_order():
    """business_id -> line number in the raw Yelp business JSONL dump. This is the
    order the previous intern's iter_jsonl()/load_restaurants() processed restaurants
    in, which determines which restaurant seeds each cluster in cluster_restaurants()."""
    order = {}
    with open(RAW_JSONL_PATH, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            bid = json.loads(line)["business_id"]
            order[bid] = i
    return order


def process_city(city, cluster_id_offset, jsonl_order):
    print(f"==== {city} ====")
    biz = load_business_raw(city)
    biz["categories"] = biz["categories"].fillna("")

    # Reorder to match the raw JSONL dump order (same order the previous intern's
    # script iterated in), instead of the alphabetical-by-business_id order that
    # business_<City>.RData happens to be in.
    missing = biz.loc[~biz["business_id"].isin(jsonl_order), "business_id"]
    assert len(missing) == 0, f"{len(missing)} business_ids not found in raw JSONL dump"
    biz["_jsonl_order"] = biz["business_id"].map(jsonl_order)
    biz = biz.sort_values("_jsonl_order").drop(columns="_jsonl_order").reset_index(drop=True)

    labels = biz["categories"].apply(classify)
    biz["venue_type"] = labels.apply(lambda x: x[0])
    biz["cuisine"] = labels.apply(lambda x: x[1])
    biz["service_style"] = labels.apply(lambda x: x[2])

    local_cluster_id = cluster_restaurants(biz["latitude"].to_numpy(), biz["longitude"].to_numpy())
    biz["cluster_id"] = local_cluster_id + cluster_id_offset

    het_rows = []
    for cid, grp in biz.groupby("cluster_id"):
        het_rows.append({
            "cluster_id": cid,
            "venue_type_heterogeneity": set_heterogeneity(grp["venue_type"].tolist()),
            "cuisine_heterogeneity": set_heterogeneity(grp["cuisine"].tolist()),
            "service_style_heterogeneity": set_heterogeneity(grp["service_style"].tolist()),
        })
    het = pd.DataFrame(het_rows)

    biz = biz.merge(het, on="cluster_id", how="left")
    n_clusters = biz["cluster_id"].nunique()
    print(f"n_restaurants: {len(biz)}  n_clusters: {n_clusters}")

    lookup = biz[["business_id", "venue_type_heterogeneity", "cuisine_heterogeneity", "service_style_heterogeneity"]]
    return lookup, int(biz["cluster_id"].max())


def main():
    print("Loading raw JSONL business order (yelp_academic_dataset_business.json)...")
    jsonl_order = load_raw_jsonl_order()
    print(f"Loaded order for {len(jsonl_order)} businesses.\n")

    all_lookups = []
    offset = 0

    for city in CITIES:
        lookup, next_offset = process_city(city, offset, jsonl_order)
        all_lookups.append(lookup)
        offset = next_offset

        rdata_path = f"{OUT_ROOT}/LATEST_t_data_{city}.RData"
        csv_path = f"{OUT_ROOT}/LATEST_{city}_FULL_DATA.csv"

        print(f"Loading current t_data for {city}...")
        t_data = pd.read_csv(csv_path)
        before_n = len(t_data)
        before_cols = set(t_data.columns)

        drop_cols = [c for c in ["venue_type_heterogeneity", "cuisine_heterogeneity", "service_style_heterogeneity"] if c in t_data.columns]
        t_data = t_data.drop(columns=drop_cols)

        t_data = t_data.merge(lookup, on="business_id", how="left")

        assert len(t_data) == before_n, "row count changed"
        assert t_data["venue_type_heterogeneity"].isna().sum() == 0
        assert t_data["cuisine_heterogeneity"].isna().sum() == 0
        assert t_data["service_style_heterogeneity"].isna().sum() == 0
        assert t_data.duplicated(subset=["business_id", "week"]).sum() == 0

        t_data.to_csv(csv_path, index=False)
        print(f"Saved {csv_path}")

    print("\n==== AllCities_MERGED ====")
    merged_lookup = pd.concat(all_lookups, ignore_index=True)
    merged_csv = f"{OUT_ROOT}/LATEST_AllCities_MERGED_FULL_DATA.csv"
    t_data = pd.read_csv(merged_csv)
    before_n = len(t_data)

    drop_cols = [c for c in ["venue_type_heterogeneity", "cuisine_heterogeneity", "service_style_heterogeneity"] if c in t_data.columns]
    t_data = t_data.drop(columns=drop_cols)
    t_data = t_data.merge(merged_lookup, on="business_id", how="left")

    assert len(t_data) == before_n
    assert t_data["venue_type_heterogeneity"].isna().sum() == 0
    assert t_data["cuisine_heterogeneity"].isna().sum() == 0
    assert t_data["service_style_heterogeneity"].isna().sum() == 0
    assert t_data.duplicated(subset=["business_id", "week"]).sum() == 0

    t_data.to_csv(merged_csv, index=False)
    print(f"Saved {merged_csv}")
    print("\nDONE")


if __name__ == "__main__":
    main()
