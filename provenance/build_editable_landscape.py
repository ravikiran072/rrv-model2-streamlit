"""Prepare an editable-speed graph from the saved reconstruction.

Preserves every existing node and edge. Adds dry grid centers in the original
zero-speed habitat class, so that class can also be activated. New-edge water
tests use the same original Natural Earth files. No GIS packages are required:
the build uses NumPy, SciPy, and Matplotlib's public path operations.
"""
import json
import argparse
import math
import sqlite3
import struct
import sys
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from matplotlib.path import Path as GeoPath
from scipy.sparse import load_npz

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "source_model2"
OUT = Path(__file__).resolve().parent / "rrv_model2"
LABELS = ["No/very low", "Low", "Moderate", "High"]


def project(xy):
    """GRS80 Albers, EPSG:5070 (lon0=-96, lat0=23, lat1=29.5, lat2=45.5)."""
    a, e2 = 6378137., 0.006694380022900787
    e = math.sqrt(e2)
    def mq(p):
        s = np.sin(p)
        return (np.cos(p)/np.sqrt(1-e2*s*s),
                (1-e2)*(s/(1-e2*s*s)-np.log((1-e*s)/(1+e*s))/(2*e)))
    m1, q1 = mq(np.deg2rad(29.5)); m2, q2 = mq(np.deg2rad(45.5))
    n = (m1*m1-m2*m2)/(q2-q1); c = m1*m1+n*q1
    _, q0 = mq(np.deg2rad(23.)); _, q = mq(np.deg2rad(xy[:, 1]))
    rho = a*np.sqrt(c-n*q)/n; rho0 = a*np.sqrt(c-n*q0)/n
    theta = n*np.deg2rad(xy[:, 0]+96)
    return np.column_stack((rho*np.sin(theta), rho0-rho*np.cos(theta)))


def shapes(file):
    """Read the original Polygon/PolyLine shapefile records and DBF attributes."""
    with ZipFile(file) as z:
        shp = z.read(next(n for n in z.namelist() if n.endswith('.shp')))
        dbf = z.read(next(n for n in z.namelist() if n.endswith('.dbf')))
    count, header, length = struct.unpack_from('<IHH', dbf, 4)
    fields=[]; pos=32
    while dbf[pos] != 13:
        f=dbf[pos:pos+32];fields.append((f[:11].split(b'\0')[0].decode(),f[16]));pos+=32
    offset=100
    for i in range(count):
        nbytes=struct.unpack_from('>i',shp,offset+4)[0]*2
        record=shp[offset+8:offset+8+nbytes];offset+=8+nbytes
        if struct.unpack_from('<i',record)[0] not in (3,5):continue
        row=dbf[header+i*length:header+(i+1)*length];values={};p=1
        for name,size in fields:values[name]=row[p:p+size].decode('latin1').strip('\x00 \t\r\n');p+=size
        nparts,npts=struct.unpack_from('<ii',record,36)
        starts=np.frombuffer(record,dtype='<i4',count=nparts,offset=44)
        xy=np.frombuffer(record,dtype='<f8',count=npts*2,offset=44+4*nparts).reshape(-1,2)
        if xy[:,0].max() < -125 or xy[:,0].min() > -65 or xy[:,1].max() < 24 or xy[:,1].min() > 51:continue
        projected=project(xy)
        rings=[projected[s:t] for s,t in zip(starts,np.r_[starts[1:],len(xy)])]
        yield values,rings


def wkb_rings(blob):
    start=8+{0:0,1:32,2:48,3:48,4:64}[(blob[3]>>1)&7]
    def geom(pos):
        endian='<' if blob[pos]==1 else '>';kind=struct.unpack_from(endian+'I',blob,pos+1)[0];pos+=5
        count=struct.unpack_from(endian+'I',blob,pos)[0];pos+=4;out=[]
        if kind==6:
            for _ in range(count):
                rings,pos=geom(pos);out.extend(rings)
        elif kind==3:
            for _ in range(count):
                n=struct.unpack_from(endian+'I',blob,pos)[0];pos+=4
                out.append(np.frombuffer(blob,dtype=endian+'f8',count=2*n,offset=pos).reshape(-1,2));pos+=16*n
        else:raise ValueError('Unexpected geometry '+str(kind))
        return out,pos
    return geom(start)[0]


def inside(xy,rings):
    mask=np.zeros(len(xy),bool)
    for ring in rings:mask^=GeoPath(ring,closed=True).contains_points(xy)
    return mask


def crosses(a,b,features):
    """Boundary intersections, with bounding-box pruning for the small build."""
    out=np.zeros(len(a),bool)
    lo=np.minimum(a,b);hi=np.maximum(a,b)
    for rings in features:
        xy=np.concatenate(rings);low=xy.min(axis=0);high=xy.max(axis=0)
        idx=np.flatnonzero(~out & (hi[:,0]>=low[0]) & (lo[:,0]<=high[0]) & (hi[:,1]>=low[1]) & (lo[:,1]<=high[1]))
        paths=[GeoPath(r) for r in rings]
        for i in idx:
            edge=GeoPath(np.array([a[i],b[i]]))
            out[i]=any(p.intersects_path(edge,filled=False) for p in paths)
    return out


def main():
    global SRC, OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=SRC,help='Extracted upstream reconstruction directory')
    parser.add_argument('--output',type=Path,default=OUT,help='Website directory for prepared NPZ files')
    args=parser.parse_args();SRC=args.source;OUT=args.output;OUT.mkdir(parents=True,exist_ok=True)
    m=json.loads((SRC/'reconstruction/county_metadata.json').read_text())
    classes=np.array([LABELS.index(c['habitat_receptivity_class']) for c in m],dtype=np.int8)
    z=np.load(SRC/'water_reconstruction/water_grid_objects.npz')
    grid=z['grid_to_node'].copy();xy=z['node_xy'];county=z['node_county'];nold=len(xy)
    yy,xx=np.where(grid<0)
    missing=np.column_stack((float(z['grid_x0'])+(xx+.5)*10000,float(z['grid_y0'])+(yy+.5)*10000))
    new_county=np.full(len(missing),-1,dtype=np.int32)
    db=sqlite3.connect(SRC/'accepted/county_arrival_p50_recept50.gpkg')
    blobs=db.execute('SELECT geom FROM county_arrival ORDER BY fid').fetchall();db.close()
    centers=[]
    # Polygon area centroids use the already-projected source geometries.
    for (blob,) in blobs:
        numer=np.zeros(2);denom=0.
        for ring in wkb_rings(blob):
            nxt=np.roll(ring,-1,axis=0);cross=ring[:,0]*nxt[:,1]-nxt[:,0]*ring[:,1]
            numer+=np.sum((ring+nxt)*cross[:,None],axis=0);denom+=3*cross.sum()
        centers.append(numer/denom)
    centers=np.asarray(centers)
    for ci in np.flatnonzero(classes==0):
        rings=wkb_rings(blobs[ci][0]);allxy=np.concatenate(rings);lo=allxy.min(axis=0);hi=allxy.max(axis=0)
        candidates=np.flatnonzero((missing[:,0]>=lo[0])&(missing[:,0]<=hi[0])&(missing[:,1]>=lo[1])&(missing[:,1]<=hi[1]))
        new_county[candidates[inside(missing[candidates],rings)]]=ci
    lakefeatures=[]
    for record,rings in shapes(SRC/'water_sources/natural_earth_lakes.zip'):
        area=abs(sum(.5*np.sum(r[:,0]*np.roll(r[:,1],-1)-np.roll(r[:,0],-1)*r[:,1]) for r in rings))
        if area>=100_000_000:lakefeatures.append(rings)
    candidates=np.flatnonzero(new_county>=0);water=np.zeros(len(candidates),bool)
    for rings in lakefeatures:water|=inside(missing[candidates],rings)
    candidates=candidates[~water]
    grid[yy[candidates],xx[candidates]]=nold+np.arange(len(candidates))
    xy=np.vstack((xy,missing[candidates]));county=np.r_[county,new_county[candidates]]
    graph=load_npz(SRC/'water_reconstruction/water_grid_graph.npz').tocoo()
    orig=np.flatnonzero(graph.row<graph.col);old_u=graph.row[orig];old_v=graph.col[orig]
    old_key=old_u.astype(np.int64)*len(xy)+old_v;sort=np.argsort(old_key);old_key=old_key[sort]
    speeds=z['node_speed_miles_per_year'];old_factor=graph.data[orig][sort]/(.5*(1/speeds[old_u[sort]]+1/speeds[old_v[sort]]))
    rivers=[rings for rec,rings in shapes(SRC/'water_sources/natural_earth_rivers.zip') if rec['featurecla']=='River' and int(rec['scalerank'])<=6]
    us=[];vs=[];cs=[];ds=[];factors=[];ny,nx=grid.shape
    for dx,dy in ((1,0),(0,1),(1,1),(1,-1)):
        if dy==-1:a,b=grid[1:,:-1],grid[:-1,1:];c,d=grid[1:,1:],grid[:-1,:-1]
        elif dx==1 and dy==1:a,b=grid[:-1,:-1],grid[1:,1:];c,d=grid[:-1,1:],grid[1:,:-1]
        elif dx==1:a,b=grid[:,:-1],grid[:,1:];c=d=None
        else:a,b=grid[:-1,:],grid[1:,:];c=d=None
        mask=(a>=0)&(b>=0)
        if c is not None:mask&=(c>=0)&(d>=0)
        u,v=a[mask],b[mask];corner1=c[mask] if c is not None else np.full(len(u),-1);corner2=d[mask] if d is not None else np.full(len(u),-1)
        key=np.minimum(u,v).astype(np.int64)*len(xy)+np.maximum(u,v);idx=np.searchsorted(old_key,key);found=(idx<len(old_key)) & (old_key[np.minimum(idx,len(old_key)-1)]==key)
        was_possible=(u<nold)&(v<nold)&(corner1<nold)&(corner2<nold)
        keep=found.copy();new=np.flatnonzero(~was_possible)
        blocked=crosses(xy[u[new]],xy[v[new]],lakefeatures);new=new[~blocked];keep[new]=True
        factor=np.full(len(u),10000*math.hypot(dx,dy)/1609.344)
        factor[found]=old_factor[idx[found]]
        river=crosses(xy[u[new]],xy[v[new]],rivers);factor[new[river]]*=4
        us.append(u[keep]);vs.append(v[keep]);cs.append(corner1[keep]);ds.append(corner2[keep]);factors.append(factor[keep])
        print('Neighbors',dx,dy,'kept',int(keep.sum()),'new',len(new),flush=True)
    # Preserve non-neighbor special link (the mapped Sandusky Bay connection).
    extra=np.linalg.norm(xy[old_u]-xy[old_v],axis=1)>15000
    us.append(old_u[extra]);vs.append(old_v[extra]);cs.append(np.full(extra.sum(),-1));ds.append(np.full(extra.sum(),-1))
    sp=.5*(1/speeds[old_u[extra]]+1/speeds[old_v[extra]])
    factors.append(graph.data[orig][extra]/sp)
    u,v,c,d=map(np.concatenate,(us,vs,cs,ds));factor=np.concatenate(factors)
    active=(u<nold)&(v<nold)&(c<nold)&(d<nold)
    assert len(u[active])==len(orig),(len(u[active]),len(orig))
    keys=np.minimum(u[active],v[active]).astype(np.int64)*len(xy)+np.maximum(u[active],v[active]);order=np.argsort(keys)
    assert np.array_equal(keys[order],old_key)
    assert np.allclose(factor[active][order],old_factor,rtol=2e-7)
    # Cross-check new projection/intersection implementation on original river crossings.
    river_old=np.flatnonzero(np.isclose(old_factor/(np.linalg.norm(xy[old_u[sort]]-xy[old_v[sort]],axis=1)/1609.344),4,rtol=1e-4))
    sample=river_old[np.linspace(0,len(river_old)-1,min(100,len(river_old)),dtype=int)]
    checked=crosses(xy[old_u[sort][sample]],xy[old_v[sort][sample]],rivers)
    print('Water features',len(lakefeatures),len(rivers),'river audit',checked.sum(),len(checked),flush=True)
    for si in sample[~checked][:3]: print('Audit miss',xy[old_u[sort][si]],xy[old_v[sort][si]],flush=True)
    assert checked.all()
    np.savez_compressed(OUT/'landscape_data.npz',node_xy=xy,node_county=county,county_class=classes,county_center_xy=centers,edge_u=u,edge_v=v,corner1=c,corner2=d,effective_miles=factor,initial_county=np.array([c['baseline_arrival_year']==0 for c in m]),original_nodes=nold,original_origin_nodes=z['origin_node_by_county'])
    routing=np.load(SRC/'reconstruction/translocation_routing_objects.npz');road_global=routing['road_global'];kernels=[]
    for kind in range(2):
        kernel=np.zeros((len(road_global),len(m)),dtype=np.float64)
        bw=routing['short_probs_mc'] if kind==0 else routing['long_probs_mc']
        for oi in range(len(road_global)):
            for band,weight in enumerate(bw):
                actual=int(routing['fallback_band'][oi,band+4*kind])
                if actual<0:continue
                first,last=routing['candidate_offsets'][oi*8+actual:oi*8+actual+2]
                dest=road_global[routing['candidate_indices'][first:last]];w=routing['candidate_probabilities'][first:last].astype(float)
                np.add.at(kernel[oi],dest,weight*w/w.sum())
        kernels.append(kernel)
    np.savez_compressed(OUT/'route_kernels.npz',short=kernels[0],long=kernels[1],road_global=road_global,exposure=routing['road_exposure'],long_capable=routing['long_capable'])
    print('Saved',len(xy),'nodes;',len(u),'edges;',len(candidates),'added zero-class cells; exact original graph retained.')


if __name__=='__main__':main()
