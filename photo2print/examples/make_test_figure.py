"""Make a small textured Y-up test figure: python examples/make_test_figure.py test.glb"""
import numpy as np, trimesh, sys
from PIL import Image
# Y-up figure: base disc, legs (pants), torso (shirt), head (skin) as one textured mesh
parts=[]
def add(m, color): parts.append((m,color))
add(trimesh.creation.cylinder(radius=30, height=6, sections=64), (140,135,135))   # base
for x in (-8,8):
    leg=trimesh.creation.cylinder(radius=6, height=40, sections=32); leg.apply_translation([x,0,23]); add(leg,(205,192,180))
t=trimesh.creation.cylinder(radius=14, height=35, sections=48); t.apply_translation([0,0,58]); add(t,(224,32,108))
h=trimesh.creation.icosphere(subdivisions=4, radius=9); h.apply_translation([0,0,84]); add(h,(240,170,130))
mesh=trimesh.util.concatenate([p for p,_ in parts])
# texture: 1 pixel column per color; uv per vertex by owning part
tex=np.zeros((8,len(parts)*8,3),np.uint8)
uv=[]
for i,(p,c) in enumerate(parts):
    tex[:,i*8:(i+1)*8]=c
    uv.append(np.tile([(i*8+4)/tex.shape[1],0.5],(len(p.vertices),1)))
uv=np.vstack(uv)
mesh.visual=trimesh.visual.TextureVisuals(uv=uv,material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(tex),baseColorFactor=[255,255,255,255]))
mesh.apply_transform(trimesh.transformations.rotation_matrix(-np.pi/2,[1,0,0]))  # to Y-up like glTF
mesh.export(sys.argv[1])
