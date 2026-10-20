"""Step 3b-4: split a textured mesh into one watertight solid per filament.

Pipeline
--------
1. Load the textured model (GLB/OBJ/PLY from Meshy), orient Z-up, scale.
2. Sample the texture at every face and snap it to the nearest filament.
3. Majority-smooth face labels so speckles do not become tiny parts.
4. Voxelize: surface voxels take the label of the surface they touch, the
   inside is filled and every interior voxel takes the label of its nearest
   surface voxel (or a single "core" filament below a chosen shell depth).
5. Clean the label grid: majority filter, then merge islands smaller than
   --min-island into their neighbours.
6. Build the parts:
   * "original" surface (default when the model is a closed mesh): each color
     region is cut out of the ORIGINAL model with exact booleans, so the
     outside keeps all of Meshy's detail and only the hidden color borders
     come from the voxels.
   * "voxel" surface (fallback for open/broken meshes): marching cubes per
     label. Smoother but loses detail finer than about 2x --pitch.
   Either way the parts are closed, watertight, do not overlap and together
   rebuild the figure.
"""
import numpy as np
import trimesh
from scipy import ndimage
from skimage import measure

from .colors import nearest, palette_targets, rgb_to_lab, kmeans, rgb_to_hex


# ---------------------------------------------------------------- loading
def _texture_image(material):
    for attr in ("baseColorTexture", "image"):
        img = getattr(material, attr, None)
        if img is not None:
            return img
    return None


def _face_colors(geom):
    """RGB (0-255) per face, sampled at face centroids where possible."""
    vis = geom.visual
    n = len(geom.faces)
    if isinstance(vis, trimesh.visual.TextureVisuals) and vis.uv is not None:
        img = _texture_image(vis.material)
        if img is not None:
            uv = vis.uv[geom.faces].mean(axis=1)
            rgba = trimesh.visual.color.uv_to_color(uv, img)
            factor = getattr(vis.material, "baseColorFactor", None)
            rgb = rgba[:, :3].astype(float)
            if factor is not None:
                rgb *= np.asarray(factor[:3], dtype=float) / 255.0
            return rgb
        try:
            vis = vis.to_color()
        except Exception:
            vis = None
    if vis is not None and vis.kind == "face":
        return vis.face_colors[:, :3].astype(float)
    if vis is not None and vis.kind == "vertex":
        return vis.vertex_colors[geom.faces][:, :, :3].mean(1).astype(float)
    print("  warning: a mesh piece has no color/texture; treating it as grey")
    return np.full((n, 3), 128.0)


def load_colored_mesh(path, up="y", height_mm=120.0):
    scene = trimesh.load(path, force="scene", process=False)
    meshes, colors = [], []
    for node in scene.graph.nodes_geometry:
        transform, name = scene.graph[node]
        geom = scene.geometry[name]
        if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
            continue
        colors.append(_face_colors(geom))
        g = trimesh.Trimesh(geom.vertices.copy(), geom.faces.copy(), process=False)
        g.apply_transform(transform)
        meshes.append(g)
    if not meshes:
        raise SystemExit(f"No triangle meshes found in {path}")
    mesh = trimesh.util.concatenate(meshes)
    face_rgb = np.concatenate(colors)

    if up == "y":  # glTF convention -> printer convention
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    scale = height_mm / mesh.extents[2]
    mesh.apply_scale(scale)
    lo, hi = mesh.bounds
    mesh.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
    # merge seam vertices so face adjacency works (face order is preserved)
    mesh.merge_vertices(merge_tex=True, merge_norm=True)
    return mesh, face_rgb


# ---------------------------------------------------------------- labels
def assign_labels(face_rgb, filaments):
    targets, owner = palette_targets(filaments)
    return owner[nearest(rgb_to_lab(face_rgb), targets)]


def _index(filaments, name):
    for i, f in enumerate(filaments):
        if f["name"].lower() == name.lower():
            return i
    raise SystemExit(f"rule: {name!r} is not a filament name")


def apply_box_rules(mesh, labels, filaments, rules):
    """Recolor faces inside a box: e.g. hair that shares a color with pants."""
    c = mesh.triangles_center
    for r in rules:
        inside = np.ones(len(labels), bool)
        for axis, col in (("x", 0), ("y", 1), ("z", 2)):
            if r.get(axis):
                lo, hi = sorted(r[axis])
                inside &= (c[:, col] >= lo) & (c[:, col] <= hi)
        if r.get("from"):
            src = [_index(filaments, n) for n in r["from"]]
            inside &= np.isin(labels, src)
        labels = np.where(inside, _index(filaments, r["to"]), labels)
        print(f"  rule -> {r['to']}: {int(inside.sum())} faces")
    return labels


def auto_filaments(face_rgb, areas, k):
    """No filament file: cluster the texture into k colors."""
    lab = rgb_to_lab(face_rgb)
    rng = np.random.default_rng(0)
    pick = rng.choice(len(lab), min(len(lab), 80000), replace=False,
                      p=areas / areas.sum())
    centers, labels = kmeans(lab[pick], k)
    share = np.bincount(labels, minlength=len(centers))
    out = []
    for rank, i in enumerate(np.argsort(-share)):
        out.append({"name": f"color{rank + 1}", "slot": rank + 1, "match": [],
                    "hex": rgb_to_hex(face_rgb[pick][labels == i].mean(0))})
    return out


def smooth_face_labels(mesh, labels, n_labels, iterations=3):
    """Majority vote over edge-adjacent faces (area weighted)."""
    if iterations <= 0:
        return labels
    adj = mesh.face_adjacency
    area = mesh.area_faces
    for _ in range(iterations):
        votes = np.zeros((len(labels), n_labels))
        np.add.at(votes, (np.arange(len(labels)), labels), area * 1.5)
        np.add.at(votes, (adj[:, 0], labels[adj[:, 1]]), area[adj[:, 1]])
        np.add.at(votes, (adj[:, 1], labels[adj[:, 0]]), area[adj[:, 0]])
        labels = votes.argmax(1)
    return labels


def texture_report(path, filaments, k=16, up="y", png=None):
    """List the colors actually painted on the model (area weighted) and the
    filament each one goes to, so 'match' lists can be tuned."""
    from PIL import Image, ImageDraw
    from .colors import hex_to_rgb
    mesh, face_rgb = load_colored_mesh(path, up=up)
    area = mesh.area_faces
    lab = rgb_to_lab(face_rgb)
    rng = np.random.default_rng(0)
    pick = rng.choice(len(lab), min(len(lab), 120000), replace=True, p=area / area.sum())
    centers, lbl = kmeans(lab[pick], k)
    share = np.bincount(lbl, minlength=len(centers)) / len(lbl)
    rows = []
    for i in np.argsort(-share):
        rgb = face_rgb[pick][lbl == i].mean(0)
        target = filaments[assign_labels(rgb[None], filaments)[0]] if filaments else None
        rows.append((rgb_to_hex(rgb), float(share[i]), target))
    if png:
        h = 34
        img = Image.new("RGB", (560, h * len(rows) + 10), "white")
        d = ImageDraw.Draw(img)
        for r, (hx, sh, t) in enumerate(rows):
            y = 5 + r * h
            d.rectangle([5, y, 85, y + h - 6], fill=hex_to_rgb(hx))
            d.text((95, y + 8), f"{hx}   {sh:6.1%}", fill="black")
            if t:
                d.text((260, y + 8), "->", fill="black")
                d.rectangle([290, y, 350, y + h - 6], fill=hex_to_rgb(t["hex"]))
                d.text((360, y + 8), f"slot {t['slot']}  {t['name']}", fill="black")
        img.save(png)
    return rows


# ---------------------------------------------------------------- voxels
def _rasterize(mesh, lo, pitch, shape, chunk=4_000_000):
    """Voxel index of points on a barycentric grid over each triangle, dense
    enough (spacing <= pitch/2) that the voxel shell has no gaps."""
    tri = mesh.triangles
    edge = np.linalg.norm(tri - np.roll(tri, 1, axis=1), axis=2).max(1)
    steps = np.maximum(1, np.ceil(edge / (pitch * 0.5))).astype(int)
    lins, fids = [], []
    for n in np.unique(steps):
        faces = np.flatnonzero(steps == n)
        i, j = np.mgrid[0:n + 1, 0:n + 1]
        keep = i + j <= n
        w = np.stack([i[keep], j[keep]], 1) / n  # barycentric (u, v)
        per = max(1, chunk // len(w))
        for s in range(0, len(faces), per):
            f = faces[s:s + per]
            t = tri[f]
            pts = (t[:, None, 0] + w[None, :, :1] * (t[:, None, 1] - t[:, None, 0])
                   + w[None, :, 1:] * (t[:, None, 2] - t[:, None, 0]))
            ijk = np.floor((pts.reshape(-1, 3) - lo) / pitch).astype(np.int64)
            ijk = np.clip(ijk, 0, np.array(shape) - 1)
            lin = np.ravel_multi_index(ijk.T, shape)
            fid = np.repeat(f, len(w))
            u = np.unique(lin * len(mesh.faces) + fid)  # drop duplicate hits
            lins.append(u // len(mesh.faces))
            fids.append(u % len(mesh.faces))
    return np.concatenate(lins), np.concatenate(fids)


def voxel_labels(mesh, face_labels, pitch, pad=3, close_iters=1):
    """Return (grid of labels 0=empty / 1..n, origin). Labels are shifted +1."""
    lo = mesh.bounds[0] - pad * pitch
    shape = np.ceil((mesh.bounds[1] - lo) / pitch).astype(int) + pad + 1
    print(f"  voxel grid {shape[0]}x{shape[1]}x{shape[2]} @ {pitch} mm "
          f"({np.prod(shape) / 1e6:.1f} M voxels)")

    # rasterize every triangle into voxels; each hit carries the face label
    lin, fidx = _rasterize(mesh, lo, pitch, shape)
    lab = face_labels[fidx].astype(np.int64) + 1

    # majority label per surface voxel
    key = lin * 256 + lab
    uk, cnt = np.unique(key, return_counts=True)
    vox, vlab = uk // 256, uk % 256
    order = np.lexsort((-cnt, vox))
    vox, vlab = vox[order], vlab[order]
    first = np.r_[True, vox[1:] != vox[:-1]]
    surf = np.zeros(int(np.prod(shape)), np.uint8)
    surf[vox[first]] = vlab[first]
    surf = surf.reshape(shape)

    # solid = surface shell + enclosed inside
    shell = surf > 0
    if close_iters:
        shell = ndimage.binary_closing(shell, iterations=close_iters)
    solid = ndimage.binary_fill_holes(shell)
    filled = solid.sum() / max(shell.sum(), 1)
    if filled < 1.2:
        print("  warning: the mesh shell seems open, the inside barely filled. "
              "Try a larger --pitch or --close 2.")

    # every solid voxel inherits the nearest surface label
    idx = ndimage.distance_transform_edt(surf == 0, return_distances=False, return_indices=True)
    grid = surf[tuple(idx)]
    grid[~solid] = 0
    return grid, lo


def apply_core(grid, pitch, shell_mm, core_label):
    """Voxels deeper than shell_mm below the outside become core_label."""
    depth = ndimage.distance_transform_edt(grid > 0) * pitch
    grid[(depth > shell_mm) & (grid > 0)] = core_label
    return grid


def remove_islands(grid, min_voxels, n_labels):
    """Merge tiny disconnected bits of a color into their neighbours."""
    if min_voxels <= 1:
        return grid
    solid = grid > 0
    holes = np.zeros_like(solid)
    struct = ndimage.generate_binary_structure(3, 3)
    for k in range(1, n_labels + 1):
        comp, n = ndimage.label(grid == k, structure=struct)
        if n == 0:
            continue
        sizes = np.bincount(comp.ravel())
        small = np.flatnonzero(sizes < min_voxels)
        small = small[small > 0]
        if len(small):
            holes |= np.isin(comp, small)
    if holes.any():
        keep = np.where(holes, 0, grid)
        if keep.max() == 0:
            return grid
        idx = ndimage.distance_transform_edt(keep == 0, return_distances=False, return_indices=True)
        grid = np.where(solid, keep[tuple(idx)], 0).astype(grid.dtype)
    return grid


def majority_filter(grid, n_labels, iterations=1):
    """3x3x3 majority vote inside the solid; cleans ragged color borders."""
    solid = grid > 0
    for _ in range(iterations):
        best = np.zeros(grid.shape, np.float32)
        out = grid.copy()
        for k in range(1, n_labels + 1):
            score = ndimage.uniform_filter((grid == k).astype(np.float32), 3)
            better = score > best
            out[better] = k
            best[better] = score[better]
        grid = np.where(solid, out, 0).astype(grid.dtype)
    return grid


def absorb_regions(grid, filaments):
    """A patch of color A that is mostly surrounded by color B (listed in A's
    "absorb_into") takes color B: e.g. black straps or shadows painted on a
    shirt, while a black cane or base touching other colors stays black."""
    struct = ndimage.generate_binary_structure(3, 3)
    for i, f in enumerate(filaments):
        targets = [_index(filaments, n) + 1 for n in f.get("absorb_into", [])]
        if not targets:
            continue
        a = i + 1
        comp, n = ndimage.label(grid == a, structure=struct)
        moved = 0
        for j, sl in enumerate(ndimage.find_objects(comp), start=1):
            if sl is None:
                continue
            sl = tuple(slice(max(s.start - 1, 0), s.stop + 1) for s in sl)
            blob = comp[sl] == j
            ring = ndimage.binary_dilation(blob, struct) & ~blob
            nb = grid[sl][ring]
            nb = nb[(nb > 0) & (nb != a)]
            if len(nb) == 0:
                continue
            cnt = np.bincount(nb, minlength=len(filaments) + 1)
            best = int(cnt.argmax())
            if best in targets and cnt[best] >= f.get("absorb_ratio", 0.75) * len(nb):
                grid[sl][blob] = best
                moved += 1
        if moved:
            print(f"  {f['name']}: {moved} patch(es) absorbed into surrounding color")
    return grid


def extend_labels(grid, grow_voxels=3):
    """Copy the nearest label a few voxels outward past the solid, so color
    regions fully cover the original surface."""
    solid = grid > 0
    idx = ndimage.distance_transform_edt(~solid, return_distances=False, return_indices=True)
    full = grid[tuple(idx)]
    del idx
    near = ndimage.binary_dilation(solid, iterations=grow_voxels)
    return np.where(near, full, 0).astype(grid.dtype)


# ---------------------------------------------------------------- booleans
def to_manifold(m):
    import manifold3d as mf
    mesh = mf.Mesh(vert_properties=np.asarray(m.vertices, np.float32),
                   tri_verts=np.asarray(m.faces, np.uint32))
    return mf.Manifold(mesh)


def from_manifold(man):
    out = man.to_mesh()
    v = np.asarray(out.vert_properties)[:, :3]
    return trimesh.Trimesh(v, np.asarray(out.tri_verts), process=True)


def original_solid(mesh):
    """The loaded model as one exact boolean solid, or None if it can't be
    made closed. Separate or overlapping shells (common in AI models) are
    fused; small open scraps are dropped."""
    try:
        import manifold3d as mf
    except ImportError:
        print("  (manifold3d not installed: using voxel surface)")
        return None
    comps = mesh.split(only_watertight=False)
    big = max(len(c.faces) for c in comps)
    solids = []
    for c in comps:
        if not c.is_watertight:
            trimesh.repair.fill_holes(c)
        if not c.is_watertight:
            if len(c.faces) < 0.01 * big:
                continue  # floating scrap
            return None
        trimesh.repair.fix_normals(c)
        man = to_manifold(c)
        if man.status() != mf.Error.NoError:
            return None
        if not man.is_empty():
            solids.append(man)
    if not solids:
        return None
    if len(solids) > 1:
        print(f"  fusing {len(solids)} shells into one solid")
        return mf.Manifold.batch_boolean(solids, mf.OpType.Add)
    return solids[0]


def region_fields(full, n_labels, sigma):
    """Smooth, mutually consistent color regions.

    f_k is the blurred indicator of label k (label 0 = outside). Region k is
    where f_k beats every other label, so g_k = f_k - max(other f) >= 0.
    Where two colors meet, g_a = -g_b, so marching cubes puts both sides of
    the border on exactly the same vertices: no gaps or slivers."""
    def field(k):
        f = (full == k).astype(np.float32)
        return ndimage.gaussian_filter(f, sigma) if sigma > 0 else f

    labels = range(0, n_labels + 1)
    best = np.full(full.shape, -1.0, np.float32)
    second = np.full(full.shape, -1.0, np.float32)
    best_k = np.zeros(full.shape, np.uint8)
    for k in labels:
        f = field(k)
        top = f > best
        second = np.where(top, best, np.maximum(second, f))
        best_k[top] = k
        best = np.where(top, f, best)
    for k in labels:
        if k == 0 or not (full == k).any():
            continue
        f = field(k)
        yield k, np.where(best_k == k, f - second, f - best)


def field_mesh(g, lo, pitch, pad=2):
    if g.max() <= 0:
        return None
    nz = np.argwhere(g > 0)
    a = np.maximum(nz.min(0) - pad, 0)
    b = np.minimum(nz.max(0) + pad + 1, g.shape)
    sub = np.pad(g[a[0]:b[0], a[1]:b[1], a[2]:b[2]], pad, constant_values=-1.0)
    verts, faces, _, _ = measure.marching_cubes(sub, 0.0)
    verts = (verts + a - pad) * pitch + lo
    m = trimesh.Trimesh(verts, faces, process=True)
    if m.volume < 0:
        m.invert()
    return m


def drop_crumbs(m, min_mm3):
    """Remove tiny disconnected bits (sub-voxel crumbs at color borders)."""
    pieces = m.split(only_watertight=False)
    if len(pieces) <= 1:
        return m
    keep = [p for p in pieces if abs(p.volume) >= min_mm3]
    if not keep:
        keep = [max(pieces, key=lambda p: abs(p.volume))]
    return trimesh.util.concatenate(keep)


def boolean_parts(original, grid, lo, pitch, n_labels, sigma, min_island_mm3):
    """Cut each color region out of the original solid, so the outside keeps
    the original surface and only the hidden borders come from voxels."""
    full = extend_labels(grid)
    del grid
    out = {}
    for k, g in region_fields(full, n_labels, max(sigma, 0.8)):
        region = field_mesh(g, lo, pitch)
        if region is None:
            continue
        print(f"  cutting color {k} ...", flush=True)
        part = original ^ to_manifold(region)
        if part.is_empty():
            continue
        m = drop_crumbs(from_manifold(part), min_island_mm3 * 0.1)
        if m.volume < 0:
            m.invert()
        out[k - 1] = m
    return out


# ---------------------------------------------------------------- meshing
def label_mesh(grid, label, lo, pitch, sigma=0.7, pad=2):
    mask = grid == label
    if not mask.any():
        return None
    nz = np.argwhere(mask)
    a = np.maximum(nz.min(0) - pad, 0)
    b = np.minimum(nz.max(0) + pad + 1, grid.shape)
    sub = np.pad(mask[a[0]:b[0], a[1]:b[1], a[2]:b[2]].astype(np.float32), pad)
    if sigma > 0:
        sub = ndimage.gaussian_filter(sub, sigma)
    if sub.max() <= 0.5:
        return None
    verts, faces, _, _ = measure.marching_cubes(sub, 0.5)
    verts = (verts + a - pad) * pitch + lo
    m = trimesh.Trimesh(verts, faces, process=True)
    if m.volume < 0:
        m.invert()
    return m


def decimate(m, target_faces):
    if target_faces <= 0 or len(m.faces) <= target_faces:
        return m
    try:
        d = m.simplify_quadric_decimation(face_count=target_faces)
    except Exception as e:  # fast_simplification not installed
        print(f"  (decimation skipped: {e})")
        return m
    d = trimesh.Trimesh(d.vertices, d.faces, process=True)
    if d.is_watertight and abs(d.volume) > 0.9 * abs(m.volume):
        if d.volume < 0:
            d.invert()
        return d
    return m


# ---------------------------------------------------------------- driver
def split_model(path, filaments=None, n_auto=6, height_mm=120.0, up="y",
                pitch=None, smooth=3, min_island_mm3=3.0, sigma=0.7,
                core=None, shell_mm=2.0, close_iters=1, max_faces=400000,
                surface="auto", clean=2, rules=None):
    """Returns (parts, filaments): parts = [(filament_index, trimesh), ...]."""
    print(f"Loading {path}")
    mesh, face_rgb = load_colored_mesh(path, up=up, height_mm=height_mm)
    ext = mesh.extents
    print(f"  {len(mesh.faces)} faces, size {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm")

    if not filaments:
        filaments = auto_filaments(face_rgb, mesh.area_faces, n_auto)
        print("  auto palette: " + ", ".join(f["hex"] for f in filaments))
    n = len(filaments)
    labels = assign_labels(face_rgb, filaments)
    labels = smooth_face_labels(mesh, labels, n, smooth)
    if rules:
        labels = apply_box_rules(mesh, labels, filaments, rules)

    original = None
    if surface in ("auto", "original"):
        original = original_solid(mesh)
        if original is None:
            msg = "  the model is not a closed mesh, so its surface can't be kept exactly"
            if surface == "original":
                raise SystemExit(msg + ". Use --surface voxel.")
            print(msg + "; using the voxel surface instead (lower detail).")
        else:
            print("  closed mesh: keeping the original Meshy surface")

    if pitch is None:  # surface detail no longer depends on pitch when kept
        pitch = 0.4 if original is not None else 0.3
    print("Voxelizing")
    grid, lo = voxel_labels(mesh, labels, pitch, close_iters=close_iters)
    if core is not None:
        grid = apply_core(grid, pitch, shell_mm, core + 1)
    grid = majority_filter(grid, n, clean)
    min_vox = int(np.ceil(min_island_mm3 / pitch ** 3))
    grid = remove_islands(grid, min_vox, n)
    grid = absorb_regions(grid, filaments)

    print("Building parts")
    meshes = None
    if original is not None:
        meshes = boolean_parts(original, grid, lo, pitch, n, sigma, min_island_mm3)
        if not all(m.is_watertight for m in meshes.values()):
            print("  some parts came out open; falling back to the voxel surface")
            meshes = None
    if meshes is None:
        meshes = {}
        for i in range(n):
            m = label_mesh(grid, i + 1, lo, pitch, sigma=sigma)
            if m is not None:
                meshes[i] = decimate(m, max_faces)

    parts = []
    for i, f in enumerate(filaments):
        m = meshes.get(i)
        if m is None:
            print(f"  {f['name']:<20} (not used)")
            continue
        print(f"  {f['name']:<20} {f['hex']}  slot {f['slot']}  "
              f"{len(m.faces):>8} faces  {m.volume / 1000:7.2f} cm3  "
              f"watertight={m.is_watertight}")
        parts.append((i, m))
    return parts, filaments
