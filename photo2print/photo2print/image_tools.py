"""Step 1-2 helpers for the 2D picture: solid background and palette preview."""
import json

import numpy as np
from PIL import Image
from scipy import ndimage

from .colors import kmeans, rgb_to_hex, rgb_to_lab


def _background_field(lab, band=0.03):
    """Fit a smooth (quadratic) background to the image border, so gradients
    and vignetting in an AI-generated backdrop are handled."""
    h, w = lab.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    y, x = yy / h - 0.5, xx / w - 0.5
    basis = np.stack([np.ones_like(x), x, y, x * x, y * y, x * y], -1)
    b = max(2, int(band * min(h, w)))
    edge = np.zeros((h, w), bool)
    edge[:b] = edge[-b:] = True
    edge[:, :b] = edge[:, -b:] = True
    coef, *_ = np.linalg.lstsq(basis[edge], lab[edge], rcond=None)
    return basis @ coef


def foreground_mask(rgb, tolerance=10.0):
    """Mask of pixels that are not the (near solid) background.

    The background is modelled from the image border; everything connected to
    the border within `tolerance` (Lab distance) counts as background.
    """
    lab = rgb_to_lab(rgb)
    close = np.linalg.norm(lab - _background_field(lab), axis=-1) < tolerance
    lbl, _ = ndimage.label(close)
    edge_ids = np.unique(np.concatenate([lbl[0], lbl[-1], lbl[:, 0], lbl[:, -1]]))
    # also treat big enclosed patches (e.g. the gap between the legs) as background
    sizes = np.bincount(lbl.ravel())
    big = np.flatnonzero(sizes > 0.002 * lbl.size)
    ids = np.union1d(edge_ids, big)
    bg_mask = np.isin(lbl, ids[ids > 0])
    return ndimage.binary_opening(~bg_mask, iterations=2)


def flatten_background(src, dst, color="#FFFFFF", tolerance=10.0):
    """Replace a (near) solid background with a flat color, or transparency."""
    img = np.array(Image.open(src).convert("RGB"))
    fg = foreground_mask(img, tolerance)
    if color.lower() == "transparent":
        out = np.dstack([img, (fg * 255).astype(np.uint8)])
        Image.fromarray(out, "RGBA").save(dst)
    else:
        from .colors import hex_to_rgb
        out = img.copy()
        out[~fg] = hex_to_rgb(color)
        Image.fromarray(out).save(dst)
    return fg.mean()


def suggest_palette(src, k=8, json_out=None, preview_out=None, tolerance=10.0):
    """Cluster the subject's colors into k groups to help pick filaments."""
    img = np.array(Image.open(src).convert("RGB"))
    fg = foreground_mask(img, tolerance)
    px = img[fg].astype(float)
    if len(px) > 60000:
        px = px[np.random.default_rng(0).choice(len(px), 60000, replace=False)]
    centers_lab, labels = kmeans(rgb_to_lab(px), k)
    share = np.bincount(labels, minlength=len(centers_lab)) / len(labels)
    order = np.argsort(-share)
    entries = []
    for rank, i in enumerate(order):
        mean_rgb = px[labels == i].mean(0)
        entries.append({"name": f"color{rank + 1}", "hex": rgb_to_hex(mean_rgb),
                        "slot": rank + 1, "share": round(float(share[i]), 4)})
    if json_out:
        with open(json_out, "w") as f:
            json.dump({"filaments": entries}, f, indent=2)
    if preview_out:
        _write_preview(img, fg, entries, preview_out)
    return entries


def _write_preview(img, fg, entries, path):
    from .colors import hex_to_rgb, nearest
    pal = np.array([hex_to_rgb(e["hex"]) for e in entries], dtype=float)
    idx = nearest(rgb_to_lab(img[fg].astype(float)), rgb_to_lab(pal))
    out = np.full_like(img, 255)
    out[fg] = pal[idx].astype(np.uint8)
    Image.fromarray(np.hstack([img, out])).save(path)
