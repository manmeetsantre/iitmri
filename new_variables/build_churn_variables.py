"""
Builds TIME-VARYING local churn variables and merges them onto all 6 datasets.

For each restaurant, each week, this counts how much its immediate area (within
1000 m) has been "turning over" in the trailing 52 weeks -- i.e. how many nearby
restaurants recently opened or closed. A high-churn area is an unstable location,
which may raise a restaurant's own failure risk.

New columns (3), all TIME-VARYING (they change week to week for a given restaurant):
    local_openings_1yr -- # of OTHER restaurants within 1000 m that OPENED in the
                          trailing 52 weeks (weeks t-51 .. t).
    local_closings_1yr -- # of OTHER restaurants within 1000 m that CLOSED in the
                          trailing 52 weeks.
    local_churn_1yr    -- local_openings_1yr + local_closings_1yr (total turnover).

How open/close weeks are read from the panel (verified encoding):
  - Each restaurant is is_open=1 every week it is alive, then has a single terminal
    is_open=0 row at the week it closes. Restaurants still open at the end of the
    data never have an is_open=0 row (right-censored -- no closing event).
  - birth_week  = first week the restaurant appears in the panel (its opening).
  - close_week  = its single is_open=0 week, if it has one (its closing); otherwise
    the restaurant has no closing event.

Computation (per city, to keep it exact and fast):
  - Neighbour adjacency B: restaurants within 1000 m of each other (self excluded),
    haversine, Earth radius 6,371,000 m.
  - Each opening/closing is an "event" at (restaurant j, event_week e). An event at
    j adds +1 to the trailing-year count of every neighbour i of j, for the 52 weeks
    e .. e+51. We accumulate that directly into per-restaurant weekly arrays, then
    read off the value for each (restaurant, week) row that appears in the panel.
  - self is excluded, so a restaurant's own opening/closing never counts toward its
    own churn.
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
WINDOW = 52  # trailing weeks

NEW_COLS = ["local_openings_1yr", "local_closings_1yr", "local_churn_1yr"]


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


def build_city_churn(city, panel):
    """Returns a DataFrame with (business_id, week, local_openings_1yr,
    local_closings_1yr, local_churn_1yr) for one city."""
    rest = load_restaurants(city)
    coords = rest.set_index("business_id")

    p = panel[panel["business_id"].isin(coords.index)].copy()

    # birth week and (optional) close week per restaurant, from the panel
    births = p.groupby("business_id")["week"].min()
    closes = p[p["is_open"] == 0].groupby("business_id")["week"].min()  # single terminal week

    # align to the restaurant order in `rest`
    rest = rest[rest["business_id"].isin(births.index)].reset_index(drop=True)
    bid = rest["business_id"].to_numpy()
    idx_of = {b: i for i, b in enumerate(bid)}
    n = len(rest)

    birth_week = births.reindex(bid).to_numpy()
    close_week = closes.reindex(bid).to_numpy()  # NaN where the restaurant never closed

    # weekly grid
    wmin = int(p["week"].min())
    wmax = int(p["week"].max())
    W = wmax - wmin + 1

    # neighbour adjacency within 1000 m (self excluded)
    d = haversine_cross(rest["latitude"].to_numpy(), rest["longitude"].to_numpy(),
                        rest["latitude"].to_numpy(), rest["longitude"].to_numpy())
    neigh = d <= RADIUS_M
    np.fill_diagonal(neigh, False)

    open_grid = np.zeros((n, W), dtype=np.int32)   # opening churn each restaurant sees each week
    close_grid = np.zeros((n, W), dtype=np.int32)

    def add_event(j, e_week, grid):
        # event at restaurant j in week e_week affects its neighbours for weeks e..e+51
        lo = e_week - wmin
        hi = min(lo + WINDOW, W)          # weeks [lo, lo+52)
        if hi <= 0 or lo >= W:
            return
        lo = max(lo, 0)
        nbrs = np.where(neigh[:, j])[0]   # restaurants that have j as a neighbour
        if len(nbrs):
            grid[np.ix_(nbrs, np.arange(lo, hi))] += 1

    for j in range(n):
        add_event(j, int(birth_week[j]), open_grid)
        if not np.isnan(close_week[j]):
            add_event(j, int(close_week[j]), close_grid)

    # read the grid value for each (business_id, week) row in the panel
    p = p[["business_id", "week"]].copy()
    ri = p["business_id"].map(idx_of).to_numpy()
    wi = p["week"].to_numpy() - wmin
    p["local_openings_1yr"] = open_grid[ri, wi]
    p["local_closings_1yr"] = close_grid[ri, wi]
    p["local_churn_1yr"] = p["local_openings_1yr"] + p["local_closings_1yr"]
    print(f"{city}: {n} restaurants, weeks {wmin}-{wmax} | "
          f"local_churn_1yr mean={p['local_churn_1yr'].mean():.2f} max={p['local_churn_1yr'].max()}")
    return p


def main():
    # per-city panels come straight from each city's own file (has is_open, week)
    lookups = []
    for city in CITIES:
        panel = pd.read_csv(f"{OUT_ROOT}/LATEST_{city}_FULL_DATA.csv",
                            usecols=["business_id", "week", "is_open"])
        lookups.append(build_city_churn(city, panel))
    churn = pd.concat(lookups, ignore_index=True)

    for name in CITIES + ["AllCities_MERGED"]:
        print(f"\n==== {name} ====")
        csv_path = f"{OUT_ROOT}/LATEST_{name}_FULL_DATA.csv"
        rdata_path = f"{OUT_ROOT}/LATEST_t_data_{name}.RData"

        t_data = pd.read_csv(csv_path)
        before_n = len(t_data)
        before_cols = [c for c in t_data.columns if c not in NEW_COLS]
        t_data = t_data[before_cols]

        t_data = t_data.merge(churn, on=["business_id", "week"], how="left")

        assert len(t_data) == before_n, "row count changed!"
        assert list(t_data.columns) == before_cols + NEW_COLS, "column set changed unexpectedly"
        for c in NEW_COLS:
            assert t_data[c].isna().sum() == 0, f"unexpected NAs in {c}"
        assert (t_data["local_churn_1yr"] ==
                t_data["local_openings_1yr"] + t_data["local_closings_1yr"]).all(), "churn != open+close"
        assert (t_data[NEW_COLS] >= 0).all().all(), "negative churn!"
        assert t_data.duplicated(subset=["business_id", "week"]).sum() == 0, "duplicates introduced!"

        print(f"  rows: {len(t_data)}, cols: {len(t_data.columns)}, "
              f"local_churn_1yr mean={t_data['local_churn_1yr'].mean():.2f} max={t_data['local_churn_1yr'].max()}")

        t_data.to_csv(csv_path, index=False)
        pyreadr.write_rdata(rdata_path, t_data, df_name="t_data", compress="gzip")
        print(f"  saved {csv_path}")

    print("\nDONE")


if __name__ == "__main__":
    main()
