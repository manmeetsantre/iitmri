# new_variables — record of variables added on top of the prepared 5-city + merged data

This folder holds the working copies of the 5 individual-city datasets plus the merged
all-cities dataset (originally prepared in `/Users/MANMEETSANTRE/Desktop/restaurantri/YelpJSON/`,
one `.RData` + `.csv` pair per city, plus `AllCities_MERGED`). New variables are added
to these copies here, with each addition logged below.

Files in this folder:
- `LATEST_<City>_FULL_DATA.csv` / `LATEST_t_data_<City>.RData` for Tucson, Tampa,
  Indianapolis, Nashville, Philadelphia
- `LATEST_AllCities_MERGED_FULL_DATA.csv` / `LATEST_t_data_AllCities_MERGED.RData`
- `local_revenue.py` — a standalone script (not yet re-run against the current files)
- `compute_heterogeneity.py` — computes the cluster-based heterogeneity variables
  (classification, clustering, heterogeneity, merge, verification) end to end
- `compute_local_heterogeneity.py` — computes the local heterogeneity variables
  (per-restaurant neighborhood, merge, verification) end to end
- `pull_census_income.py` — pulls median household income from the Census ACS API
  and saves `census_income_raw.csv` (run this first)
- `build_income_variable.py` — merges `census_income_raw.csv` onto all 6 datasets by
  zip code + year (run this second)
- `census_income_raw.csv` — the raw pulled Census data (zip_code, year,
  median_household_income), kept here for reproducibility/audit

See `CODE_GUIDE.md` in this folder for the full project structure, how each script
fits together, and setup/run instructions.

All 6 variables below were computed **entirely in Python** (`pandas` + `numpy`), not R.
The only place R's `.RData` file format is touched at all is *reading/writing the file
container* — done with the `rdata` library (to read the raw `business_<City>.RData`
fields) and `pyreadr` (to write the updated `t_data` back out as `.RData`). No R code
was executed and no R computation happened anywhere; all classification, clustering,
and heterogeneity math is plain Python.

---

## Cluster-based heterogeneity: `venue_type_heterogeneity`, `cuisine_heterogeneity`, `service_style_heterogeneity`

Recreated from the previous intern's `build_compdata.py`. Source: raw Yelp `categories`
and `latitude`/`longitude` fields from each city's `business_<City>.RData`, classified
using the exact `VENUE_TYPE_MAP` / `CUISINE_MAP` / `SERVICE_STYLE_MAP` dictionaries from
his `categories.py`.

Only these 3 heterogeneity scores are kept as final variables. Computing them requires
two intermediate steps — single-label classification (`venue_type`, `cuisine`,
`service_style`) and spatial clustering (`cluster_id`) — but those intermediate values
are not themselves meaningful model variables (they're re-labelings of existing category
data, or an arbitrary grouping key), so they are computed, used, and dropped rather than
kept as columns.

**Classification** — single-label: for each restaurant, iterate the map's groups **in
order** (same order as `categories.py`); the first group containing any of the
restaurant's raw Yelp category tags wins. `venue_type` falls back to "Other" if none
match (no catch-all group in that map); `service_style` falls back to
"Fine_Casual_Dining" (its catch-all covers any restaurant tagged "Restaurants", i.e.
effectively every restaurant).

**Clustering (`cluster_id`)** — greedy single-pass spatial clustering, replicating
`build_compdata.py`'s `cluster_restaurants()` exactly: restaurants are processed one at a
time **in the same order they appear in the raw Yelp business JSONL dump**
(`yelp_academic_dataset_business.json`, loaded once and used to sort every city's
restaurant list before clustering); each not-yet-assigned restaurant becomes the seed of
a new cluster and absorbs every other not-yet-assigned restaurant within **1000m**
(haversine distance, Earth radius **6,371,000m** — matching the previous intern's
constant exactly) of it. This is a greedy/order-dependent method, not a rigorous
clustering algorithm — two restaurants 999m apart could end up in different clusters if
a closer seed claimed one of them first. Clustering is done **per city** (restaurants in
different cities are always >>1000m apart); cluster IDs are offset to stay globally
unique before computing the merged file's heterogeneity scores.

Both the iteration order and the Earth radius constant were corrected to match
`build_compdata.py` exactly (an earlier version of this script used
alphabetical-by-business_id order and R's `geosphere` default radius of 6,378,137m
instead — both have since been fixed so the methodology is identical to the previous
intern's original, not just close to it).

`venue_type_heterogeneity`, `cuisine_heterogeneity`, `service_style_heterogeneity` are
then computed per cluster as:

```
heterogeneity = |intersection of all members' labels| / |union of all members' labels|
```

i.e. 1 if every restaurant in the cluster shares the identical label (fully homogeneous),
down toward 0 as the cluster's members have more different labels. Despite the name
"heterogeneity," a **higher** value means **more uniform** (this matches the previous
intern's naming, which is a bit counter-intuitive). Computed separately for `venue_type`,
`cuisine`, and `service_style` using each restaurant's own cluster's members, and
broadcast to every restaurant in that cluster.

### Verification performed
- Zero NAs introduced by the join.
- No duplicate `(business_id, week)` rows introduced.
- Row counts unchanged from the pre-existing prepared files.
- Cluster counts stayed identical (207/213/242/154/173) after correcting the iteration
  order and Earth radius constant — confirming the fix was a legitimate refinement, not
  something that silently broke the clustering.

### Results (this run, 2026-07-11 — corrected iteration order/radius; originally computed 2026-07-06)

| City | Restaurants | Clusters (1000m, intermediate only) | Panel rows (unchanged) |
|---|---|---|---|
| Tucson | 2,466 | 207 | 980,154 |
| Tampa | 2,960 | 213 | 994,295 |
| Indianapolis | 2,862 | 242 | 1,056,248 |
| Nashville | 2,502 | 154 | 875,723 |
| Philadelphia | 5,852 | 173 | 2,193,439 |
| **AllCities_MERGED** | 16,642 | 989 (globally unique, offsets sum correctly) | 6,099,859 |

---

## Local heterogeneity: `local_venue_type_heterogeneity`, `local_cuisine_heterogeneity`, `local_service_style_heterogeneity`

Recreated from the previous intern's `extend_local_heterogeneity.py`. Same raw source
data and same classification dictionaries as above, but a genuinely **different**
heterogeneity measure — not a duplicate of the cluster-based variables.

### How this differs from the cluster-based variables

| | Cluster-based (`*_heterogeneity`) | Local (`local_*_heterogeneity`) |
|---|---|---|
| Neighborhood definition | Fixed, shared cluster (restaurants are grouped once; everyone in a cluster shares it) | Each restaurant's own personal 1000m circle, centered on itself |
| Two nearby restaurants can get different scores? | No — if they're in the same cluster, same score | Yes — each one's circle can catch a different set of neighbors |
| Value type | Graded ratio (0 to 1, e.g. 0.6) | Strict flag: exactly 1.0 or 0.0 |
| Meaning of 1.0 | Every member of this restaurant's cluster has the identical label | Every restaurant within 1000m of this one (including itself) has the identical label |
| Isolated restaurant (no one else nearby) | Its own 1-member cluster → 1.0 | No neighbors within 1000m → trivially 1.0 (nothing nearby disagrees) |

For each restaurant, find every restaurant (itself included) within **1000m** (haversine
distance, Earth radius **6,371,000m**, matching `extend_local_heterogeneity.py` exactly).
Then:

```
local_heterogeneity = 1.0  if every restaurant in that 1000m circle has the identical label
                     = 0.0  otherwise (even one different neighbor makes it 0)
```

Computed separately for `venue_type`, `cuisine`, `service_style`, using each
restaurant's own neighborhood (not a shared cluster).

### Verification performed
- Zero NAs introduced by the join.
- No duplicate `(business_id, week)` rows introduced.
- Row counts and all pre-existing columns unchanged (confirmed via exact value
  comparison, not just row counts).
- All 3 new columns contain only 0.0 or 1.0.

### Results (this run, 2026-07-09)

| City | Restaurants | Isolated (no neighbor within 1000m) | % venue_type local-homogeneous | % cuisine local-homogeneous | % service_style local-homogeneous |
|---|---|---|---|---|---|
| Tucson | 2,466 | 27 | 2.0% | 1.4% | 2.5% |
| Tampa | 2,960 | 25 | 1.3% | 1.1% | 1.6% |
| Indianapolis | 2,862 | 29 | 2.8% | 1.3% | 1.7% |
| Nashville | 2,502 | 24 | 2.1% | 1.1% | 1.4% |
| Philadelphia | 5,852 | 8 | 0.3% | 0.1% | 0.3% |

These percentages are low because the flag requires **every single** nearby restaurant
to match — in a dense area with many different competitors nearby, it only takes one
different neighbor to flip a restaurant to 0.

---

## Current state of all 6 files

Every dataset now has **42 columns**: the original 36 (Table 3 + extra Yelp variables +
neighbor variables) + the 3 cluster-based heterogeneity scores + the 3 local
heterogeneity scores. Both `.csv` and `.RData` are up to date and in sync for all 6
datasets (Tucson, Tampa, Indianapolis, Nashville, Philadelphia, AllCities_MERGED).

Verified with no manipulation of the original 36 columns: every value in those columns
matches the original source files in `YelpJSON/` exactly (row-order-preserving for the
5 individual cities; exact match after sorting by `business_id`+`week` for
`AllCities_MERGED`, whose row order differs from the source only because of a documented,
harmless R `merge()` sort that happened in an earlier processing step — no values were
changed).

Full data-quality audit (2026-07-12) across all 6 files: 0 NAs, 0 duplicate
`(business_id, week)` rows, 0 fully duplicate rows, 0 unexpected `state`/`city` values,
0 malformed `business_id`s, all binary columns strictly 0/1, all ratio columns within
[0,1], all count columns non-negative, 0 `Inf` values. Only zero-variance columns are
`state`/`city` (expected — each city file covers one city) and `week_start` (a known
constant reference value).

---

## Median household income: `median_household_income`

**Source**: U.S. Census Bureau, American Community Survey (ACS) 5-Year estimates,
table `B19013` ("Median Household Income in the Past 12 Months"), pulled directly from
`api.census.gov` by ZIP Code Tabulation Area (ZCTA), one query per year. Not from the
Kaggle "US Household Income Statistics" dataset — that one is a frozen 2017-era snapshot
(single year, no updates since) and, when checked directly, only covered 160 of our 225
zip codes (71%) vs. Census's much higher coverage below. Not from the 1-Year ACS product
either — tested directly and confirmed it doesn't support zip-code-level geography at
all (only large areas with 65,000+ population), so 5-Year is the only ACS product usable
at zip-code granularity.

**API bug found and fixed along the way**: years 2009–2019 initially returned zero data
for every single query (`HTTP 400: ambiguous geography`). Root cause, found via direct
testing: those years require the ZCTA query to be qualified with a parent state
(`&in=state:XX`); 2020+ allows querying ZCTA directly. Fixed by grouping our zip codes by
their real state (FIPS: AZ=04, FL=12, IN=18, TN=47, PA=42) and querying state-by-state
for years before 2020.

**Zip-code join methodology**: a `business_id → zip_code` lookup was built from each
city's raw `business_<City>.RData` (`postal_code` field), with one correction applied
in-memory only (not to the source file): **Apna Kabab House**
(`business_id = Jfi-hoD-hKlnu3LljlEUqA`, Tampa) has `postal_code = 336140` (6 digits) in
Yelp's own original data — a data-entry typo (extra trailing zero) — corrected to
`33614` for matching purposes. The 9 food-truck `business_id`s with no address in Yelp's
own data (see Batch 1 above) keep no zip code, so they get no income value — not
fabricated. Each panel row's calendar year was derived from its `week` number using the
same date formula the original R pipeline uses. `median_household_income` was then
merged in by **exact match** on `(zip_code, year)`.

**Policy: exact match only, no imputation.** Per instruction, wherever there's no exact
`(zip_code, year)` match, `median_household_income` is left blank (`NA`) — no filling
with a nearby year's value, no interpolation. Imputation, if wanted, is left for model-
fitting time, not baked into the data. This covers 3 disclosed, real limitations:

1. **2005–2010 have no matching Census data at all** (≈11.6% of all panel rows,
   dataset-wide). Confirmed 2009 and 2010 don't support ZCTA-level queries at all in the
   API — tested with random zip codes, not just ours, and none worked for those two
   specific years (real ZCTA-level access starts at the 2011 release); 2005–2008 predate
   the ACS 5-Year product entirely.
2. **73 restaurants (20 zip codes) never have Census income data, in any year 2011–2024**
   — traced to these being P.O. Box / administrative zip codes with no residential
   population (confirmed: e.g. zip `19101` returns nothing for even a basic name lookup,
   while its neighbor `19102` works fine) — Census structurally never measures income
   where nobody lives, this isn't a searching failure.
3. **113 (zip, year) pairs where Census's own value was its official "not a reliable
   estimate" sentinel code** (`-666666666`, used for small-sample ZCTAs) — treated as
   missing, not as literal negative income.

### Verification performed
- Row counts unchanged in all 6 files (columns-only addition).
- All 42 previously-existing columns confirmed byte-identical (exact value comparison
  against a pre-change backup for Tucson; same drop-and-remerge logic applied uniformly
  to all 6, so this generalizes).
- Zero duplicate `(business_id, week)` rows.
- Zero sentinel (`-666666666`) values present anywhere in the final column — confirmed
  by explicit check, not just by absence of complaints.
- `.csv` and `.RData` confirmed in sync (same shape, same columns, same NA count).

### Results (this run, 2026-07-15)

| City | Rows | `median_household_income` NAs | Income range (non-NA) |
|---|---|---|---|
| Tucson | 980,154 | 122,268 (12.47%) | $23,769 – $114,201 |
| Tampa | 994,295 | 85,295 (8.58%) | $23,632 – $152,044 |
| Indianapolis | 1,056,248 | 97,491 (9.23%) | $23,203 – $250,001 |
| Nashville | 875,723 | 105,979 (12.10%) | $15,286 – $150,132 |
| Philadelphia | 2,193,439 | 330,682 (15.08%) | $14,185 – $161,554 |
| **AllCities_MERGED** | 6,099,859 | 741,715 (12.16%) | $14,185 – $250,001 |

Philadelphia's NA rate is highest because 46 of the 73 zero-coverage restaurants (P.O.
Box zips) are there. NA rates are otherwise close to the ~11.6% baseline expected purely
from the 2005–2010 gap, confirming nothing unexpected is inflating them.

Every dataset went from 42 → **43 columns**.

---

## POI (points of interest) reference data: `osm_poi_raw.csv` — no dataset columns yet

**Status: raw reference data only.** This pull produced a standalone CSV of POI
locations; **no new columns have been added to the 6 datasets from it yet** —
restaurant-level variables built from it (e.g. distance to nearest mall) are the next
step, pending discussion.

**Source**: OpenStreetMap, via the free Overpass API (`overpass-api.de`) — no API key,
no account, no cost. Chosen over Google Places API (needs a credit card + billing
account even for its free tier) and Foursquare (free tier nearly eliminated from June
2026). Google Places' free tier remains available as a backup to fill gaps if any
category's coverage proves too thin.

**What was pulled**: for each of the 5 cities, every OSM feature inside the city's
official municipal boundary (`admin_level=8` area) matching these 8 categories:

| Our category | OSM tag |
|---|---|
| mall | `shop=mall` |
| attraction | `tourism=attraction` |
| museum | `tourism=museum` |
| zoo | `tourism=zoo` |
| theme_park | `tourism=theme_park` |
| stadium | `leisure=stadium` |
| university | `amenity=university` |
| park | `leisure=park` (named parks only — unnamed ones are tiny green patches) |

Each row: `city, category, name, latitude, longitude, osm_type, osm_id`. For area
features (a mall building, a park polygon), the coordinates are the feature's geometric
center point (Overpass `out center`).

**Disclosed limitations**:
- OSM is crowd-sourced (volunteer-mapped). Coverage in big US cities is good but not
  guaranteed complete.
- The `attraction` tag is loose — it includes small items (street murals, memorial
  aircraft) alongside genuinely major tourist spots. Filter or weight by category when
  building model variables.
- 83 of 1,851 POIs (~4.5%) have no name filled in (mostly small mall-tagged plazas);
  their coordinates are still valid, which is what matters for distance calculations.
- "City" = the official municipal boundary; POIs just outside city limits (suburban
  malls etc.) are not included.

### Verification performed
- 0 missing latitude/longitude values.
- 0 duplicate `(osm_type, osm_id)` rows.
- Spot-checked real landmarks come back with correct coordinates (e.g. Liberty Bell,
  Reading Terminal in Philadelphia; Tucson Mall, Park Place Mall in Tucson).
- Counts consistent with an earlier independent spot-test run (slightly higher here
  because `relation`-type OSM features are also included).

### Results (this run, 2026-07-18) — 1,851 POIs total

| City | mall | attraction | museum | zoo | theme_park | stadium | university | park | Total |
|---|---|---|---|---|---|---|---|---|---|
| Tucson | 13 | 42 | 21 | 1 | 2 | 12 | 49 | 150 | 290 |
| Tampa | 12 | 52 | 16 | 3 | 9 | 9 | 7 | 137 | 245 |
| Indianapolis | 14 | 12 | 22 | 1 | 0 | 12 | 13 | 287 | 361 |
| Nashville | 12 | 17 | 23 | 3 | 0 | 7 | 13 | 219 | 294 |
| Philadelphia | 11 | 39 | 96 | 1 | 0 | 12 | 36 | 466 | 661 |

---

## POI variables: `dist_nearest_mall`, `n_tourist_spots_1km`

Two restaurant-level variables built from `osm_poi_raw.csv` (above) and merged onto all
6 datasets. Both are **static** — one value per restaurant, repeated across that
restaurant's weekly rows (a restaurant doesn't move, and the POIs are treated as fixed).

- **`dist_nearest_mall`** — straight-line (haversine) distance, in **meters**, from the
  restaurant to the closest `shop=mall` POI **in the same city**. Idea: being near a mall
  may bring foot traffic / anchor-tenant spillover that helps a restaurant survive.
- **`n_tourist_spots_1km`** — **count** of tourist POIs within **1000 m** of the
  restaurant. "Tourist POIs" = the OSM categories `attraction` + `museum` + `zoo` +
  `theme_park` (parks, stadiums, universities and malls are deliberately excluded — parks
  alone would swamp the count, and malls have their own variable). Idea: tourist density
  is a proxy for a high-footfall destination area. 1000 m matches the neighbor/cluster
  radius used by the earlier variables, for consistency.

### Method
1. Restaurant coordinates (`latitude`/`longitude`) come from the raw
   `business_<City>.RData` files — present for every restaurant, including the food
   trucks (they have a point location even without a street address / zip).
2. POI coordinates come from `osm_poi_raw.csv`.
3. Per city, a haversine distance matrix (restaurants × POIs) is computed, Earth radius
   **6,371,000 m** (same constant as the heterogeneity scripts).
4. `dist_nearest_mall` = row-minimum over that city's malls;
   `n_tourist_spots_1km` = row-count of that city's tourist POIs at distance ≤ 1000 m.
5. Merged onto the 6 datasets by `business_id`.

### Disclosed limitations
- **Straight-line distance**, not walking/driving distance — a mall 400 m away across a
  highway is still recorded as 400 m.
- POIs are only those **inside the city's municipal boundary** (from the OSM pull). A
  restaurant near the city edge whose nearest real mall sits just across the city line
  will get an inflated `dist_nearest_mall` (nearest *in-city* mall instead).
- `n_tourist_spots_1km` inherits the loose OSM `attraction` tag — small items (murals,
  memorial aircraft) count the same as major attractions. It's a density proxy, not a
  curated "major landmarks" count.
- Both are computed against the **current** OSM snapshot (2026), applied uniformly across
  all panel years — POIs aren't time-varying, so a museum that opened in 2015 is counted
  for a restaurant's 2011 rows too. Acceptable for a location-context proxy; noted for
  transparency.

### Verification performed
- Row counts unchanged in all 6 files; went 43 → **45 columns**.
- Zero NAs in both new columns (every restaurant has coordinates; every city has ≥ 11
  malls, so `dist_nearest_mall` always resolves).
- Zero duplicate `(business_id, week)` rows.
- The previous 43 columns confirmed unchanged (drop-and-remerge on `business_id`, verified).
- `.csv` and `.RData` confirmed in sync (same shape/cols, values match).
- **Independent recompute check**: for sample restaurants, both variables were
  recomputed from scratch with a separate loop and matched the stored values exactly
  (e.g. a Tucson restaurant: `dist_nearest_mall` 12457.7 m both ways).

### Results (this run, 2026-07-21)

| City | Malls | Tourist POIs | `dist_nearest_mall` median | `dist_nearest_mall` range | `n_tourist_spots_1km` mean | max |
|---|---|---|---|---|---|---|
| Tucson | 13 | 66 | 3,568 m | 1 – 29,578 m | 1.64 | 17 |
| Tampa | 12 | 80 | 2,495 m | 4 – 22,907 m | 0.95 | 40 |
| Indianapolis | 14 | 35 | 3,532 m | 2 – 13,087 m | 1.22 | 13 |
| Nashville | 12 | 43 | 5,172 m | 4 – 20,785 m | 2.33 | 15 |
| Philadelphia | 11 | 136 | 1,509 m | 3 – 21,909 m | 7.83 | 45 |

Philadelphia stands out — smallest median mall distance and by far the highest tourist
density (7.83 tourist spots within 1 km on average), consistent with a dense, walkable
downtown. Nashville has the largest median mall distance, consistent with a more
spread-out metro.

---

## POI count variables (per category + total + neighbour aggregate)

Eight variables answering mam's request: "how many malls, university, etc are close by,
same for neighbour restaurants." All merged onto the 6 datasets; **static** per
restaurant (repeated across weekly rows).

**Per-category counts within 1000 m** (haversine, Earth radius 6,371,000 m; POIs from
`osm_poi_raw.csv`, restaurant coordinates from `business_<City>.RData`):

- `n_malls_1km` — # of malls within 1 km
- `n_museums_1km` — # of museums within 1 km
- `n_attractions_1km` — # of tourist attractions within 1 km
- `n_parks_1km` — # of named parks within 1 km
- `n_universities_1km` — # of universities within 1 km
- `n_stadiums_1km` — # of stadiums within 1 km

**Total:**
- `n_poi_1km` — # of POIs of **any** of the 8 OSM categories within 1 km (the six above
  plus zoo and theme_park; so `n_poi_1km` ≥ any single category count, always).

**Neighbour aggregate** ("same for neighbour restaurants"):
- `avg_neigh_n_poi_1km` — for each restaurant, the **mean `n_poi_1km` of its neighbouring
  restaurants** (other restaurants within 1000 m, self excluded). Captures whether a
  restaurant sits inside a cluster that is collectively in an amenity-rich area.
  **NaN** for restaurants with no neighbour within 1000 m (genuinely undefined — nothing
  to average). Isolated-restaurant counts: Tucson 27, Tampa 25, Indianapolis 29,
  Nashville 24, Philadelphia 8 (matching the local-heterogeneity isolated counts).

### Honest caveat on the neighbour variable
`avg_neigh_n_poi_1km` is **strongly correlated with a restaurant's own `n_poi_1km`** —
neighbours within 1 km mostly see the same POIs, so a restaurant's neighbourhood-average
POI exposure closely tracks its own. It is included because it was explicitly requested,
but for modelling, a *difference* form (`n_poi_1km − avg_neigh_n_poi_1km`, i.e. "am I
better-located than my neighbours") would carry more independent signal. Noted for
whoever runs the model.

### Verification performed
- Row counts unchanged in all 6 files; went 45 → **53 columns**.
- Zero NAs in all 7 count columns (every restaurant has coordinates; counts always resolve).
- `avg_neigh_n_poi_1km` NAs confirmed = isolated-restaurant rows only, and the merged
  file's NA rows (36,875) exactly equal the sum of the 5 individual city files — i.e. no
  spurious NAs.
- `n_poi_1km ≥ every individual category count` for every row (a total-vs-parts sanity
  check); no negative counts anywhere.
- Zero duplicate `(business_id, week)` rows; previous 45 columns unchanged; `.csv` /
  `.RData` in sync (verified).
- **Independent recompute check**: a from-scratch brute-force count for a sample
  restaurant matched the vectorized count exactly.

### Results (this run, 2026-07-22) — per-restaurant means, counts within 1 km

| City | n_poi_1km (mean / max) | malls | museums | attractions | parks | universities | stadiums |
|---|---|---|---|---|---|---|---|
| Tucson | 5.33 / 50 | 0.26 | 0.86 | 0.72 | 1.99 | 1.29 | 0.15 |
| Tampa | 3.87 / 44 | 0.23 | 0.53 | 0.39 | 2.41 | 0.20 | 0.09 |
| Indianapolis | 5.39 / 39 | 0.26 | 0.63 | 0.59 | 3.31 | 0.23 | 0.38 |
| Nashville | 7.68 / 36 | 0.14 | 1.69 | 0.60 | 4.52 | 0.31 | 0.38 |
| Philadelphia | 21.86 / 78 | 0.62 | 5.72 | 2.11 | 11.33 | 1.94 | 0.15 |

Philadelphia is far denser on every category (≈22 POIs within 1 km on average vs 4–8
elsewhere), consistent with a compact old-city core; parks dominate the counts
everywhere (they are the most-mapped OSM category).

### Same limitations as the other POI variables
Straight-line distance; POIs limited to each city's municipal boundary (edge restaurants
slightly undercounted); loose OSM `attraction` tag; current-snapshot POIs applied to all
panel years.

---

## Distance-decay accessibility variables (Hansen index)

Six variables that answer the criticism of the hard 1 km count: a place at 999 m counts
as 1 but one at 1001 m counts as 0, and a place at 100 m counts the same as one at 950 m.
Accessibility fixes both by giving every place a **closeness weight that fades smoothly
with distance**, then summing:

```
weight = exp( -distance / d0 )          d0 = 1000 m

  distance    weight
      0 m      1.00
   1000 m      0.37
   2000 m      0.14
   3000 m      0.05
```

accessibility = sum of these weights over the relevant set of places. Close places
contribute a lot, far places fade toward 0, no arbitrary cutoff. This is the **Hansen
(1959) accessibility index**, the standard measure in spatial economics.

The six variables differ only in *which places* they sum over:

| Variable | Sums the decay-weight over… |
|---|---|
| `amenity_access` | **all** POIs in the city (overall reachable amenity) |
| `mall_access` | `shop=mall` POIs |
| `university_access` | `amenity=university` POIs |
| `tourist_access` | `tourism` attraction + museum + zoo + theme_park POIs |
| `park_access` | named `leisure=park` POIs |
| `competition_access` | **other restaurants** (self excluded — see below) |

**Design choices (documented / defensible):**
- **d0 = 1000 m** — keeps these comparable with the existing 1 km count/neighbour
  variables, and 1 km is a normal walkable-neighbourhood scale.
- **Per-category (not one blended score)** — so a survival model can learn each POI
  type's own weight via its regression coefficient, rather than us hard-coding that (say)
  a mall matters more than a park.
- **`competition_access` self-exclusion** — a restaurant's distance to itself is 0, which
  would give weight 1 (counting itself as its own competitor). The diagonal of the
  restaurant×restaurant weight matrix is zeroed before summing.
- **`competition_access` is static** — it sums over *all* restaurants in the city, i.e. a
  location's restaurant-density. Time-varying *active* competition (who is open in a given
  week) is already a separate variable, `num_neighbors`. The two complement, not duplicate.
- Earth radius 6,371,000 m (same haversine constant as the other spatial scripts).

**Note on exact-zero values:** a small number of very remote restaurants (e.g. 40 in
Tucson; 0 in Indianapolis and Philadelphia) have `amenity_access = 0.0000`. This is **not
missing data** (there are zero NAs) — their nearest POI is ~10 km+ away, where
`exp(-d/1000)` rounds to 0 at 4 decimals. A ~0 accessibility for an outskirts restaurant
with no reachable amenities is the correct, intended value.

### Verification performed
- Row counts unchanged; went 53 → **59 columns**; zero NAs in all 6 columns; no negatives.
- `amenity_access ≥ every single-category access` for every row (a subset of POIs cannot
  out-sum the whole) — checked, holds everywhere.
- Zero duplicate `(business_id, week)` rows; previous 53 columns unchanged; `.csv`/`.RData`
  in sync (verified, values match).
- **Brute-force recompute** for a sample restaurant matched the vectorized value exactly
  (Tucson restaurant #5: 16.7607 both ways).
- **Closeness demonstration**: among restaurants with the *same* `n_poi_1km` count (e.g.
  count = 3), `amenity_access` ranged from 2.16 to 19.0 — i.e. it correctly distinguishes
  "3 POIs right next door" from "3 POIs near the 1 km edge", which the plain count cannot.
- **Correlation with `n_poi_1km` = 0.92** — high (they measure related things) but well
  below 1.0, confirming accessibility is the smoother relative of the count that carries
  extra closeness information rather than a duplicate.

### Results (this run, 2026-07-26) — per-restaurant accessibility

| City | `amenity_access` mean / max | `competition_access` mean / max |
|---|---|---|
| Tucson | 7.57 / 37.96 | 55.81 / 173.57 |
| Tampa | 5.48 / 32.77 | 65.80 / 203.67 |
| Indianapolis | 6.94 / 32.89 | 71.34 / 289.38 |
| Nashville | 9.31 / 28.45 | 117.10 / 333.90 |
| Philadelphia | 30.03 / 68.79 | 447.28 / 1088.83 |

Philadelphia dominates on both — highest reachable amenity and, by far, the highest
restaurant density (competition), consistent with its compact core.

### Same limitations as the other POI variables
Straight-line distance; POIs limited to each city's municipal boundary; current-snapshot
POIs applied to all panel years.

---

## Relative advantage & amenity diversity: `poi_advantage`, `poi_diversity`

Two more location variables, both static per restaurant.

### `poi_advantage` — is this restaurant better-located than its neighbours?

$$\text{poi\_advantage} = n\_poi\_1km - avg\_neigh\_n\_poi\_1km$$

Pure arithmetic on two existing columns (nothing recomputed). It measures whether *this*
spot has more nearby amenities than the *typical restaurant around it*:
- **positive** → better-located than its neighbours (the best spot in its micro-cluster);
- **negative** → its neighbours sit in more amenity-rich spots;
- **NaN** → only for restaurants with no neighbour within 1000 m (the same isolated
  restaurants for which `avg_neigh_n_poi_1km` is already NaN — "advantage over
  neighbours" is undefined when there are none). Verified the NaN rows match exactly.

**Why this is the *distinct* neighbour variable.** The earlier `avg_neigh_n_poi_1km`
was almost a copy of a restaurant's own `n_poi_1km` — measured correlation **0.976**.
Taking the *difference* cancels that shared level and isolates the relative-position
signal: `poi_advantage` correlates only **0.262** with `n_poi_1km`. So it carries genuinely
new information, where the raw neighbour-average mostly did not.

### `poi_diversity` — how many *different kinds* of places are nearby

Shannon entropy over the mix of the 8 OSM POI categories within 1000 m:

$$\text{poi\_diversity} = -\sum_c p_c \ln p_c, \qquad p_c = \frac{\text{count of category } c \text{ within 1km}}{\text{total POIs within 1km}}$$

Not "how many" (that's `n_poi_1km`) but "how varied". Two restaurants can both have 6
POIs nearby, but 6 parks → diversity ≈ 0, whereas mall+museum+park+university+attraction+
stadium → high diversity.

**Scale (for interpretation):** 0 = all one type (or no POIs nearby); even mix of 2 types
= ln 2 ≈ 0.69; even mix of 4 types = ln 4 ≈ 1.39; theoretical max with 8 categories =
ln 8 ≈ 2.079. The entropy formula was hand-verified on these anchor cases. Computed over
all 8 categories, so it is consistent with `n_poi_1km`. Correlation with `n_poi_1km` =
**0.786** — related to the count but clearly a distinct construct (variety, not amount).

**Why it matters:** tests the Jacobs (1961) mixed-use hypothesis — an area with varied
amenities (offices + culture + retail + green space) sustains foot traffic across the
whole day, which should help restaurants survive.

### Verification performed
- Row counts unchanged; went 59 → **61 columns**.
- `poi_diversity`: 0 NAs, all values ≥ 0 and ≤ ln 8 (no impossible entropies).
- `poi_advantage`: NaN rows exactly equal the isolated-restaurant rows (matching
  `avg_neigh_n_poi_1km`); ~0.6 % of rows merged-file-wide.
- 0 duplicate `(business_id, week)` rows; previous 59 columns unchanged; `.csv`/`.RData`
  in sync (verified).
- Entropy formula hand-checked: all-one-type → 0, even-2 → 0.6931, even-4 → 1.3863,
  empty → 0.

### Results (this run, 2026-07-26)

| City | `poi_diversity` mean / max | restaurants with diversity 0 | `poi_advantage` range |
|---|---|---|---|
| Tucson | 0.330 / 1.472 | 1,562 | −17.2 … 17.4 |
| Tampa | 0.199 / 1.602 | 2,217 | −24.5 … 11.7 |
| Indianapolis | 0.250 / 1.632 | 2,114 | −12.6 … 11.4 |
| Nashville | 0.404 / 1.262 | 1,376 | −15.6 … 6.3 |
| Philadelphia | 0.677 / 1.515 | 1,902 | −26.8 … 21.1 |

Philadelphia has the richest amenity mix (highest mean diversity); the "diversity 0"
restaurants are those with either no POIs within 1 km or only a single POI type nearby.

---

## Multi-scale amenity catchment: `n_poi_500m`, `n_poi_3km`

The single 1 km radius mixes two different kinds of customer: people who **walk** over
(realistically a few hundred metres) and people who **drive** in (happy to come several
km). These two counts split that apart, using the same all-8-category POI count as
`n_poi_1km` but at a walk-in and a drive-to distance:

- `n_poi_500m` — POIs within **500 m** (the walk-in catchment)
- `n_poi_3km` — POIs within **3000 m** (the drive-to catchment)

By construction they bracket the existing count: `n_poi_500m ≤ n_poi_1km ≤ n_poi_3km`
for every restaurant (verified — a nesting sanity check). This lets a model test whether
walk-in proximity or regional draw matters more for survival, and whether that differs by
restaurant type — a distinction the single 1 km radius hides.

### Results (per-restaurant mean POIs)

| City | `n_poi_500m` | `n_poi_1km` | `n_poi_3km` |
|---|---|---|---|
| Tucson | 1.58 | 5.33 | 31.81 |
| Tampa | 1.37 | 3.87 | 22.91 |
| Indianapolis | 1.58 | 5.39 | 27.16 |
| Nashville | 2.79 | 7.68 | 35.92 |
| Philadelphia | 5.99 | 21.86 | 124.93 |

---

## Anchor × competition: `near_mall`, `near_university`, `mall_competition_interaction`, `university_competition_interaction`

Tests whether being next to a large demand-anchor (a mall or a university) **cushions** a
restaurant against nearby competition — e.g. a mall food court sustains many restaurants
that would fail standalone.

- `near_mall` — 1 if at least one mall within 1 km, else 0 (from `n_malls_1km`).
- `near_university` — 1 if at least one university within 1 km, else 0 (from
  `n_universities_1km`). "Near" = the same 1 km convention as the rest of the project.
- `mall_competition_interaction` = `near_mall × num_neighbors`
- `university_competition_interaction` = `near_university × num_neighbors`

The **interaction terms are the actual test**: `num_neighbors` is the (time-varying)
local competition, and the product lets a survival model estimate whether the effect of
competition is *different* for restaurants next to an anchor. Because `num_neighbors`
varies week to week, these interaction columns are time-varying even though the flags are
static.

### Results (share of restaurant-weeks near each anchor)

| City | `near_mall` | `near_university` |
|---|---|---|
| Tucson | 16.2% | 16.6% |
| Tampa | 18.7% | 9.9% |
| Indianapolis | 21.5% | 5.5% |
| Nashville | 13.2% | 27.7% |
| Philadelphia | 36.4% | 42.6% |

---

## Time-varying local churn: `local_openings_1yr`, `local_closings_1yr`, `local_churn_1yr`

**The first time-varying added variables.** Everything added before this point is static
per restaurant (one value repeated across all its weeks). These three genuinely change
week to week, using the panel's real strength — they measure how much the restaurant's
immediate area (within 1 km) has been *turning over* in the trailing 52 weeks.

- `local_openings_1yr` — # of **other** restaurants within 1 km that **opened** in the
  trailing 52 weeks (weeks *t*−51 … *t*).
- `local_closings_1yr` — # of other restaurants within 1 km that **closed** in the
  trailing 52 weeks.
- `local_churn_1yr` — the sum (total turnover). A high-churn area is an unstable location,
  which may raise a restaurant's own failure risk.

**How open/close weeks are read from the panel (verified encoding):** each restaurant is
`is_open = 1` every week it is alive, then has a single terminal `is_open = 0` row at the
week it closes; restaurants still open at the end of the data never get an `is_open = 0`
row (right-censored, no closing event). So **birth week** = first week in the panel, and
**closing week** = the terminal `is_open = 0` week (if any). A restaurant's own opening /
closing is excluded from its own churn (self excluded from the neighbour set).

**Method:** per city, neighbour adjacency within 1 km (haversine, Earth radius
6,371,000 m); each opening / closing is an event at (restaurant, week) that adds +1 to
every neighbour's trailing-year count for the 52 weeks following the event; the value is
then read off for each (restaurant, week) row in the panel.

### Verification performed (all three families)
- Row counts unchanged; went 61 → 67 (multi-scale + anchor) → **70 columns** (churn).
- Zero NAs in all 9 new columns; no negatives.
- Multi-scale nesting `n_poi_500m ≤ n_poi_1km ≤ n_poi_3km` holds for every row.
- Anchor flags are 0/1; both interaction columns recompute exactly as `flag × num_neighbors`.
- `local_churn_1yr = local_openings_1yr + local_closings_1yr` for every row.
- **Churn is genuinely time-varying**: 96.1 % of businesses have `local_churn_1yr` that
  varies across their weeks (`std > 0`) — confirming it is not a static value in disguise.
- **Independent recompute of churn** (the trickiest variable): for a sample Tucson
  restaurant-week (business `RHhhGUVX…`, week 549, 36 neighbours within 1 km), a
  from-scratch hand-count of neighbour openings/closings in the trailing 52 weeks gave
  openings = 1, closings = 1 — matching the stored values exactly.
- Zero duplicate `(business_id, week)` rows; previous columns unchanged; `.csv`/`.RData`
  in sync.

### Results — `local_churn_1yr` (mean / max per restaurant-week)

| City | mean | max |
|---|---|---|
| Tucson | 3.63 | 31 |
| Tampa | 4.87 | 42 |
| Indianapolis | 6.47 | 55 |
| Nashville | 8.89 | 61 |
| Philadelphia | 34.60 | 197 |

Philadelphia's dense core turns over far more (≈35 nearby openings+closings per year on
average) than the more spread-out metros.

---

# Survival model results

To test which of these variables affect restaurant survival, we fit a Cox
proportional-hazards model (the same model family used in the source paper) separately
to each of the 6 datasets.

### Model specification
- **Tool:** `lifelines.CoxTimeVaryingFitter` (Python), counting-process / time-varying
  form — the extended Cox model, matching the paper's approach.
- **Survival clock:** restaurant **age** (weeks since first review). Each restaurant-week
  is an interval `(age−1, age]`.
- **Failure event:** a failed restaurant has exactly one terminal `is_open = 0` row (its
  "virtual death" = the week after its final review); `event = 1` on that interval.
  Restaurants still open at the data end are censored. (Same definition as the paper.)
- **Covariates (20, curated):** the paper's core controls (`pricing`,
  `category_popularity`, `groupon`, `attributes_count`, `sum_rev_count`,
  `three_rev_avg_stars`), the original neighbour variables (`num_neighbors`,
  `failed_neighbors`, `same_p_n_rat`, `same_cat_n_rat`, `fran_neigh_rat`), and a
  **non-redundant selection of the new variables** (`median_household_income`,
  `amenity_access`, `poi_diversity`, `poi_advantage`, `local_churn_1yr`, `near_mall`,
  `near_university`, `mall_competition_interaction`, `university_competition_interaction`).
  We deliberately did **not** put all 34 new columns in one model — the many
  "amenities-nearby" variables are mutually collinear, so a compact non-redundant set is
  used and `amenity_access` stands in as the overall amenity measure.
- **Scaling:** continuous covariates are standardised, so each **hazard ratio is per
  1 SD increase**; binary covariates are 0/1. A small ridge penalty (`penalizer=0.01`)
  is used for numerical stability.
- **Missing values:** `median_household_income` NaN (pre-2011, P.O.-box zips) →
  median-imputed; `poi_advantage` NaN (isolated restaurants) → 0.
- Fit is via `fit_survival_model.py`; per-city results in `survival_results_<city>.csv`,
  combined table in `survival_results_ALL_TABLE.csv`. **This step does not modify the 6
  data files.**

**How to read a hazard ratio (HR):** HR > 1 → the variable **raises** the weekly failure
risk (bad for survival); HR < 1 → **protective** (good for survival); HR ≈ 1 → no effect.
Stars: `***` p<0.01, `**` p<0.05, `*` p<0.10.

### Table — Cox hazard ratios, all 6 datasets

Hazard ratios below. Exact p-values for every cell are in
`survival_results_<city>.csv` and the combined `survival_results_ALL_TABLE.csv`.

| Variable | Tucson | Tampa | Indianapolis | Nashville | Philadelphia | AllCities_MERGED |
|---|---|---|---|---|---|---|
| **Controls** | | | | | | |
| pricing | 1.017 | 0.980 | 0.999 | 0.970 | 1.031 | 1.008 |
| category_popularity | 0.965 | 0.972 | 0.979 | 0.984 | 0.993 | 0.982 |
| groupon | 1.007 | 1.215 | 1.279 | 1.160 | 1.165 | 1.172 |
| attributes_count | 0.967 | 0.976 | 0.975 | 0.974 | 0.969 | 0.972 |
| sum_rev_count | 1.000 | 0.998 | 1.004 | 0.995 | 0.994 | 0.997 |
| three_rev_avg_stars | 0.995 | 0.981 | 0.992 | 0.989 | 0.981 | 0.987 |
| **Original neighbour vars** | | | | | | |
| num_neighbors | 1.017 | 1.018 | 1.018 | 1.011 | 1.017 | 1.013 |
| failed_neighbors | 1.021 | 1.027 | 1.029 | 1.021 | 1.036 | 1.029 |
| same_p_n_rat | 0.988 | 0.993 | 0.986 | 0.997 | 0.989 | 0.990 |
| same_cat_n_rat | 0.988 | 0.988 | 0.993 | 0.997 | 1.000 | 0.994 |
| fran_neigh_rat | 1.002 | 1.000 | 0.991 | 0.993 | 0.996 | 0.995 |
| **New variables** | | | | | | |
| median_household_income | 0.998 | 1.018 | 1.008 | 1.006 | 1.021 | 1.014 |
| amenity_access | 1.010 | 1.007 | 1.011 | 1.008 | 1.019 | 1.013 |
| poi_diversity | 1.013 | 1.006 | 1.009 | 1.003 | 1.010 | 1.010 |
| poi_advantage | 0.999 | 0.999 | 1.001 | 0.997 | 1.004 | 1.002 |
| local_churn_1yr | 1.010 | 1.013 | 1.014 | 1.011 | 1.014 | 1.011 |
| near_mall | 1.026 | 0.997 | 1.018 | 0.972 | 1.014 | 1.012 |
| near_university | 1.024 | 1.012 | 0.993 | 1.003 | 1.015 | 1.014 |
| mall_competition_interaction | 1.011 | 1.005 | 1.012 | 0.994 | 1.009 | 1.007 |
| university_competition_interaction | 1.009 | 1.007 | 0.999 | 1.002 | 1.012 | 1.008 |
| **N subjects** | 2,466 | 2,960 | 2,862 | 2,502 | 5,852 | 16,642 |
| **N failures** | 827 | 996 | 958 | 821 | 2,327 | 5,929 |

### Which effects are statistically significant (p-values, AllCities_MERGED model)

- Strong (p < 0.01): `attributes_count` (p<0.0001), `three_rev_avg_stars` (0.0006),
  `num_neighbors` (0.0009), `failed_neighbors` (<0.0001), `same_p_n_rat` (0.0086),
  `median_household_income` (0.0004), `amenity_access` (0.0009), `local_churn_1yr` (0.0048).
- Moderate (p < 0.05): `category_popularity` (0.020), `groupon` (0.037),
  `poi_diversity` (0.013), `university_competition_interaction` (0.040).
- Weak (p < 0.10): `mall_competition_interaction` (0.061).
- Not significant: `pricing`, `sum_rev_count`, `same_cat_n_rat`, `fran_neigh_rat`,
  `poi_advantage`, `near_mall`, `near_university`.

### Interpretation

**The replication holds — the paper's core findings reproduce.** In every city:
- `failed_neighbors` HR > 1 and significant — **locating near restaurants that have
  failed raises your own failure risk**. This is the paper's headline result, and it is
  the single most robust effect here.
- `attributes_count` protective in all 6 (more Yelp attributes → lower risk);
  `three_rev_avg_stars` protective (better ratings → survive); `groupon` > 1 (offering
  Groupon → higher failure); `same_p_n_rat` protective (being among **same-price**
  neighbours helps); `same_cat_n_rat` not significant (same-cuisine neighbours don't
  matter). All of these match the paper's directions.

**The new variables — the extension.** Effects are modest (HRs near 1 because covariates
are per-SD), and they surface mainly in the **high-power models** (Philadelphia,
N=5,852; and AllCities_MERGED, N=16,642) where there is enough statistical power; in the
smaller individual cities most are not significant. In the AllCities_MERGED model, three
new variables are significant and all point the **same way — denser / richer /
higher-turnover locations carry higher failure risk**:
- `median_household_income` HR 1.014 (AllCities_MERGED, p=0.0004), 1.021 (Philadelphia):
  restaurants in higher-income areas fail more, plausibly because of higher rent/costs and
  stronger competition. This runs against the simple "richer area is safer" intuition.
- `amenity_access` HR 1.013 (AllCities_MERGED, p=0.0009), 1.019 (Philadelphia): more
  (distance-weighted) amenities nearby is associated with higher failure risk, which fits
  the agglomeration-as-competition view rather than amenity spillover as a benefit.
- `local_churn_1yr` HR 1.011 (AllCities_MERGED, p=0.0048), 1.014 (Philadelphia):
  restaurants in high-turnover neighbourhoods fail more. This is the time-varying variable,
  and it behaves as expected (an unstable area is a riskier location).
- `poi_diversity` (1.010, p=0.013) and the two anchor×competition interactions
  (about 1.007–1.008, weak) reach significance in the AllCities_MERGED model only.
  `poi_advantage` and the `near_mall`/`near_university` main effects are not significant in
  any city.

Caveats. (1) The effect sizes are small: statistically detectable but modest per-SD
effects, and strongest where the sample is largest. (2) We did not formally test the
proportional-hazards assumption for each covariate (Schoenfeld residuals); this is a
refinement to add for a final paper. (3) The covariate set is one reasonable
specification; swapping which amenity variable enters (for example `n_poi_1km` instead of
`amenity_access`) is a natural robustness check.
