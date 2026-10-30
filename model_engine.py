"""Annual translocation with burden scaling and feedback from established nidi.

Transport histories sample deliveries conditional on one shared scenario front.
Each year's rate and eligible origins use only counties reached by its start.
Nidus decisions use the cumulative ensemble receipt fraction and fixed habitat
cutoff. This is not10,000 independently evolving epidemic landscapes.
"""
import numpy as np
from model_utils import data,parse
from landscape_engine import landscape,travel,kernels,DEFAULT_SPEEDS

def annual_origins(arrival,start_year):
 k=kernels();occupied=arrival[k['road_global']]<=start_year;prob=[]
 for kind in ['short','long']:
  eligible=occupied if kind=='short' else occupied&k['long_capable'];weights=k['exposure']*eligible;total=weights.sum()
  prob.append(np.asarray((weights/total)@k[kind]).ravel() if total else np.zeros(len(arrival)))
 return prob[0],prob[1],int(occupied.sum())

def run(params):
 if not isinstance(params,dict):raise ValueError('Scenario inputs must be an object')
 observed=parse(params.get('observed_per_year',.2),0,20,'Observed detections/year');detection=parse(params.get('detection_probability',.01),.0001,1,'Detection probability');longshare=parse(params.get('long_share',.6),0,1,'Long-haul share');receiptcut=parse(params.get('receipt_cutoff',.5),0,1,'Receipt cutoff');receptcut=parse(params.get('receptivity_cutoff',.7928484500378316),0,1,'Receptivity cutoff');h=parse(params.get('horizon',20),1,20,'Horizon');seed=parse(params.get('random_seed',20261009),0,4294967295,'Random seed')
 if h!=int(h) or seed!=int(seed):raise ValueError('Horizon and seed must be whole numbers')
 horizon=int(h);seed=int(seed);mode=params.get('mode','monte_carlo')
 if mode not in ['monte_carlo','analytic']:raise ValueError('Calculation mode must be monte_carlo or analytic')
 scale=params.get('scale_transport_with_burden',True);feedback=params.get('include_nidi_as_origins',True)
 if not isinstance(scale,bool) or not isinstance(feedback,bool):raise ValueError('Burden scaling and origin feedback must be Boolean')
 speeds=tuple(parse(params.get(k,v),0,400,k) for k,v in zip(['speed_very_low','speed_low','speed_moderate','speed_high'],DEFAULT_SPEEDS))
 if any(v % 2 != 0 for v in speeds):raise ValueError('Spread speeds must be multiples of 2 km/year')
 if params.get('landscape_mode','rebuild')!='rebuild':raise ValueError('Updated habitat requires a rebuilt landscape')
 initial_rate=observed/detection
 if initial_rate>1000:raise ValueError('Initial inferred transport rate must be at most1000/year')
 a=data();baseline=landscape(speeds)['baseline'];scenario=baseline.copy();initial_n=int(np.sum(baseline==0));assert initial_n>0
 receptive=a['receptivity']>receptcut;road={int(ci):ri for ri,ci in enumerate(a['road_global'])};seen=np.zeros(len(baseline),dtype=bool);hits=np.zeros(len(baseline),dtype=np.int64);cumulative=np.zeros(len(baseline));rng=np.random.default_rng(seed);simulations=10000;seeds=[];summary=[];history=[]
 for year in range(1,horizon+1):
  # Scenario includes arrival forecasts from past nidi, but this mask uses
  # only counties actually reached by the start of the current year.
  occupied_start=scenario<=year-1;occupied_n=int(occupied_start.sum());factor=occupied_n/initial_n if scale else 1.;rate=initial_rate*factor
  origin_arrival=scenario if feedback else baseline;short,long,origin_n=annual_origins(origin_arrival,year-1)
  annual=rate*((1-longshare)*short+longshare*long);cumulative+=annual
  if mode=='monte_carlo':hits+=rng.binomial(simulations-hits,-np.expm1(-annual));p=hits/simulations
  else:p=-np.expm1(-cumulative)
  history.append(p.copy());crossed=(p>receiptcut)&receptive&~seen;seen|=crossed;candidate=np.flatnonzero(crossed);usable=[int(i) for i in candidate if scenario[i]>year and int(i) in road]
  for i in usable:
   scenario[i]=year;seeds.append({'index':i,'year':year,'p_receipt':round(float(p[i]),4),'receptivity':round(float(a['receptivity'][i]),4)})
  for i in usable:np.minimum(scenario,year+1+travel(speeds,i),out=scenario)
  summary.append({'year':year,'endemic_counties_at_start':occupied_n,'burden_multiplier':factor,'annual_infectious_transport_mean':rate,'expected_detected_transports':rate*detection,'eligible_road_origin_counties':origin_n,'short_destination_probability_mass':float(short.sum()),'long_destination_probability_mass':float(long.sum()),'annual_assigned_transport_mean':float(annual.sum()),'candidate_count':len(candidate),'nidi':len(usable),'baseline':int(np.sum(baseline<=year)),'reached':int(np.sum(scenario<=year)),'added':int(np.sum((scenario<=year)&(baseline>year)))})
 return {'inputs':{'distance_unit':'km','speed_unit':'km/year','speed_step':2,'observed_per_year':observed,'detection_probability':detection,'initial_annual_infectious_transports':initial_rate,'annual_infectious_transports':initial_rate,'long_share':longshare,'receipt_cutoff':receiptcut,'receptivity_cutoff':receptcut,'horizon':horizon,'mode':mode,'random_seed':seed,'simulations':simulations,'landscape_mode':'rebuild','scale_transport_with_burden':scale,'include_nidi_as_origins':feedback,'burden_reference_counties':initial_n,**dict(zip(['speed_very_low','speed_low','speed_moderate','speed_high'],speeds))},'candidates':int(seen.sum()),'nidi':len(seeds),'seeds':seeds,'annual':summary,'baseline_count':summary[-1]['baseline'],'reached':summary[-1]['reached'],'added':summary[-1]['added'],'arrival':np.where(np.isfinite(scenario),scenario,-1).tolist(),'baseline_arrival':np.where(np.isfinite(baseline),baseline,-1).tolist(),'receptivity':a['receptivity'].tolist(),'p_receipt':np.round(history[-1],4).tolist(),'receipt_probability_history':np.asarray(history).tolist(),'model_note':'County count is a burden proxy with constant average burden per reached county. Frontier and nidus decisions are shared scenario-level states; delivery histories are sampled conditional on this state.'}
