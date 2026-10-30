"""Prepare website transport_routes.npz from the original reconstruction archive.
Usage: python prepare_transport_routes.py ORIGINAL_RECONSTRUCTION WEBSITE_FOLDER
"""
import sys
from pathlib import Path
import numpy as np
source,output=map(Path,sys.argv[1:3])
with np.load(source/'routed_distances.npz') as z:
 distance=z['miles'].astype(np.float64)*1.609344
 road=z['road_global'];exposure=z['road_exposure_miles']*1.609344
with np.load(source/'translocation_routing_objects.npz') as z:
 assert np.array_equal(road,z['road_global'])
 longitude=z['road_longitude']
with np.load(output/'model_data.npz') as z:
 assert np.array_equal(road,z['road_global'])
np.savez_compressed(output/'transport_routes.npz',distance_km=distance,road_global=road,exposure_km=exposure,longitude=longitude)
