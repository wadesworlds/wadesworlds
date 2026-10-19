"""Step 3b-4: split a textured mesh into one watertight solid per filament.

Pipeline
--------
1. Load the textured model (GLB/OBJ/PLY from Meshy), orient Z-up, scale.
2. Sample the texture at every face and snap it to the nearest filament.
3. Majority-smooth face labels so speckles do not become tiny parts.
4. Voxelize: surface voxels take the label of the surface they touch, the
   inside is filled and every interior voxel takes the label of its nearest
   surface voxel (or a single "core" filament below a chosen shell depth).
5. Drop islands smaller than --min-island and refill from their neighbours.
6. Marching cubes per label -> closed, watertight, non-overlapping solids
   that share their boundaries exactly, so together they rebuild the figure.
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
    _, idx = ndimage.distance_transform_edt(surf == 0, return_indices=True)
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
        _, idx = ndimage.distance_transform_edt(keep == 0, return_indices=True)
        grid = np.where(solid, keep[tuple(idx)], 0).astype(grid.dtype)
    return grid


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
                pitch=0.3, smooth=3, min_island_mm3=1.0, sigma=0.7,
                core=None, shell_mm=2.0, close_iters=1, max_faces=400000):
    """Returns (parts, filaments): parts = [(filament_index, trimesh), ...]."""
    print(f"Loading {path}")
    mesh, face_rgb = load_colored_mesh(path, up=up, height_mm=height_mm)
    ext = mesh.extents
    print(f"  {len(mesh.faces)} faces, size {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm")

    if not filaments:
        filaments = auto_filaments(face_rgb, mesh.area_faces, n_auto)
        print("  auto palette: " + ", ".join(f["hex"] for f in filaments))
    labels = assign_labels(face_rgb, filaments)
    labels = smooth_face_labels(mesh, labels, len(filaments), smooth)

    print("Voxelizing")
    grid, lo = voxel_labels(mesh, labels, pitch, close_iters=close_iters)
    if core is not None:
        grid = apply_core(grid, pitch, shell_mm, core + 1)
    min_vox = int(np.ceil(min_island_mm3 / pitch ** 3))
    grid = remove_islands(grid, min_vox, len(filaments))

    print("Meshing parts")
    parts = []
    for i, f in enumerate(filaments):
        m = label_mesh(grid, i + 1, lo, pitch, sigma=sigma)
        if m is None:
            print(f"  {f['name']:<20} (not used)")
            continue
        m = decimate(m, max_faces)
        print(f"  {f['name']:<20} {f['hex']}  slot {f['slot']}  "
              f"{len(m.faces):>8} faces  {m.volume / 1000:7.2f} cm3  "
              f"watertight={m.is_watertight}")
        parts.append((i, m))
    return parts, filaments
