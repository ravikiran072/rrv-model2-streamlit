"""Shared input loading and validation for the accepted Model2 runtime."""
from pathlib import Path
from functools import lru_cache
import numpy as np
ROOT=Path(__file__).resolve().parent
@lru_cache(maxsize=1)
def data():
 with np.load(ROOT/'model_data.npz') as z:return {k:z[k] for k in z.files}
def parse(value,low,high,name):
 x=float(value)
 if not np.isfinite(x) or x<low or x>high:raise ValueError(f'{name} must be between {low:g} and {high:g}')
 return x
