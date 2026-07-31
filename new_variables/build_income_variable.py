"""
Builds median_household_income and merges it onto all 6 prepared datasets.

Methodology (per mam's instruction: exact match only, blank wherever data
isn't there -- no filling/imputation at this stage, that's deferred to model time):

  1. Build a zip_code lookup per restaurant, from the raw business_<City>.RData
     files (business_id -> postal_code). Apply one known correction: business_id
     Jfi-hoD-hKlnu3LljlEUqA (Apna Kabab House, Tampa) has postal_code "336140"
     in Yelp's own original data (a 6-digit typo) -- corrected to "33614" here
     only, for matching purposes. The 9 food-truck business_ids with no address
     in Yelp's data keep an empty zip_code (so they get NA income, honestly).

  2. For each of the 6 datasets, derive a 'year' column from each row's 'week'
     number, using the same date formula the original R pipeline uses:
     calendar_date = 1970-01-01 + 12620 days + week*7 days.

  3. Merge in median_household_income from census_income_raw.csv (Census ACS
     5-Year data, table B19013, pulled via api.census.gov) by EXACT match on
     (zip_code, year). No fallback to a nearby year -- if the exact (zip, year)
     combination isn't in the Census data, income is left NA for that row.
     This covers three real, disclosed limitations:
       - Rows from 2005-2010: Census's ZCTA-level (zip-code-level) data via
         this API does not exist for 2009 or 2010 at all (confirmed by testing
         random zip codes, not just ours -- a real gap in the government's own
         system, not something fixable by querying differently), and 2005-2008
         predates the ACS 5-Year product entirely.
       - 20 zip codes (73 restaurants) that never have Census income data in
         any year 2011-2024 -- traced to these being P.O. Box/administrative
         zip codes with no residential population, so Census structurally
         never measures income there.
       - A small number (113) of specific (zip, year) pairs where Census's own
         value was the official "not a reliable estimate" sentinel code
         (-666666666) -- treated as missing, not as a literal negative income.

  4. The 'year' intermediate column is not kept as a final variable (same
     reasoning as venue_type/cluster_id in earlier batches -- it's scaffolding
     used to do the merge, not new information).
"""
import datetime
import pandas as pd
import pyreadr
import rdata

SRC_ROOT = "/Users/MANMEETSANTRE/Desktop/restaurantri/YelpJSON"
OUT_ROOT = "/Users/MANMEETSANTRE/Downloads/restaurant-agglomeration-main/new_variables"
CITIES = ["Tucson", "Tampa", "Indianapolis", "Nashville", "Philadelphia"]

TYPO_FIX = {"Jfi-hoD-hKlnu3LljlEUqA": "33614"}  # Apna Kabab House, Tampa: 336140 -> 33614
CENSUS_NULL_SENTINEL = -666666666

EPOCH = datetime.date(1970, 1, 1)
DAY_OFFSET = 12620  # matches latest.R's week formula: week = ceiling((date - 12620)/7)


def week_to_year(week):
    d = EPOCH + datetime.timedelta(days=DAY_OFFSET + int(week) * 7)
    return d.year


# ---- Step 1: build business_id -> zip_code lookup for all 5 cities ----
print("Building zip_code lookup from raw business files...")
zip_lookup_frames = []
for city in CITIES:
    parsed = rdata.parser.parse_file(f"{SRC_ROOT}/business_{city}.RData")
    conv = rdata.conversion.convert(parsed, constructor_dict={})
    obj = conv["bus_res_city"]
    df = pd.DataFrame({
        "business_id": obj["business_id"],
        "zip_code": pd.Series(obj["postal_code"]).astype(str).str.zfill(5),
    })
    zip_lookup_frames.append(df)

zip_lookup = pd.concat(zip_lookup_frames, ignore_index=True)
zip_lookup["zip_code"] = zip_lookup.apply(
    lambda r: TYPO_FIX.get(r["business_id"], r["zip_code"]), axis=1
)
zip_lookup.loc[zip_lookup["zip_code"] == "00000", "zip_code"] = pd.NA  # food trucks: no real zip
print(f"  {len(zip_lookup)} business_id -> zip_code rows built "
      f"({zip_lookup['zip_code'].isna().sum()} with no zip code)")

# ---- Step 2: load Census income lookup, clean sentinel values ----
print("Loading Census income data...")
income = pd.read_csv(
    f"{OUT_ROOT}/census_income_raw.csv",
    dtype={"zip_code": str},
)
n_sentinel = (income["median_household_income"] == CENSUS_NULL_SENTINEL).sum()
income.loc[income["median_household_income"] == CENSUS_NULL_SENTINEL, "median_household_income"] = pd.NA
income = income.dropna(subset=["median_household_income"])
print(f"  {len(income)} real (zip, year) income rows loaded "
      f"({n_sentinel} sentinel/no-reliable-estimate values dropped)")

# ---- Step 3: merge onto each of the 6 datasets ----
NAMES = CITIES + ["AllCities_MERGED"]

for name in NAMES:
    print(f"\n==== {name} ====")
    csv_path = f"{OUT_ROOT}/LATEST_{name}_FULL_DATA.csv"
    rdata_path = f"{OUT_ROOT}/LATEST_t_data_{name}.RData"

    t_data = pd.read_csv(csv_path)
    before_n = len(t_data)
    before_cols = list(t_data.columns)

    if "median_household_income" in t_data.columns:
        t_data = t_data.drop(columns=["median_household_income"])

    t_data["_year"] = t_data["week"].apply(week_to_year)
    t_data = t_data.merge(zip_lookup, on="business_id", how="left")
    t_data = t_data.merge(
        income.rename(columns={"year": "_year"}),
        on=["zip_code", "_year"], how="left",
    )
    t_data = t_data.drop(columns=["_year", "zip_code"])

    assert len(t_data) == before_n, "row count changed!"
    assert list(t_data.columns) == before_cols + ["median_household_income"], "column set changed unexpectedly"
    assert t_data.duplicated(subset=["business_id", "week"]).sum() == 0, "duplicates introduced!"

    n_na = t_data["median_household_income"].isna().sum()
    pct_na = 100 * n_na / len(t_data)
    print(f"  rows: {len(t_data)}, median_household_income NAs: {n_na} ({pct_na:.2f}%)")
    print(f"  income stats (non-NA): min={t_data['median_household_income'].min():.0f}, "
          f"median={t_data['median_household_income'].median():.0f}, "
          f"max={t_data['median_household_income'].max():.0f}")

    t_data.to_csv(csv_path, index=False)
    pyreadr.write_rdata(rdata_path, t_data, df_name="t_data", compress="gzip")
    print(f"  saved {csv_path}")

print("\nDONE")
