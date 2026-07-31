"""
Pulls median household income (table B19013) by ZIP Code Tabulation Area (ZCTA)
from the Census Bureau's ACS 5-Year API, for every zip code across our 5 cities'
restaurants, for every year 2009-2024. Saves census_income_raw.csv (zip_code,
year, median_household_income) in this folder.

Run this before build_income_variable.py.

Requires a free Census API key: https://api.census.gov/data/key_signup.html
Set it as an environment variable before running:
    export CENSUS_API_KEY=your_key_here

Discovered via direct testing: for years 2009-2019 the API requires the ZCTA
query to be qualified with a parent state (&in=state:XX), or it returns
"error: ambiguous geography" (HTTP 400) for every request. From 2020 onward,
ZCTA can be queried directly with no state qualifier. This script queries
state-by-state for 2009-2019 (using each zip's real state) and directly
(no state qualifier) for 2020-2024, matching what was confirmed to work.

Separately: 2009 and 2010 do not support ZCTA-level queries at all (confirmed
by testing random zip codes nationwide, not just ours) -- these two years will
come back with 0 rows regardless. That's a real limitation of the Census API
itself, not a bug in this script.
"""
import json
import os
import time
import urllib.request
import csv

import pandas as pd
import rdata

SRC_ROOT = "/Users/MANMEETSANTRE/Desktop/restaurantri/YelpJSON"
OUT_ROOT = "/Users/MANMEETSANTRE/Downloads/restaurant-agglomeration-main/new_variables"

API_KEY = os.environ["CENSUS_API_KEY"]
YEARS = list(range(2009, 2025))  # 2009..2024
NEEDS_STATE_QUALIFIER_BEFORE = 2020
BATCH_SIZE = 50

# FIPS state codes for our 5 cities
STATE_FIPS = {"Tucson": "04", "Tampa": "12", "Indianapolis": "18", "Nashville": "47", "Philadelphia": "42"}

# One known typo in Yelp's own source data, corrected here for matching purposes only
TYPO_FIX = {"336140": "33614"}  # Apna Kabab House, Tampa


def build_zip_to_state():
    """Reads postal_code from each city's raw business_<City>.RData and maps
    each real zip code to its state's FIPS code, for querying the Census API."""
    zip_to_state = {}
    for city, fips in STATE_FIPS.items():
        parsed = rdata.parser.parse_file(f"{SRC_ROOT}/business_{city}.RData")
        conv = rdata.conversion.convert(parsed, constructor_dict={})
        obj = conv["bus_res_city"]
        zips = set(pd.Series(obj["postal_code"]).astype(str).str.zfill(5))
        zips.discard("00000")  # food trucks with no address
        for z in zips:
            z = TYPO_FIX.get(z, z)
            zip_to_state[z] = fips
    return zip_to_state


def batches_for_year(year, zip_to_state):
    zips = sorted(zip_to_state.keys())
    if year < NEEDS_STATE_QUALIFIER_BEFORE:
        by_state = {}
        for z, st in zip_to_state.items():
            by_state.setdefault(st, []).append(z)
        out = []
        for st, zs in by_state.items():
            zs = sorted(zs)
            for i in range(0, len(zs), BATCH_SIZE):
                out.append((zs[i:i + BATCH_SIZE], st))
        return out
    else:
        return [(zips[i:i + BATCH_SIZE], None) for i in range(0, len(zips), BATCH_SIZE)]


def main():
    print("Building zip code -> state lookup from raw business files...")
    zip_to_state = build_zip_to_state()
    print(f"Querying {len(zip_to_state)} zip codes across {len(YEARS)} years...")

    rows = []
    errors = []

    for year in YEARS:
        year_rows_before = len(rows)
        for zip_batch, state_fips in batches_for_year(year, zip_to_state):
            zips_param = ",".join(zip_batch)
            url = (f"https://api.census.gov/data/{year}/acs/acs5"
                   f"?get=NAME,B19013_001E&for=zip%20code%20tabulation%20area:{zips_param}")
            if state_fips is not None:
                url += f"&in=state:{state_fips}"
            url += f"&key={API_KEY}"
            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    data = json.loads(resp.read().decode())
                header = data[0]
                for row in data[1:]:
                    rec = dict(zip(header, row))
                    rows.append({
                        "zip_code": rec.get("zip code tabulation area"),
                        "year": year,
                        "median_household_income": rec.get("B19013_001E"),
                    })
            except Exception as e:
                errors.append((year, state_fips, zip_batch[:3], str(e)[:200]))
            time.sleep(0.3)  # be polite to the API
        print(f"year {year}: +{len(rows) - year_rows_before} rows, total so far = {len(rows)}, errors so far = {len(errors)}")

    out_path = f"{OUT_ROOT}/census_income_raw.csv"
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["zip_code", "year", "median_household_income"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved {len(rows)} rows to {out_path}")
    if errors:
        print(f"\n{len(errors)} batch errors (expected for 2009/2010 -- see docstring):")
        for e in errors[:30]:
            print(" ", e)
    print("DONE")


if __name__ == "__main__":
    main()
