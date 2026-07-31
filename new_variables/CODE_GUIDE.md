# CODE_GUIDE — project structure, file map, and how to run everything

This file explains **how the code fits together and how to run it**. For what each
variable means, how it was computed, its limitations, and verification results, see
`README.md` in this same folder — that's the detailed narrative documentation. This file
is the map.

---

## 1. The big picture

There are two separate stages to this whole project, in two different folders:

```
/Users/MANMEETSANTRE/Desktop/restaurantri/YelpJSON/     <- Stage 1: original R pipeline (36 columns)
/Users/MANMEETSANTRE/Downloads/restaurant-agglomeration-main/new_variables/  <- Stage 2: this folder (Python, +34 more columns)
```

**Stage 1** (not this folder — done separately, in R): takes the raw Yelp Open Dataset
(`yelp_academic_dataset_*.json`) and builds a weekly restaurant-survival panel for 5
cities (Tucson, Tampa, Indianapolis, Nashville, Philadelphia) plus a merged file, with 36
columns — Table 3 variables from the source paper, plus extra Yelp fields, plus
neighbor/competition variables. Output: `LATEST_<City>_FULL_DATA.csv` /
`LATEST_t_data_<City>.RData`, one pair per city plus `AllCities_MERGED`, saved in
`YelpJSON/`. This is the read-only starting point for everything in this folder — nothing
here ever modifies those files.

**Stage 2** (this folder, `new_variables/`, all Python): copies of those same 6 datasets,
with new variables added on top, one script per variable (or variable group), each
verified not to touch the original columns. Currently at **70 columns** (36 original + 34
added here: 3 cluster heterogeneity + 3 local heterogeneity + 1 income + 2 POI +
8 POI-count + 6 accessibility + 2 advantage/diversity + 6 multi-scale/anchor + 3 churn).

## 2. File map — what's in this folder and what it's for

| File | Type | What it does |
|---|---|---|
| `README.md` | docs | Full narrative: what each variable means, methodology, limitations, verification results, numbers |
| `CODE_GUIDE.md` | docs | This file — structure and how-to-run |
| `LATEST_<City>_FULL_DATA.csv` | data | The actual working dataset per city, 43 columns, this is the thing you'd open/analyze |
| `LATEST_t_data_<City>.RData` | data | Same data, R format (for opening in R instead of Python) |
| `LATEST_AllCities_MERGED_FULL_DATA.csv` / `.RData` | data | All 5 cities combined into one file |
| `compute_heterogeneity.py` | script | Adds `venue_type_heterogeneity`, `cuisine_heterogeneity`, `service_style_heterogeneity` |
| `compute_local_heterogeneity.py` | script | Adds `local_venue_type_heterogeneity`, `local_cuisine_heterogeneity`, `local_service_style_heterogeneity` |
| `pull_census_income.py` | script | Downloads raw income data from the Census Bureau's API, saves `census_income_raw.csv` |
| `census_income_raw.csv` | data | Raw pulled Census data (zip code, year, income) — kept for reproducibility, not a final variable itself |
| `build_income_variable.py` | script | Adds `median_household_income` to all 6 datasets, using `census_income_raw.csv` |
| `pull_osm_poi.py` | script | Downloads POI locations (malls, attractions, museums, parks, etc.) for the 5 cities from OpenStreetMap's free Overpass API — **no API key needed** — saves `osm_poi_raw.csv` |
| `osm_poi_raw.csv` | data | Raw POI reference data (city, category, name, lat/long) |
| `build_poi_variables.py` | script | Adds `dist_nearest_mall` and `n_tourist_spots_1km` to all 6 datasets, using `osm_poi_raw.csv` |
| `build_poi_count_variables.py` | script | Adds per-category POI counts within 1 km (`n_malls_1km`, `n_museums_1km`, `n_attractions_1km`, `n_parks_1km`, `n_universities_1km`, `n_stadiums_1km`), `n_poi_1km` (total), and `avg_neigh_n_poi_1km` (neighbour aggregate) |
| `build_accessibility_variables.py` | script | Adds distance-decay (Hansen index) accessibility scores: `amenity_access`, `mall_access`, `university_access`, `tourist_access`, `park_access`, `competition_access` |
| `build_advantage_diversity_variables.py` | script | Adds `poi_advantage` (own `n_poi_1km` − neighbour average — the distinct relative-position variable) and `poi_diversity` (Shannon entropy of nearby POI-type mix) |
| `build_multiscale_anchor_variables.py` | script | Adds multi-scale catchment counts (`n_poi_500m`, `n_poi_3km`) and anchor×competition (`near_mall`, `near_university`, `mall_competition_interaction`, `university_competition_interaction`) |
| `build_churn_variables.py` | script | Adds the time-varying local churn (`local_openings_1yr`, `local_closings_1yr`, `local_churn_1yr`) — nearby restaurant openings/closings in the trailing 52 weeks |
| `fit_survival_model.py` | script (analysis) | Fits the Cox proportional-hazards survival model to each of the 6 datasets; writes `survival_results_<city>.csv` + `survival_results_ALL_TABLE.csv`. **Does NOT modify the data files** — it's the analysis step, not a column-adding step. Needs `lifelines` (`pip install lifelines`). |
| `survival_results_*.csv` | data (output) | Hazard-ratio tables from the survival model |
| `local_revenue.py` | script | Pre-existing script (not written as part of this work), computes a `local_revenue` field — **not yet re-run against the current 43-column files** |

## 3. Where each variable actually comes from

| Variable | Built by | Reads from |
|---|---|---|
| `venue_type_heterogeneity`, `cuisine_heterogeneity`, `service_style_heterogeneity` | `compute_heterogeneity.py` | `../../Desktop/restaurantri/YelpJSON/business_<City>.RData` (raw categories, lat/lon), `yelp_academic_dataset_business.json` (raw iteration order) |
| `local_venue_type_heterogeneity`, `local_cuisine_heterogeneity`, `local_service_style_heterogeneity` | `compute_local_heterogeneity.py` | same `business_<City>.RData` files |
| `median_household_income` | `pull_census_income.py` then `build_income_variable.py` | `business_<City>.RData` (for zip codes), Census Bureau's live API (for income) |
| `dist_nearest_mall`, `n_tourist_spots_1km` | `pull_osm_poi.py` then `build_poi_variables.py` | `business_<City>.RData` (restaurant lat/lon), OpenStreetMap Overpass API (POI lat/lon) |
| `n_malls_1km` … `n_stadiums_1km`, `n_poi_1km`, `avg_neigh_n_poi_1km` | `build_poi_count_variables.py` | `osm_poi_raw.csv` + `business_<City>.RData` (restaurant lat/lon) |
| `amenity_access`, `mall_access`, `university_access`, `tourist_access`, `park_access`, `competition_access` | `build_accessibility_variables.py` | `osm_poi_raw.csv` + `business_<City>.RData` (restaurant lat/lon) |
| `poi_advantage`, `poi_diversity` | `build_advantage_diversity_variables.py` | existing columns (`n_poi_1km`, `avg_neigh_n_poi_1km`) + `osm_poi_raw.csv` |
| `n_poi_500m`, `n_poi_3km`, `near_mall`, `near_university`, `mall_competition_interaction`, `university_competition_interaction` | `build_multiscale_anchor_variables.py` | `osm_poi_raw.csv` + existing columns (`n_malls_1km`, `n_universities_1km`, `num_neighbors`) |
| `local_openings_1yr`, `local_closings_1yr`, `local_churn_1yr` | `build_churn_variables.py` | each city's panel (`business_id`, `week`, `is_open`) + `business_<City>.RData` (restaurant lat/lon) |

None of these scripts touch the original `business_<City>.RData` or the original
`LATEST_<City>_FULL_DATA.csv` files in `YelpJSON/` — they only read from there, and only
ever write into this `new_variables/` folder.

## 4. How to run everything from scratch

### 4.1 One-time setup

You need Python 3 with a few libraries that aren't part of a typical install, because we
need to read/write R's `.RData` format without using R itself:

```bash
python3 -m venv pyenv                     # create an isolated environment (recommended)
source pyenv/bin/activate
pip install pandas numpy rdata pyreadr
```

- `rdata` — reads `.RData` files (used to pull raw fields out of `business_<City>.RData`)
- `pyreadr` — writes `.RData` files back out (so the outputs work in R too)
- Everything else (`pandas`, `numpy`) does the actual computation

For the income variable specifically, you also need a free Census API key:
1. Sign up at https://api.census.gov/data/key_signup.html (instant, no cost)
2. Set it as an environment variable before running any income script:
   ```bash
   export CENSUS_API_KEY=your_key_here
   ```

### 4.2 Run order

The scripts must run in this order, because each one reads the *previous* script's
output (they add columns on top of whatever's already there):

```
1. compute_heterogeneity.py         (36 cols -> 39 cols)
2. compute_local_heterogeneity.py   (39 cols -> 42 cols)
3. pull_census_income.py            (produces census_income_raw.csv, no column changes)
4. build_income_variable.py         (42 cols -> 43 cols)
5. pull_osm_poi.py                  (produces osm_poi_raw.csv, no column changes; no API key needed)
6. build_poi_variables.py           (43 cols -> 45 cols)
7. build_poi_count_variables.py     (45 cols -> 53 cols)
8. build_accessibility_variables.py (53 cols -> 59 cols)
9. build_advantage_diversity_variables.py (59 cols -> 61 cols)
10. build_multiscale_anchor_variables.py (61 cols -> 67 cols)
11. build_churn_variables.py            (67 cols -> 70 cols)
12. fit_survival_model.py               (ANALYSIS — fits the Cox model; writes survival_results_*.csv; does not change the data)
```

```bash
cd new_variables
python compute_heterogeneity.py
python compute_local_heterogeneity.py
python pull_census_income.py          # needs CENSUS_API_KEY set
python build_income_variable.py
```

Each script is **safe to re-run** — they all check for and drop their own
previously-added columns before recomputing, so running one twice won't create
duplicate columns or break anything.

### 4.3 What each script prints

Every script prints per-city progress and a final summary (row counts, NA counts,
verification checks) as it runs — that output is what the numbers in `README.md`'s
"Results" sections come from. If you re-run a script, compare its printed numbers
against `README.md` to confirm nothing changed unexpectedly.

## 5. Adding a new variable (for whoever picks this up next)

The pattern every script here follows, if you're adding another one:

1. Read whatever raw source you need (usually `business_<City>.RData`, sometimes an
   external source like the Census API).
2. Compute the new column(s) **in memory** — never write intermediate results back into
   the original source files.
3. Load the *current* `LATEST_<City>_FULL_DATA.csv` from this folder (not from
   `YelpJSON/` — always build on top of the latest state in this folder).
4. Drop the column(s) you're about to add if they already exist (makes the script
   re-runnable).
5. Merge your new column(s) on `business_id` (and `week`/`year` if the variable varies
   over time, not just per-restaurant).
6. Verify: row count unchanged, no duplicate `(business_id, week)` rows, no NAs beyond
   what you expect and can explain, original columns byte-identical to before.
7. Save both `.csv` and `.RData` (`pyreadr.write_rdata(path, df, df_name="t_data",
   compress="gzip")`).
8. Document it in `README.md`: source, methodology, any limitations/assumptions, and the
   verification results with real numbers — not just "done."

## 6. Known outstanding items

- `local_revenue.py` exists in this folder but was **not** written as part of this
  batch of work, and hasn't been re-run against the current 43-column files — check with
  whoever added it before relying on its output.
- Variables from the previous intern's codebase not yet recreated here: review/checkin
  rates (`extend_compdata.py`), tip rates (`extend_tips.py`), multi-label category
  bitstrings (`extend_newcategorymapping.py`), sentiment scores
  (`sentiment_reviews.py`/`sentiment_tips.py`). See the previous intern's own
  `restaurant-agglomeration-main` repo (one level up from this folder) for that original
  code, kept only for reference — nothing in that outer folder should be treated as
  current/authoritative data.
