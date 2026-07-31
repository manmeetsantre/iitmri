"""
Recomputes the 3 "local" heterogeneity variables in pure Python:
    local_venue_type_heterogeneity, local_cuisine_heterogeneity, local_service_style_heterogeneity

Replicates the previous intern's extend_local_heterogeneity.py, but per-restaurant
instead of per-fixed-cluster (see compute_heterogeneity.py / README.md for the
cluster-based version, which is a separate, different set of variables).

Pipeline (per city):
  1. Read raw business_<City>.RData (business_id, categories, latitude, longitude)
     directly with `rdata` -- no R computation involved, just reading the file format.
  2. Classify each restaurant into a single venue_type / cuisine / service_style label
     (same classification maps as compute_heterogeneity.py).
  3. For each restaurant, find every restaurant (including itself) within 1000m
     (haversine distance) -- this is a per-restaurant neighborhood, NOT a shared,
     fixed cluster like Batch 1.
  4. local_homogeneity = 1.0 if every restaurant in that neighborhood (self included)
     has the identical label, else 0.0 -- a strict yes/no flag, not a graded ratio.
     An isolated restaurant with no neighbors trivially scores 1.0 (nothing around it
     disagrees with it).
  5. Merge the 3 resulting columns onto each of the 6 prepared datasets (by
     business_id), verify no NAs/duplicates introduced, and save (csv + RData).

venue_type / cuisine / service_style are intermediate-only here too: computed to
derive the local heterogeneity flags, not written to the final files (same reasoning
as compute_heterogeneity.py -- they're re-labelings of existing category data, not new
information).
"""

import numpy as np
import pandas as pd
import rdata
import pyreadr

SRC_ROOT = "/Users/MANMEETSANTRE/Desktop/restaurantri/YelpJSON"
OUT_ROOT = "/Users/MANMEETSANTRE/Downloads/restaurant-agglomeration-main/new_variables"
RADIUS_M = 1000.0
EARTH_RADIUS_M = 6371000.0  # matches the previous intern's extend_local_heterogeneity.py exactly

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
    """Pairwise haversine distances in meters, vectorized (n x n). Diagonal is 0
    (a restaurant's distance to itself), which is what makes self-inclusion happen
    automatically in the <=radius_m comparison below."""
    lat_r = np.radians(lat)
    lon_r = np.radians(lon)
    dlat = lat_r[:, None] - lat_r[None, :]
    dlon = lon_r[:, None] - lon_r[None, :]
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat_r[:, None]) * np.cos(lat_r[None, :]) * np.sin(dlon / 2.0) ** 2
    c = 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    return EARTH_RADIUS_M * c


def local_homogeneity_all(labels, within_mask):
    """For each restaurant i, look at labels of all j where within_mask[i, j] is True
    (includes i itself, since distance-to-self is 0). Return 1.0 if all those labels
    are identical, else 0.0. Vectorized per-row using pandas/numpy grouping."""
    n = len(labels)
    labels = np.asarray(labels)
    out = np.empty(n, dtype=float)
    for i in range(n):
        neigh_labels = labels[within_mask[i]]
        out[i] = 1.0 if len(set(neigh_labels)) == 1 else 0.0
    return out


def process_city(city):
    print(f"==== {city} ====")
    parsed = rdata.parser.parse_file(f"{SRC_ROOT}/business_{city}.RData")
    conv = rdata.conversion.convert(parsed, constructor_dict={})
    obj = conv["bus_res_city"]
    biz = pd.DataFrame({
        "business_id": obj["business_id"],
        "categories": obj["categories"],
        "latitude": obj["latitude"].astype(float),
        "longitude": obj["longitude"].astype(float),
    })
    biz["categories"] = biz["categories"].fillna("")

    labels = biz["categories"].apply(classify)
    biz["venue_type"] = labels.apply(lambda x: x[0])
    biz["cuisine"] = labels.apply(lambda x: x[1])
    biz["service_style"] = labels.apply(lambda x: x[2])

    dist_mat = haversine_matrix(biz["latitude"].to_numpy(), biz["longitude"].to_numpy())
    within_mask = dist_mat <= RADIUS_M  # n x n boolean, diagonal always True

    biz["local_venue_type_heterogeneity"] = local_homogeneity_all(biz["venue_type"].to_numpy(), within_mask)
    biz["local_cuisine_heterogeneity"] = local_homogeneity_all(biz["cuisine"].to_numpy(), within_mask)
    biz["local_service_style_heterogeneity"] = local_homogeneity_all(biz["service_style"].to_numpy(), within_mask)

    n_isolated = int((within_mask.sum(axis=1) == 1).sum())
    print(f"n_restaurants: {len(biz)}  n_isolated (no neighbors within {int(RADIUS_M)}m): {n_isolated}")
    print(f"pct local_venue_type_heterogeneity==1: {biz['local_venue_type_heterogeneity'].mean():.3f}")
    print(f"pct local_cuisine_heterogeneity==1: {biz['local_cuisine_heterogeneity'].mean():.3f}")
    print(f"pct local_service_style_heterogeneity==1: {biz['local_service_style_heterogeneity'].mean():.3f}")

    return biz[["business_id", "local_venue_type_heterogeneity", "local_cuisine_heterogeneity", "local_service_style_heterogeneity"]]


def merge_and_save(name, lookup):
    csv_path = f"{OUT_ROOT}/LATEST_{name}_FULL_DATA.csv"
    rdata_path = f"{OUT_ROOT}/LATEST_t_data_{name}.RData"

    print(f"Loading current t_data for {name}...")
    t_data = pd.read_csv(csv_path)
    before_n = len(t_data)

    drop_cols = [c for c in lookup.columns if c != "business_id" and c in t_data.columns]
    t_data = t_data.drop(columns=drop_cols)
    t_data = t_data.merge(lookup, on="business_id", how="left")

    assert len(t_data) == before_n, "row count changed"
    for c in ["local_venue_type_heterogeneity", "local_cuisine_heterogeneity", "local_service_style_heterogeneity"]:
        assert t_data[c].isna().sum() == 0, f"NAs introduced in {c}"
    assert t_data.duplicated(subset=["business_id", "week"]).sum() == 0

    t_data.to_csv(csv_path, index=False)
    pyreadr.write_rdata(rdata_path, t_data, df_name="t_data", compress="gzip")
    print(f"Saved {name}: {t_data.shape}")


def main():
    all_lookups = []
    for city in CITIES:
        lookup = process_city(city)
        all_lookups.append(lookup)
        merge_and_save(city, lookup)

    print("\n==== AllCities_MERGED ====")
    merged_lookup = pd.concat(all_lookups, ignore_index=True)
    merge_and_save("AllCities_MERGED", merged_lookup)

    print("\nDONE")


if __name__ == "__main__":
    main()
