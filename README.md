# iitmri

Research internship project at IIT Madras, based on the paper *Effect of Agglomeration
in the Restaurant Industry* (AMCIS 2018).

## About the project

The original paper looks at why restaurants survive or fail depending on the restaurants
around them, an idea from economics called the agglomeration effect. It uses a Cox
survival model on Yelp data for Phoenix.

This project rebuilds that weekly restaurant-survival dataset for five US cities (Tucson,
Tampa, Indianapolis, Nashville, Philadelphia) and extends it. The original study only
described a restaurant's neighbourhood in terms of other restaurants. Here the idea is to
also describe the wider location: how wealthy the area is, what kinds of places are nearby
(malls, museums, parks, universities, tourist spots), and how much the local area is
changing over time. The survival model is then run again to see which of these location
factors affect whether a restaurant survives.

Each city dataset, plus a merged all-cities dataset, is a weekly panel with one row per
restaurant per week. The starting data has 36 variables (from the original paper plus
extra Yelp fields). This project adds 34 more, so each dataset ends up with 70 variables.

## The new variables

Everything new was built in Python. A short summary:

- **Category heterogeneity** (6 variables): how similar the nearby restaurants are in
  venue type, cuisine, and service style.
- **Median household income** (1): the income level of each restaurant's zip code, by
  year, from the US Census (ACS) API.
- **Points of interest** (POI): counts of malls, museums, attractions, parks,
  universities, and stadiums within 1 km of each restaurant, pulled for free from
  OpenStreetMap, plus distance to the nearest mall.
- **Distance-decay accessibility** (6): a smoother version of the counts that weights
  nearby places by how close they are (the Hansen accessibility index), instead of a hard
  1 km cutoff.
- **Amenity diversity and relative advantage** (2): how varied the nearby places are, and
  whether a restaurant is better located than the restaurants around it.
- **Multi-scale catchments** (2): the same POI count at a walk-in distance (500 m) and a
  drive-to distance (3 km).
- **Anchor and competition** (4): flags for being next to a mall or university, and
  interaction terms that test whether an anchor cushions a restaurant against competition.
- **Local churn** (3): how many nearby restaurants opened or closed in the past year.
  This variable changes over time.

Full definitions, the exact computation for each variable, the limitations, and the
survival-model results are in [new_variables/README.md](new_variables/README.md).

## Repository structure

```
iitmri/
├── README.md                 this file
├── LICENSE
└── new_variables/
    ├── README.md             detailed writeup of every variable and the model results
    ├── CODE_GUIDE.md         how the scripts fit together and how to run them
    ├── compute_*.py          category heterogeneity variables
    ├── pull_census_income.py + build_income_variable.py     income
    ├── pull_osm_poi.py + build_poi_*.py                     POI data and counts
    ├── build_accessibility_variables.py                    accessibility scores
    ├── build_advantage_diversity_variables.py              advantage and diversity
    ├── build_multiscale_anchor_variables.py                multi-scale and anchor
    ├── build_churn_variables.py                            local churn
    ├── fit_survival_model.py                               the Cox survival model
    ├── survival_results_*.csv                              model output (hazard ratios, p-values)
    └── census_income_raw.csv, osm_poi_raw.csv              public reference data
```

`new_variables/CODE_GUIDE.md` explains each script, the order to run them in, and which
file produces which variable.

## Data

The actual datasets (the 70-variable weekly panel files) are not stored in this repo, for
two reasons. They are built from the Yelp Open Dataset, whose terms do not allow
redistributing the data, and the files are also too large for GitHub (up to about 2 GB
each). They are shared separately in a Drive folder. This repo holds the code that builds
the data, the documentation, and the aggregate model results.

## Setup

The code needs Python 3 and a few libraries:

```
pip install pandas numpy rdata pyreadr lifelines
```

- `rdata` and `pyreadr` read and write R's `.RData` format, which is what the source data
  uses, so R itself is not needed.
- `lifelines` runs the Cox survival model.

The income script needs a free Census API key
(https://api.census.gov/data/key_signup.html), set as an environment variable:

```
export CENSUS_API_KEY=your_key
```

The POI script uses OpenStreetMap's free Overpass API and needs no key.

## Results

The Cox survival model was fit to all six datasets. The original paper's main findings
reproduced: locating near restaurants that have failed raises failure risk, being among
similarly priced neighbours helps, higher ratings and more listed attributes help, and
Groupon offers hurt. Among the new variables, higher local income, more nearby amenities,
and higher local churn were each linked to higher failure risk in the larger-sample
models, which fits the idea that denser and more contested areas are harder to survive in.
The full result tables and interpretation are in `new_variables/README.md` and the
`survival_results_*.csv` files.

## Reference

Chidambaram, K. V., and Pervin, N. (2018). *Effect of Agglomeration in the Restaurant
Industry.* Twenty-fourth Americas Conference on Information Systems (AMCIS), New Orleans.

---

Guided by Prof. Vaibhav Chawla, DoMS, IIT Madras, and Prof. Nargis Pervin, DoMS, IIT Madras.

Built by Manmeet Santre, Research Intern, IIT Madras (2026).
