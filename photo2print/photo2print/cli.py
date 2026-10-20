"""Command line: python -m photo2print <command> ..."""
import argparse
import json
import os
import re

import numpy as np
import trimesh

from . import image_tools, meshy, split, threemf
from .colors import hex_to_rgb, load_filaments


def _slug(s):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_") or "part"


def cmd_background(a):
    share = image_tools.flatten_background(a.image, a.out, a.color, a.tolerance)
    print(f"Saved {a.out} (subject covers {share:.0%} of the frame)")


def cmd_palette(a):
    entries = image_tools.suggest_palette(a.image, a.colors, a.out, a.preview, a.tolerance)
    for e in entries:
        print(f"  {e['hex']}  {e['share']:6.1%}")
    print(f"Saved {a.out} - rename the colors to your filaments, set 'slot' to the "
          f"AMS/tool number, and merge or delete entries you do not want.")
    if a.preview:
        print(f"Saved {a.preview} (left: photo, right: photo snapped to the palette)")


def cmd_meshy(a):
    meshy.image_to_3d(a.image, a.out, ai_model=a.ai_model,
                      target_polycount=a.polycount, api_key=a.api_key)


def cmd_split(a):
    filaments = load_filaments(a.filaments) if a.filaments else None
    core = None
    if a.core:
        if not filaments:
            raise SystemExit("--core needs --filaments")
        names = [f["name"].lower() for f in filaments]
        if a.core.lower() not in names:
            raise SystemExit(f"--core {a.core!r} is not one of: {', '.join(names)}")
        core = names.index(a.core.lower())

    parts, filaments = split.split_model(
        a.model, filaments=filaments, n_auto=a.colors, height_mm=a.height, up=a.up,
        pitch=a.pitch, smooth=a.smooth, min_island_mm3=a.min_island, sigma=a.sigma,
        core=core, shell_mm=a.shell, close_iters=a.close, max_faces=a.max_faces,
        surface=a.surface, clean=a.clean)
    if not parts:
        raise SystemExit("No parts were produced")

    os.makedirs(a.out, exist_ok=True)
    name = a.name or os.path.splitext(os.path.basename(a.model))[0]
    records, scene = [], trimesh.Scene()
    for idx, m in parts:
        f = filaments[idx]
        stl = os.path.join(a.out, f"{name}_{f['slot']:02d}_{_slug(f['name'])}.stl")
        m.export(stl)
        records.append({"name": f["name"], "hex": f["hex"], "slot": f["slot"], "mesh": m,
                        "stl": os.path.basename(stl)})
        colored = m.copy()
        colored.visual.face_colors = list(hex_to_rgb(f["hex"])) + [255]
        scene.add_geometry(colored, node_name=f["name"])

    bambu = os.path.join(a.out, f"{name}_bambu_orca.3mf")
    prusa = os.path.join(a.out, f"{name}_prusa.3mf")
    threemf.write_bambu(bambu, records, name=name)
    threemf.write_prusa(prusa, records, name=name)
    scene.export(os.path.join(a.out, f"{name}_preview.glb"))

    with open(os.path.join(a.out, f"{name}_parts.json"), "w") as fh:
        json.dump([{k: r[k] for k in ("name", "hex", "slot", "stl")} |
                   {"faces": int(len(r["mesh"].faces)),
                    "volume_cm3": round(float(r["mesh"].volume) / 1000, 3),
                    "watertight": bool(r["mesh"].is_watertight)} for r in records],
                  fh, indent=2)

    print(f"\nWrote to {a.out}/")
    print(f"  {os.path.basename(bambu)}  <- open in Bambu Studio / OrcaSlicer")
    print(f"  {os.path.basename(prusa)}  <- open in PrusaSlicer")
    print("  one STL per color, a colored preview .glb and a parts.json summary")
    print("Filament slots used: " + ", ".join(
        f"{r['slot']}={r['name']} ({r['hex']})" for r in sorted(records, key=lambda r: r["slot"])))


def main(argv=None):
    p = argparse.ArgumentParser(prog="photo2print", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("background", help="flatten a near-solid background")
    b.add_argument("image")
    b.add_argument("-o", "--out", required=True)
    b.add_argument("--color", default="#FFFFFF", help="hex color or 'transparent'")
    b.add_argument("--tolerance", type=float, default=10.0)
    b.set_defaults(func=cmd_background)

    c = sub.add_parser("palette", help="suggest a filament palette from the picture")
    c.add_argument("image")
    c.add_argument("-n", "--colors", type=int, default=8)
    c.add_argument("-o", "--out", default="filaments.json")
    c.add_argument("--preview", help="PNG showing the photo snapped to the palette")
    c.add_argument("--tolerance", type=float, default=10.0)
    c.set_defaults(func=cmd_palette)

    m = sub.add_parser("meshy", help="image -> textured GLB with the Meshy API")
    m.add_argument("image", help="local file or URL")
    m.add_argument("-o", "--out", default="model.glb")
    m.add_argument("--ai-model", default="latest",
                   help="Meshy model name, e.g. latest, meshy-6 (default: latest)")
    m.add_argument("--polycount", type=int, default=300000)
    m.add_argument("--api-key")
    m.set_defaults(func=cmd_meshy)

    s = sub.add_parser("split", help="textured model -> watertight part per filament + 3MF")
    s.add_argument("model", help="GLB/GLTF/OBJ/PLY with texture or vertex colors")
    s.add_argument("-f", "--filaments", help="filaments.json (otherwise auto palette)")
    s.add_argument("-n", "--colors", type=int, default=6, help="auto palette size")
    s.add_argument("-o", "--out", default="out")
    s.add_argument("--name")
    s.add_argument("--height", type=float, default=120.0, help="final height in mm")
    s.add_argument("--up", choices=["y", "z"], default="y",
                   help="up axis of the input (Meshy GLB is y)")
    s.add_argument("--pitch", type=float, default=None,
                   help="voxel size in mm; smaller = finer color edges, more RAM "
                        "(default 0.4 with the original surface, 0.3 with voxel)")
    s.add_argument("--smooth", type=int, default=3, help="face label smoothing passes")
    s.add_argument("--sigma", type=float, default=0.7, help="surface smoothing (voxels)")
    s.add_argument("--surface", choices=["auto", "original", "voxel"], default="auto",
                   help="original = keep Meshy's surface exactly (needs a closed mesh); "
                        "voxel = rebuild it from voxels; auto = original when possible")
    s.add_argument("--clean", type=int, default=2,
                   help="majority-filter passes that tidy color borders (0 = off)")
    s.add_argument("--min-island", type=float, default=3.0,
                   help="merge color islands smaller than this (mm^3)")
    s.add_argument("--core", help="filament name used for the hidden inside")
    s.add_argument("--shell", type=float, default=2.0,
                   help="color shell thickness in mm when --core is set")
    s.add_argument("--close", type=int, default=1, help="hole closing passes before filling")
    s.add_argument("--max-faces", type=int, default=400000, help="per part, 0 = no limit")
    s.set_defaults(func=cmd_split)

    a = p.parse_args(argv)
    np.seterr(all="ignore")
    a.func(a)


if __name__ == "__main__":
    main()
