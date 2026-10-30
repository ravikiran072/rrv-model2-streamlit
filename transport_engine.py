"""Shifted exponential transport weights and the retained westbound routing proxy.

The curve allocates probability to eight bands. Within-band destinations retain
Interstate-length weights. Finite routes shorter than 100 km are never eligible.
"""
from functools import lru_cache
from pathlib import Path
import numpy as np
from scipy.sparse import coo_matrix

MIN_DISTANCE_KM = 100.
LONG_THRESHOLD_KM = 1207.008
DEFAULT_MEAN_KM = 2268.
BAND_EDGES_KM = np.array([100., 160.9344, 402.336, 804.672, 1207.008,
                          1609.344, 2414.016, 3218.688, np.inf])
ROOT = Path(__file__).resolve().parent


def distribution(mean_km):
    mean_km = float(mean_km)
    if not np.isfinite(mean_km) or mean_km <= MIN_DISTANCE_KM or mean_km > 10000:
        raise ValueError('Mean total transport distance must be greater than 100 and at most 10,000 km')
    scale = mean_km - MIN_DISTANCE_KM
    survival = np.exp(-(BAND_EDGES_KM - MIN_DISTANCE_KM) / scale)
    weights = survival[:-1] - survival[1:]
    return dict(family='shifted_exponential', minimum_km=MIN_DISTANCE_KM,
                mean_total_km=mean_km, exponential_scale_km=scale,
                central_95_lower_km=float(MIN_DISTANCE_KM-scale*np.log(.975)),
                central_95_upper_km=float(MIN_DISTANCE_KM-scale*np.log(.025)),
                nominal_long_share=float(np.exp(-(LONG_THRESHOLD_KM-MIN_DISTANCE_KM)/scale)),
                long_threshold_km=LONG_THRESHOLD_KM,
                band_edges_km=[float(v) if np.isfinite(v) else None for v in BAND_EDGES_KM],
                band_weights=weights.tolist(),
                note='Curve probabilities are discretized into eight routing bands; eligible routes and empty-band fallback can alter the assigned distance distribution.')


@lru_cache(maxsize=1)
def routes():
    with np.load(ROOT/'transport_routes.npz') as z:
        a={k:z[k] for k in z.files}
    d,lon=a['distance_km'],a['longitude']
    valid=np.isfinite(d)&(d>=MIN_DISTANCE_KM)&(lon[None,:]<lon[:,None])
    np.fill_diagonal(valid,False)
    origin,destination=np.nonzero(valid)
    band=np.searchsorted(BAND_EDGES_KM,d[origin,destination],side='right')-1
    available=np.zeros((len(lon),8),bool)
    available[origin,band]=True
    fallback=np.full((len(lon),8),-1,dtype=np.int8)
    for i in range(len(lon)):
        usable=np.flatnonzero(available[i])
        if len(usable):
            for b in range(8):
                fallback[i,b]=min(usable,key=lambda j:(abs(int(j)-b),int(j)))
    totals=np.zeros((len(lon),8))
    np.add.at(totals,(origin,band),a['exposure_km'][destination])
    pair_weight=a['exposure_km'][destination]/totals[origin,band]
    a.update(origin=origin,destination=destination,band=band,pair_weight=pair_weight,
             available=available,fallback=fallback,has_destination=available.any(axis=1))
    return a


@lru_cache(maxsize=6)
def kernel(mean_km):
    info=distribution(mean_km);a=routes();n=len(a['road_global'])
    allocated=np.zeros((n,8))
    for b,w in enumerate(info['band_weights']):
        valid=a['fallback'][:,b]>=0
        i=np.flatnonzero(valid)
        allocated[i,a['fallback'][i,b]]+=w
    i,j,b=a['origin'],a['destination'],a['band']
    probability=a['pair_weight']*allocated[i,b]
    matrix=coo_matrix((probability,(i,a['road_global'][j])),shape=(n,3096)).tocsr()
    row_distance=np.bincount(i,weights=probability*a['distance_km'][i,j],minlength=n)
    row_long=np.bincount(i,weights=probability*(a['distance_km'][i,j]>=LONG_THRESHOLD_KM),minlength=n)
    return dict(matrix=matrix,mean_distance_numerator=row_distance,long_probability=row_long,
                distribution=info,road_global=a['road_global'],exposure_km=a['exposure_km'],
                has_destination=a['has_destination'])


def annual_destinations(arrival,start_year,transport):
    occupied=arrival[transport['road_global']]<=start_year
    weights=transport['exposure_km']*occupied
    total=weights.sum()
    if total:
        origin_weight=weights/total
        probability=np.asarray(origin_weight@transport['matrix']).ravel()
        mass=float(probability.sum())
        mean=float(origin_weight@transport['mean_distance_numerator']/mass) if mass else None
        long=float(origin_weight@transport['long_probability']/mass) if mass else None
    else:
        probability=np.zeros(len(arrival));mass=0.;mean=None;long=None
    return probability,dict(road_origin_counties=int(occupied.sum()),
             assignable_road_origin_counties=int((occupied&transport['has_destination']).sum()),
             destination_probability_mass=mass,assigned_mean_distance_km=mean,assigned_long_share=long)
