"""Reweight the saved 10-km graph for category-specific spread speeds."""
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix, csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent
DEFAULT_SPEEDS = (0., 10., 25., 50.)
LABELS = ("No/very low", "Low", "Moderate", "High")


@lru_cache(maxsize=1)
def inputs():
    with np.load(ROOT / "landscape_data.npz") as f:
        return {k: f[k] for k in f.files}


def summarize(distance, context):
    z = inputs()
    result = np.full(len(z["county_class"]), np.inf, dtype=np.float32)
    order, ids, starts = context["order"], context["ids"], context["starts"]
    if len(order):
        result[ids] = np.minimum.reduceat(distance[order], starts)
        missing = context["missing"]
        result[missing] = distance[context["fallback"][missing]]
    return result


@lru_cache(maxsize=6)
def landscape(speeds):
    z = inputs()
    county_speed = np.asarray(speeds, dtype=np.float32)[z["county_class"]]
    speed = county_speed[z["node_county"]]
    u, v = z["edge_u"], z["edge_v"]
    valid = (speed[u] > 0) & (speed[v] > 0)
    for corner in (z["corner1"], z["corner2"]):
        valid &= (corner < 0) | (speed[np.maximum(corner, 0)] > 0)
    u, v = u[valid], v[valid]
    costs = z["effective_miles"][valid] * .5 * (1 / speed[u] + 1 / speed[v])
    graph = coo_matrix((np.r_[costs, costs], (np.r_[u, v], np.r_[v, u])),
                       shape=(len(speed), len(speed))).tocsr()
    active = np.flatnonzero(speed > 0)
    origin = np.full(len(county_speed), -1, dtype=np.int32)
    fallback = origin.copy()
    order = active[np.argsort(z["node_county"][active], kind="stable")]
    ids, starts = np.unique(z["node_county"][order], return_index=True)
    missing = np.setdiff1d(np.flatnonzero(county_speed > 0), ids)
    if len(active):
        _, nearest = cKDTree(z["node_xy"][active]).query(z["county_center_xy"])
        fallback[:] = active[nearest]
        origin[county_speed > 0] = fallback[county_speed > 0]
        for ci, start, end in zip(ids, starts, np.r_[starts[1:], len(order)]):
            candidates = order[start:end]
            xy = z["node_xy"][candidates] - z["county_center_xy"][ci]
            origin[ci] = candidates[np.argmin(np.sum(xy * xy, axis=1))]
    ctx = dict(graph=graph, order=order, ids=ids, starts=starts,
               missing=missing, fallback=fallback, origin=origin)
    initial_nodes = active[z["initial_county"][z["node_county"][active]]]
    distances = dijkstra(graph, directed=False, indices=initial_nodes, min_only=True) if len(initial_nodes) else np.full(len(speed), np.inf)
    baseline = summarize(distances, ctx)
    baseline[z["initial_county"]] = 0
    ctx["baseline"] = baseline
    return ctx


@lru_cache(maxsize=128)
def travel(speeds, county):
    ctx = landscape(speeds)
    node = ctx["origin"][county]
    if node < 0:
        result = np.full(len(inputs()["county_class"]), np.inf, dtype=np.float32)
    else:
        result = summarize(dijkstra(ctx["graph"], directed=False, indices=int(node)), ctx)
    result[county] = 0
    return result


@lru_cache(maxsize=1)
def kernels():
    with np.load(ROOT / "route_kernels.npz") as f:
        return dict(short=csr_matrix(f["short"]), long=csr_matrix(f["long"]),
                    road_global=f["road_global"], exposure=f["exposure"],
                    long_capable=f["long_capable"])


def annual_probabilities(baseline, horizon):
    k = kernels()
    result = np.zeros((2, horizon, len(baseline)), dtype=np.float64)
    for year in range(1, horizon + 1):
        occupied = baseline[k["road_global"]] <= year - 1
        for j, kind in enumerate(("short", "long")):
            eligible = occupied if j == 0 else occupied & k["long_capable"]
            weights = k["exposure"] * eligible
            total = weights.sum()
            if total:
                result[j, year - 1] = (weights / total) @ k[kind]
    return result
