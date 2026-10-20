"""Map picture: front/back/side views of the parts with a millimetre grid,
for writing box "rules" (coordinates are the model's, as used in the rules)."""
import numpy as np


def _decimate(m, faces):
    if len(m.faces) <= faces:
        return m
    try:
        return m.simplify_quadric_decimation(face_count=faces)
    except Exception:
        idx = np.random.default_rng(0).choice(len(m.faces), faces, replace=False)
        return m.submesh([idx], append=True)


def render_map(parts, png, budget=240000):
    """parts: list of (mesh, hex)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from matplotlib.ticker import MultipleLocator
    from .colors import hex_to_rgb

    total = sum(len(m.faces) for m, _ in parts)
    tris, cols, normals = [], [], []
    for m, hx in parts:
        d = _decimate(m, max(2000, int(budget * len(m.faces) / total)))
        tris.append(d.triangles)
        normals.append(d.face_normals)
        cols.append(np.tile(np.array(hex_to_rgb(hx)) / 255.0, (len(d.faces), 1)))
    T, N, C = np.vstack(tris), np.vstack(normals), np.vstack(cols)
    cen = T.mean(1)

    # (title, forward direction, horizontal axis, flip horizontal)
    views = [("front", np.array([0, 1, 0]), 0, False),
             ("back", np.array([0, -1, 0]), 0, True),
             ("left side", np.array([1, 0, 0]), 1, True),
             ("right side", np.array([-1, 0, 0]), 1, False)]
    lo, hi = T.reshape(-1, 3).min(0), T.reshape(-1, 3).max(0)
    widths = [hi[0] - lo[0], hi[0] - lo[0], hi[1] - lo[1], hi[1] - lo[1]]
    fig, axes = plt.subplots(1, 4, figsize=(4 + sum(widths) / 12, 3 + (hi[2] - lo[2]) / 12),
                             gridspec_kw={"width_ratios": widths})
    for ax, (title, fwd, h, flip) in zip(axes, views):
        order = np.argsort(-(cen @ fwd))  # far first
        shade = 0.3 + 0.7 * np.clip(N @ -fwd, 0, 1)
        poly = T[order][:, :, [h, 2]]
        ax.add_collection(PolyCollection(poly, facecolors=C[order] * shade[order, None],
                                         edgecolors="none"))
        ax.set_xlim(hi[h], lo[h]) if flip else ax.set_xlim(lo[h], hi[h])
        ax.set_ylim(lo[2], hi[2])
        ax.set_aspect("equal")
        ax.xaxis.set_major_locator(MultipleLocator(10))
        ax.yaxis.set_major_locator(MultipleLocator(10))
        ax.grid(True, color="#00A0FF", alpha=0.45, linewidth=0.6)
        ax.set_title(f"{title}   (across = {'xy'[h]} mm, up = z mm)", fontsize=9)
        ax.tick_params(labelsize=7)
    fig.tight_layout()
    fig.savefig(png, dpi=110)
    plt.close(fig)
