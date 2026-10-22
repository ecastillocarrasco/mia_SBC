#!/usr/bin/env python3
"""Generate high-resolution cutouts from the OFFICIAL Sunset Beach Club logo.

Input is the original 958x806 white-background image supplied with the frontend
(public/assets/sunset_beach_club_logo_blanco.jpg, copied to loading/master-hq.jpg).
The source is NOT redrawn, lettered again, or supplemented with extra shapes.
Exactly one of the nine components owns each non-transparent pixel.
"""
from pathlib import Path
import numpy as np
from PIL import Image

BASE = Path(__file__).resolve().parents[1] / 'public/assets/loading'
SOURCE = BASE / 'sunset-beach-club-master-hq.jpg'
PARTS = BASE / 'logo-pieces'
PARTS.mkdir(exist_ok=True)

src = np.asarray(Image.open(SOURCE).convert('RGB'), dtype=np.float32)
h, w, _ = src.shape
assert (w,h) == (958,806), f'Unexpected source size {w}x{h}'
y,x = np.mgrid[:h,:w]

# Anti-aliased extraction using the real navy/red/yellow ink shades.
# Match each JPG pixel against a white/ink mixture to reduce JPG chromatic
# halos instead of enlarging the 342px copy or adding a blur filter.
inks = np.array([[21,35,82],[235,0,48],[250,213,0]],dtype=np.float32)
v = 255-src
scores=[]
for color in inks:
    direction=255-color
    alpha=np.clip(np.sum(v*direction,axis=2)/np.sum(direction*direction),0,1)
    predicted=255-alpha[...,None]*direction
    residual=np.sum((predicted-src)**2,axis=2)
    scores.append((residual,alpha))
label=np.argmin(np.stack([s[0] for s in scores],axis=-1),axis=-1)
opacity=np.take_along_axis(np.stack([s[1] for s in scores],axis=-1),label[...,None],axis=-1)[...,0]
# Reject JPEG-white grain around the letters, while keeping true antialiasing.
opacity=np.clip((opacity-.050)/.950,0,1)
opacity[np.max(v,axis=2)<15]=0
opacity=np.where(opacity<.025,0,opacity)
rgba=np.zeros((h,w,4),dtype=np.uint8)
rgba[:,:,:3] = np.clip(inks[label],0,255).astype(np.uint8)
rgba[:,:,3] = np.rint(opacity*255).astype(np.uint8)
# Rounded alpha only: artwork silhouettes and layout are untouched.
visible=rgba[:,:,3]>0

names=['sol','arco-exterior','arco-rojo','arco-interior',
       'estrella-1','estrella-2','estrella-3','estrella-4','nombre']
owner=np.full((h,w),8,dtype=np.int8) # default is the original lettering
# Four stars: actual locations, not generated stars.
for index,cx in enumerate([324,432,537,642], start=4):
    owner[(y<95) & (abs(x-cx)<52)] = index
# A single sun body is made of yellow and the existing lower red disk.
owner[(y<400) & (label==2)] = 0
owner[(y>=283) & (y<393) & (x>=370) & (x<=610) & (label==1)] = 0
# Everything else in the authentic arc region, split without painting new arcs.
region=(y>=105)&(y<343)&(x>=266)&(x<701)&(owner==8)
red_arc=(region & (label==1))
owner[red_arc]=2
# Estimate each column's source red stripe bounds, then assign navy pixels
# to the outer/inner exact layers according to the existing stripe geometry.
red_ys=[]
for col in range(w):
    ys=np.where(red_arc[:,col])[0]
    red_ys.append((int(ys.min()),int(ys.max())) if len(ys) else None)
valid=np.array([i for i,a in enumerate(red_ys) if a is not None])
assert len(valid)>200
closest=valid[np.argmin(abs(np.arange(w)[:,None]-valid[None,:]),axis=1)]
lo=np.array([red_ys[c][0] for c in closest]);hi=np.array([red_ys[c][1] for c in closest])
remaining=region & (owner==8)
owner[remaining & (y<lo[None,:])] = 1
owner[remaining & (y>=lo[None,:])] = 3
# In the rear navy band the inner arch could dip beneath the red line.
# Whole base layer exactly equals the sum of its separated components.
base=Image.fromarray(rgba,'RGBA')
base.save(BASE/'sunset-beach-club-logo.png',optimize=True)
for idx,name in enumerate(names):
    result=rgba.copy()
    result[:,:,3][owner!=idx]=0
    im=Image.fromarray(result,'RGBA')
    assert im.getbbox(), f'Missing real artwork: {name}'
    im.save(PARTS/f'{name}.png',optimize=True)
# Pixel-perfect ownership of the new extracted original, including all fades.
count=np.zeros((h,w),dtype=np.int8)
for idx in range(len(names)):
    count+=(owner==idx)&visible
assert np.all(count[visible]==1)
assert np.all(count[~visible]==0)
print(f'OK: 9 original layers {w}x{h}; {visible.sum()} nontransparent pixels owned exactly once')
