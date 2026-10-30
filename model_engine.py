"""Annual burden-scaled translocation with shifted exponential travel distances.

10,000 delivery histories share the scenario frontier and ensemble nidus rules.
"""
import numpy as np
from model_utils import data,parse
from landscape_engine import landscape,travel,DEFAULT_SPEEDS
from transport_engine import kernel,annual_destinations,DEFAULT_MEAN_KM

SPEED_FIELDS=('speed_very_low','speed_low','speed_moderate','speed_high')


def run(params):
    if not isinstance(params,dict):
        raise ValueError('Scenario inputs must be an object')
    if 'long_share' in params:
        raise ValueError('Long-haul share is now derived from mean_transport_km; remove the old long_share input')
    observed=parse(params.get('observed_per_year',.2),0,20,'Observed detections/year')
    detection=parse(params.get('detection_probability',.01),.0001,1,'Detection probability')
    mean=parse(params.get('mean_transport_km',DEFAULT_MEAN_KM),100,10000,'Mean total transport distance, km')
    transport=kernel(mean)
    receiptcut=parse(params.get('receipt_cutoff',.5),0,1,'Receipt cutoff')
    receptcut=parse(params.get('receptivity_cutoff',.7928484500378316),0,1,'Receptivity cutoff')
    h=parse(params.get('horizon',20),1,20,'Horizon')
    seed=parse(params.get('random_seed',20261009),0,4294967295,'Random seed')
    if h!=int(h) or seed!=int(seed):
        raise ValueError('Horizon and seed must be whole numbers')
    horizon=int(h);seed=int(seed);mode=params.get('mode','monte_carlo')
    if mode not in ['monte_carlo','analytic']:
        raise ValueError('Calculation mode must be monte_carlo or analytic')
    scale=params.get('scale_transport_with_burden',True)
    feedback=params.get('include_nidi_as_origins',True)
    if not isinstance(scale,bool) or not isinstance(feedback,bool):
        raise ValueError('Burden scaling and origin feedback must be Boolean')
    speeds=tuple(parse(params.get(k,v),0,400,k) for k,v in zip(SPEED_FIELDS,DEFAULT_SPEEDS))
    if any(v%2!=0 for v in speeds):
        raise ValueError('Spread speeds must be multiples of 2 km/year')
    if params.get('landscape_mode','rebuild')!='rebuild':
        raise ValueError('Updated habitat requires a rebuilt landscape')
    initial_rate=observed/detection
    if initial_rate>1000:
        raise ValueError('Initial inferred transport rate must be at most 1000/year')
    a=data();baseline=landscape(speeds)['baseline'];scenario=baseline.copy()
    initial_n=int(np.sum(baseline==0));assert initial_n>0
    receptive=a['receptivity']>receptcut
    road=set(int(i) for i in a['road_global'])
    seen=np.zeros(len(baseline),bool);hits=np.zeros(len(baseline),np.int64)
    cumulative=np.zeros(len(baseline));rng=np.random.default_rng(seed)
    simulations=10000;seeds=[];summary=[];history=[]
    for year in range(1,horizon+1):
        occupied_n=int((scenario<=year-1).sum())
        factor=occupied_n/initial_n if scale else 1.;rate=initial_rate*factor
        probability,route_stats=annual_destinations(scenario if feedback else baseline,year-1,transport)
        annual=rate*probability;cumulative+=annual
        if mode=='monte_carlo':
            hits+=rng.binomial(simulations-hits,-np.expm1(-annual));p=hits/simulations
        else:
            p=-np.expm1(-cumulative)
        history.append(p.copy())
        crossed=(p>receiptcut)&receptive&~seen;seen|=crossed
        candidate=np.flatnonzero(crossed)
        usable=[int(i) for i in candidate if scenario[i]>year and int(i) in road]
        for i in usable:
            scenario[i]=year
            seeds.append(dict(index=i,year=year,p_receipt=round(float(p[i]),4),
                              receptivity=round(float(a['receptivity'][i]),4)))
        for i in usable:
            np.minimum(scenario,year+1+travel(speeds,i),out=scenario)
        assigned=float(annual.sum())
        summary.append(dict(year=year,endemic_counties_at_start=occupied_n,
            burden_multiplier=factor,annual_infectious_transport_mean=rate,
            expected_detected_transports=rate*detection,
            eligible_road_origin_counties=route_stats.pop('road_origin_counties'),
            **route_stats,annual_assigned_transport_mean=assigned,
            annual_unassigned_transport_mean=max(0.,rate-assigned),candidate_count=len(candidate),
            nidi=len(usable),baseline=int(np.sum(baseline<=year)),reached=int(np.sum(scenario<=year)),
            added=int(np.sum((scenario<=year)&(baseline>year)))))
    info=transport['distribution']
    return dict(inputs=dict(distance_unit='km',speed_unit='km/year',speed_step=2,
        observed_per_year=observed,detection_probability=detection,
        initial_annual_infectious_transports=initial_rate,annual_infectious_transports=initial_rate,
        mean_transport_km=mean,min_transport_km=100.,distance_distribution='shifted_exponential',
        long_share=info['nominal_long_share'],receipt_cutoff=receiptcut,receptivity_cutoff=receptcut,
        horizon=horizon,mode=mode,random_seed=seed,simulations=simulations,landscape_mode='rebuild',
        scale_transport_with_burden=scale,include_nidi_as_origins=feedback,
        burden_reference_counties=initial_n,**dict(zip(SPEED_FIELDS,speeds))),
        distance_distribution=info,candidates=int(seen.sum()),nidi=len(seeds),seeds=seeds,
        annual=summary,baseline_count=summary[-1]['baseline'],reached=summary[-1]['reached'],
        added=summary[-1]['added'],arrival=np.where(np.isfinite(scenario),scenario,-1).tolist(),
        baseline_arrival=np.where(np.isfinite(baseline),baseline,-1).tolist(),
        receptivity=a['receptivity'].tolist(),p_receipt=history[-1].tolist(),
        receipt_probability_history=np.asarray(history).tolist(),
        model_note='County count proxies burden. Delivery histories share the scenario front. Trucking volume is not measured; Interstate length weights routes. The drop-off map shows cumulative delivery probability, independently of habitat suitability.')
