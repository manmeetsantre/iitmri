"""
Fits a Cox proportional-hazards survival model (extended / counting-process form,
with time-varying covariates) to each of the 6 datasets separately, and writes a
paper-style hazard-ratio table (Table-3 style) per city + the merged file.

Survival setup (matches the source paper's definition):
  - Timeline = restaurant AGE (weeks since first review). Each restaurant-week is
    an interval (age-1, age].
  - Event / failure: a failed restaurant has exactly ONE terminal is_open==0 row
    (its "virtual death" week = the week after its final review). event = 1 on that
    last interval; censored restaurants (is_open==1 throughout) have event = 0.
  - This is the CoxTimeVaryingFitter counting-process format from `lifelines`.

Covariate set: deliberately CURATED (not all 70 columns) to avoid the severe
multicollinearity among the many "amenities-nearby" variables. We include the
paper's core controls, the original neighbour variables, and a non-redundant
selection of the NEW variables (income, an overall amenity-accessibility score,
amenity diversity, relative advantage, local churn, and the anchor flags +
their competition interactions). Continuous covariates are standardised (z-scored),
so each hazard ratio is "per 1 SD increase"; binary covariates are left 0/1.

Missing-value handling (disclosed):
  - median_household_income: NaN for pre-2011 weeks and P.O.-box zips -> filled
    with the city's median income (median imputation, as agreed for model time).
  - poi_advantage: NaN for isolated restaurants (no neighbour) -> filled with 0
    (no neighbours => no relative advantage).
"""
import numpy as np
import pandas as pd
from lifelines import CoxTimeVaryingFitter

OUT_ROOT = "/Users/MANMEETSANTRE/Downloads/restaurant-agglomeration-main/new_variables"
FILES = ["Tucson", "Tampa", "Indianapolis", "Nashville", "Philadelphia", "AllCities_MERGED"]

BINARY = ["pricing", "category_popularity", "groupon", "near_mall", "near_university"]
CONTINUOUS = [
    # paper-style controls
    "attributes_count", "sum_rev_count", "three_rev_avg_stars",
    # original neighbour variables
    "num_neighbors", "failed_neighbors", "same_p_n_rat", "same_cat_n_rat", "fran_neigh_rat",
    # NEW variables (the focus of the extension)
    "median_household_income", "amenity_access", "poi_diversity", "poi_advantage",
    "local_churn_1yr", "mall_competition_interaction", "university_competition_interaction",
]
COVARIATES = BINARY + CONTINUOUS


def prepare(df):
    df = df.sort_values(["business_id", "week"]).copy()
    # event: 1 on a failed restaurant's terminal (is_open==0) row
    df["event"] = 0
    last_idx = df.groupby("business_id").tail(1).index
    df.loc[last_idx, "event"] = (df.loc[last_idx, "is_open"] == 0).astype(int)
    # counting-process interval on age: (age-1, age]
    df["tstart"] = df["age"] - 1
    df["tstop"] = df["age"]
    # guard against any non-positive intervals (age must be strictly increasing per id)
    df = df[df["tstop"] > df["tstart"]].copy()

    # missing-value handling
    df["median_household_income"] = df["median_household_income"].fillna(
        df["median_household_income"].median())
    df["poi_advantage"] = df["poi_advantage"].fillna(0.0)

    # integer id for lifelines
    df["id"] = df.groupby("business_id").ngroup()

    keep = ["id", "tstart", "tstop", "event"] + COVARIATES
    d = df[keep].copy()

    # standardise continuous covariates (HR per 1 SD); drop any zero-variance column
    used = list(BINARY)
    for c in CONTINUOUS:
        sd = d[c].std()
        if sd > 0:
            d[c] = (d[c] - d[c].mean()) / sd
            used.append(c)
        else:
            d = d.drop(columns=c)
    return d, used


def fit_city(name):
    print(f"\n================ {name} ================")
    df = pd.read_csv(f"{OUT_ROOT}/LATEST_{name}_FULL_DATA.csv")
    d, used = prepare(df)
    n_subj = d["id"].nunique()
    n_fail = int(d["event"].sum())
    print(f"subjects={n_subj}  failures={n_fail}  rows={len(d)}  covariates={len(used)}")

    ctv = CoxTimeVaryingFitter(penalizer=0.01)
    ctv.fit(d, id_col="id", event_col="event", start_col="tstart", stop_col="tstop",
            show_progress=False)

    s = ctv.summary
    out = pd.DataFrame({
        "variable": s.index,
        "hazard_ratio": np.exp(s["coef"]).round(4).values,
        "p": s["p"].round(4).values,
    })
    out.to_csv(f"{OUT_ROOT}/survival_results_{name}.csv", index=False)
    print(out.to_string(index=False))
    return name, n_subj, n_fail, out


def main():
    hr = {}
    pv = {}
    meta = {}
    for name in FILES:
        nm, ns, nf, out = fit_city(name)
        hr[nm] = out.set_index("variable")["hazard_ratio"]
        pv[nm] = out.set_index("variable")["p"]
        meta[nm] = (ns, nf)

    # combined table: one flat header per dataset -> <city>_HR and <city>_p columns
    comb = {}
    for nm in FILES:
        comb[f"{nm}_HR"] = hr[nm].reindex(COVARIATES)
        comb[f"{nm}_p"] = pv[nm].reindex(COVARIATES)
    table = pd.DataFrame(comb)
    table.index.name = "variable"
    for label, i in [("N_subjects", 0), ("N_failures", 1)]:
        table.loc[label] = {**{f"{nm}_HR": meta[nm][i] for nm in FILES},
                            **{f"{nm}_p": "" for nm in FILES}}
    table.to_csv(f"{OUT_ROOT}/survival_results_ALL_TABLE.csv")
    print("\n\n============ COMBINED HAZARD-RATIO TABLE ============")
    print(pd.DataFrame({nm: hr[nm].reindex(COVARIATES) for nm in FILES}).to_string())
    print("\nDONE")


if __name__ == "__main__":
    main()
