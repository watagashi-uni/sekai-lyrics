"""Synthetic controls for false offsets, silence and mismatched edits."""
import importlib.util
from pathlib import Path
import numpy as np
spec=importlib.util.spec_from_file_location('mapping',Path(__file__).with_name('map-vocal-audio.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
rng=np.random.default_rng(20261114)
x=rng.normal(0,.1,4000*70)
y=np.r_[np.zeros(4000),x]
a=m.compare(x,y)
assert a['accepted'] and a['sourceMinusTarget']==-1,a
assert not m.compare(x,np.zeros_like(x))['accepted']
assert not m.compare(x,rng.normal(0,.1,len(x)))['accepted']
z=x.copy();z[30*4000:40*4000]=rng.normal(0,.1,10*4000)
assert not m.compare(x,z)['accepted'], 'unverified middle section must fail'
print('audio mapping positive/negative controls passed')
