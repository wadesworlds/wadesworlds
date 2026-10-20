"""Color helpers: sRGB <-> CIELAB, palettes, k-means, filament files."""
import json

import numpy as np


def hex_to_rgb(h):
    h = h.strip().lstrip("#")
    if len(h) != 6:
        raise ValueError(f"bad hex color: {h!r}")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*(int(round(c)) for c in rgb[:3]))


def rgb_to_lab(rgb):
    """rgb: (..., 3) array in 0-255. Returns CIELAB (D65)."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def nearest(colors_lab, palette_lab):
    """Index of the nearest palette entry (CIE76 distance) for each color."""
    d = ((colors_lab[:, None, :] - palette_lab[None, :, :]) ** 2).sum(-1)
    return d.argmin(1)


def kmeans(x, k, iters=30, seed=0):
    """Plain k-means (k-means++ init). x: (n, d). Returns (centers, labels)."""
    rng = np.random.default_rng(seed)
    centers = [x[rng.integers(len(x))]]
    for _ in range(1, k):
        d = np.min(((x[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
        if d.sum() == 0:
            break
        centers.append(x[rng.choice(len(x), p=d / d.sum())])
    centers = np.array(centers)
    for _ in range(iters):
        labels = nearest(x, centers)
        new = np.array([x[labels == i].mean(0) if np.any(labels == i) else centers[i]
                        for i in range(len(centers))])
        if np.allclose(new, centers):
            break
        centers = new
    return centers, nearest(x, centers)


def load_filaments(path):
    """Load a filament list.

    Accepts either a list or {"filaments": [...]}; each entry is
    {"name": "Magenta PLA", "hex": "#C2185B"} plus optional "slot" (AMS/tool
    number, 1-based) and "match" (list of extra hex colors that should also
    map to this filament, e.g. shading on the texture).
    """
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data["filaments"]
    out = []
    for i, e in enumerate(data):
        out.append({
            "name": e.get("name", f"color{i + 1}"),
            "hex": rgb_to_hex(hex_to_rgb(e["hex"])),
            "slot": int(e.get("slot", i + 1)),
            "match": [rgb_to_hex(hex_to_rgb(m)) for m in e.get("match", [])],
            "absorb_into": list(e.get("absorb_into", [])),
            "absorb_ratio": float(e.get("absorb_ratio", 0.75)),
        })
    names = {f["name"].lower() for f in out}
    for f in out:
        for n in f["absorb_into"]:
            if n.lower() not in names:
                raise SystemExit(f"{f['name']}: absorb_into {n!r} is not a filament name")
    return out


def load_rules(path):
    """Optional "rules": [{"to": "Black", "from": ["White"],
    "x": [lo, hi], "y": [lo, hi], "z": [lo, hi]}, ...] in model millimetres
    (the grid on the *_map.png picture). Missing axes mean "any"."""
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return []
    rules = []
    for r in data.get("rules", []):
        rules.append({"to": r["to"], "from": r.get("from"),
                      **{ax: r.get(ax) for ax in ("x", "y", "z")}})
    return rules


def palette_targets(filaments):
    """Flatten filaments (+ their extra 'match' colors) into Lab targets.

    Returns (lab array, owner index per row)."""
    rgbs, owner = [], []
    for i, f in enumerate(filaments):
        for h in [f["hex"]] + f["match"]:
            rgbs.append(hex_to_rgb(h))
            owner.append(i)
    return rgb_to_lab(np.array(rgbs, dtype=float)), np.array(owner)
