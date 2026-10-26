"""Annual Model 2 scenario calculations from saved county route intensities.

Poisson thinning gives annual county receipts Poisson(lambda[y, county]).
For each county, the number of previously unhit histories receiving an animal
this year is Binomial(n_unhit, 1-exp(-lambda)). Tracking these counts exactly
reproduces the distribution of annual cumulative Monte Carlo receipt fractions
without storing individual histories. This reduction relies on fixed route
intensities and no transport feedback from new nidi.
"""
from functools import lru_cache
from pathlib import Path

import numpy as np
from landscape_engine import DEFAULT_SPEEDS, landscape, travel, annual_probabilities

ROOT = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def data():
    a = np.load(ROOT / "model_data.npz")
    return {k: a[k] for k in a.files}


def parse(value, low, high, name):
    x = float(value)
    if not np.isfinite(x) or x < low or x > high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return x


def run(params):
    if not isinstance(params, dict):
        raise ValueError("Scenario inputs must be an object")
    observed_per_year = parse(params.get("observed_per_year", .2), 0, 20, "Observed detections/year")
    detection = parse(params.get("detection_probability", .01), .0001, 1, "Detection probability")
    long_share = parse(params.get("long_share", .6), 0, 1, "Long-haul share")
    receipt_cutoff = parse(params.get("receipt_cutoff", .5), 0, 1, "Receipt cutoff")
    recept_cutoff = parse(params.get("receptivity_cutoff", .7050952593606139), 0, 1, "Receptivity cutoff")
    horizon = parse(params.get("horizon", 20), 1, 20, "Horizon")
    if horizon != int(horizon):
        raise ValueError("Horizon must be a whole number")
    horizon = int(horizon)
    mode = params.get("mode", "monte_carlo")
    if mode not in ("monte_carlo", "analytic"):
        raise ValueError("Calculation mode must be monte_carlo or analytic")
    seed = parse(params.get("random_seed", 20261009), 0, 4294967295, "Random seed")
    if seed != int(seed):
        raise ValueError("Random seed must be a whole number")
    seed = int(seed)
    simulations = 10000
    speed_fields = ("speed_very_low", "speed_low", "speed_moderate", "speed_high")
    speeds = tuple(parse(params.get(key, default), 0, 250, key.replace("_", " "))
                   for key, default in zip(speed_fields, DEFAULT_SPEEDS))
    landscape_mode = params.get("landscape_mode", "reference" if speeds == DEFAULT_SPEEDS else "rebuild")
    if landscape_mode not in ("reference", "rebuild"):
        raise ValueError("Landscape mode must be reference or rebuild")
    if landscape_mode == "reference" and speeds != DEFAULT_SPEEDS:
        raise ValueError("Custom speeds require the recalculated landscape mode")
    rate = observed_per_year / detection
    if rate > 1000:
        raise ValueError("Inferred annual transport rate must be at most 1,000 in this interface")
    a = data()
    if landscape_mode == "rebuild":
        baseline = landscape(speeds)["baseline"]
        short, long = annual_probabilities(baseline, horizon)
    else:
        baseline = a["baseline"]
        short, long = a["short"][:horizon], a["long"][:horizon]
    annual = rate * ((1-long_share)*short + long_share*long)
    analytic_p = -np.expm1(-np.cumsum(annual, axis=0, dtype=np.float64))
    if mode == "monte_carlo":
        rng = np.random.default_rng(seed)
        hits = np.zeros(annual.shape[1], dtype=np.int64)
        p = np.empty_like(analytic_p)
        for year in range(horizon):
            hits += rng.binomial(simulations-hits, -np.expm1(-annual[year].astype(np.float64)))
            p[year] = hits / simulations
    else:
        p = analytic_p
    scenario = baseline.copy()
    receptive = a["receptivity"] > recept_cutoff
    road = {int(ci): ri for ri, ci in enumerate(a["road_global"])}
    seen = np.zeros(len(baseline), dtype=bool)
    seeds = []
    summary = []
    for year in range(1, horizon+1):
        crossed = (p[year-1] > receipt_cutoff) & receptive & ~seen
        seen |= crossed
        candidate = np.flatnonzero(crossed)
        usable = [int(i) for i in candidate if scenario[i] > year and int(i) in road]
        for i in usable:
            scenario[i] = year
            seeds.append(dict(index=i, year=year, p_receipt=round(float(p[year-1,i]),4),
                              receptivity=round(float(a["receptivity"][i]),4)))
        for i in usable:
            onward = travel(speeds, i) if landscape_mode == "rebuild" else a["travel"][road[i]]
            np.minimum(scenario, year+1+onward, out=scenario)
        summary.append(dict(year=year, candidate_count=int(len(candidate)), nidi=len(usable),
                            baseline=int(np.sum(baseline <= year)), reached=int(np.sum(scenario <= year)),
                            added=int(np.sum((scenario <= year) & (baseline > year)))))
    return dict(inputs=dict(observed_per_year=observed_per_year, detection_probability=detection,
                            annual_infectious_transports=rate, long_share=long_share,
                            receipt_cutoff=receipt_cutoff, receptivity_cutoff=recept_cutoff, horizon=horizon,
                            mode=mode, random_seed=seed, simulations=simulations,
                            landscape_mode=landscape_mode, **dict(zip(speed_fields, speeds))),
                candidates=int(seen.sum()), nidi=len(seeds), seeds=seeds, annual=summary,
                baseline_count=summary[-1]["baseline"], reached=summary[-1]["reached"],
                added=summary[-1]["added"],
                arrival=np.where(np.isfinite(scenario), scenario, -1).tolist(),
                baseline_arrival=np.where(np.isfinite(baseline), baseline, -1).tolist(),
                receptivity=np.where(np.isfinite(a["receptivity"]), np.round(a["receptivity"],4), -1).tolist(),
                p_receipt=np.round(p[-1],4).tolist())
