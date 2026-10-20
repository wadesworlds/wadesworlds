# photo2print: turn a photo into a multi-color 3MF

Turns a photo into a 3D-printable figure where every color (shirt, pants,
skin, shoes, base...) is its **own watertight solid** with a filament already
assigned. You open the 3MF and slice it without painting any colors.

```
1  photo from camera
2  AI image with a solid background      -> photo2print background / palette
3  Meshy image-to-3D (textured GLB)      -> photo2print meshy
4  split by color into watertight parts, -> photo2print split
   rebuild the figure as one multi-part 3MF
```

## Install

```bash
cd photo2print
pip install -r requirements.txt
pip install fast-simplification   # optional: shrinks big parts in voxel mode
```

## Workflow

### 1-2. Picture with a solid background
Make the picture however you like (OpenAI, etc.). If the backdrop is grey or
has a gradient, you can flatten it to white or transparent first:

```bash
python -m photo2print background couple.png -o couple_flat.png            # white
python -m photo2print background couple.png -o couple.png --color transparent
```

### Pick your filaments
Get a suggested palette from the picture, then edit it to match the spools you own:

```bash
python -m photo2print palette couple.png -n 10 -o filaments.json --preview palette.png
```

`palette.png` shows the photo next to the photo snapped to those colors.
Edit `filaments.json` (see `examples/filaments.example.json`):

```json
{"name": "Magenta PLA", "hex": "#E92576", "slot": 4, "match": ["#D11859"]}
```

* `hex`: the filament color. Each texture pixel goes to the closest filament.
* `slot`: the AMS / tool / extruder number this part prints with.
* `match` (optional): extra texture colors that should also use this
  filament, e.g. the shadow side of the shirt or darker skin tones.

Fewer filaments give cleaner parts. Merge colors you don't need, like the
logo on a cap.

### 3. Make the 3D model with Meshy
On meshy.ai, make an Image-to-3D model **with texture** and download the
**GLB**. Or use the API (needs `MESHY_API_KEY`):

```bash
export MESHY_API_KEY=msy_...
python -m photo2print meshy couple_flat.png -o couple.glb                # ai_model=latest
python -m photo2print meshy couple_flat.png -o couple.glb --ai-model meshy-6
```

### Check which model colors go to which filament
Meshy's texture has its own shadows and shades, which can differ from the photo.
List the colors actually painted on the model, and the filament each one goes to:

```bash
python -m photo2print colors couple.glb -f filaments.json -o model_colors.png
```

If a shadow color goes to the wrong filament (for example, a dark shirt shadow
turning black), add its hex to the right filament's `"match"` list.

### 4. Split by color and rebuild

```bash
python -m photo2print split couple.glb -f filaments.json --height 150 -o out
```

Output in `out/`:

| file | use |
|---|---|
| `couple_bambu_orca.3mf` | Bambu Studio / OrcaSlicer: one object, one part per color, extruder already set |
| `couple_prusa.3mf` | PrusaSlicer: same thing in Prusa's format |
| `couple_NN_<filament>.stl` | one watertight STL per color, in case you want to load them by hand |
| `couple_preview.glb` | colored preview (open in any 3D viewer or Windows 3D Viewer) |
| `couple_parts.json` | faces, volume and watertight check for each part |

If a slicer doesn't take the 3MF, select all the STLs and drag them in
together, then answer **Yes** to "load as a single object with multiple
parts". The parts share coordinates, so they snap back into the figure.

In the slicer, make sure the project has at least as many filaments as the
highest `slot` you used, and set each filament slot's color to match.

## Useful `split` options

| option | default | meaning |
|---|---|---|
| `--height` | 120 | final height in mm |
| `--surface` | auto | `original` keeps Meshy's surface exactly (needs a closed model). `voxel` rebuilds it from voxels (smoother, less detail). `auto` uses original when it can |
| `--pitch` | 0.4 / 0.3 | voxel size (mm) for the color borders. Smaller gives sharper borders but uses more RAM and time |
| `--clean` | 2 | passes that tidy ragged color borders |
| `--min-island` | 3.0 | color blobs smaller than this (mm³) join their neighbor. Raise it (e.g. 10) for fewer specks |
| `--smooth` | 3 | passes that clean up speckled texture colors |
| `--sigma` | 0.7 | how smooth the color borders are |
| `--core NAME --shell MM` | off | only the outer MM mm is colored; the hidden inside is printed with filament NAME, so fewer filament changes inside |
| `--up z` | y | use if your model is already Z-up (Meshy GLB is Y-up) |
| `--close 2` | 1 | use if you get the "mesh shell seems open" warning |
| `--max-faces` | 400000 | per-part triangle limit, voxel surface only (needs `fast-simplification`) |
| `-n 6` (no `-f`) | | no filament file: auto-cluster the texture into 6 colors |

## How it works

1. Loads the textured mesh, turns it Z-up, scales it to `--height` and sets it on the bed.
2. Reads the texture color under each triangle and snaps it to the nearest filament (CIELAB).
3. A neighbor majority vote removes speckles.
4. Voxelizes the model. Surface voxels take the filament of the triangle
   they touch, and each inside voxel takes the filament of the nearest
   surface voxel (or the `--core` filament below `--shell`). A majority
   filter and island merge tidy the color regions.
5. **Original surface** (default): each color region is turned into a smooth
   solid, and neighboring regions share exactly the same border. The tool
   then cuts each region out of the original Meshy model with exact boolean
   operations (manifold3d). The outside keeps all of Meshy's detail; only the
   hidden borders between colors come from the voxels. Separate or
   overlapping shells are fused first, and small holes are filled.
6. **Voxel surface** (fallback for broken models): marching cubes per color.
7. Every part comes out closed and watertight, the parts don't overlap, and
   together they rebuild the figure.

## Tips

* Color areas smaller than `--min-island` (eyes, logos, laces) are merged
  into a neighbor color. The shape detail itself is kept.
* Ask Meshy for a high-poly model with a texture. PBR is not needed.
* If the shirt picks up shading as a different color, add those shades to
  the shirt filament's `match` list.

## Quick self-test (no Meshy needed)

```bash
python examples/make_test_figure.py test.glb
python -m photo2print split test.glb -n 4 -o out_test
```
