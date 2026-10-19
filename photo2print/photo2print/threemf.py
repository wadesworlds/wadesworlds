"""3MF writers that keep every color as its own part with a filament assigned.

* bambu  - Bambu Studio / OrcaSlicer project layout (one object, N parts,
           extruder per part in Metadata/model_settings.config).
* prusa  - PrusaSlicer layout (one object, N volumes, extruder per volume in
           Metadata/Slic3r_PE_model.config).
"""
import uuid
import zipfile
from xml.sax.saxutils import quoteattr

import numpy as np

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
REL_TYPE = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="config" ContentType="text/xml"/>
</Types>
"""

ROOT_RELS = f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="{REL_TYPE}"/>
</Relationships>
"""


def _mesh_xml(mesh, indent="    "):
    v = np.asarray(mesh.vertices)
    f = np.asarray(mesh.faces)
    out = [f"{indent}<mesh>\n{indent} <vertices>\n"]
    out.extend(f'{indent}  <vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>\n'
               for x, y, z in v.tolist())
    out.append(f"{indent} </vertices>\n{indent} <triangles>\n")
    out.extend(f'{indent}  <triangle v1="{a}" v2="{b}" v3="{c}"/>\n'
               for a, b, c in f.tolist())
    out.append(f"{indent} </triangles>\n{indent}</mesh>\n")
    return "".join(out)


def _uid():
    return str(uuid.uuid4())


def write_bambu(path, parts, name="figure", bed_center=(128.0, 128.0)):
    """parts: list of dicts {name, mesh, slot (1-based extruder), hex}."""
    obj_id = len(parts) + 1
    sub = [f'<?xml version="1.0" encoding="UTF-8"?>\n'
           f'<model unit="millimeter" xml:lang="en-US" xmlns="{CORE_NS}" '
           f'xmlns:p="{PROD_NS}" requiredextensions="p">\n'
           f' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n']
    for i, p in enumerate(parts, start=1):
        sub.append(f'  <object id="{i}" p:UUID="{_uid()}" type="model">\n')
        sub.append(_mesh_xml(p["mesh"]))
        sub.append("  </object>\n")
    sub.append(" </resources>\n <build/>\n</model>\n")

    comps = "".join(
        f'    <component p:path="/3D/Objects/object_1.model" objectid="{i}" '
        f'p:UUID="{_uid()}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n'
        for i in range(1, len(parts) + 1))
    bx, by = bed_center
    main = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<model unit="millimeter" xml:lang="en-US" xmlns="{CORE_NS}" '
            f'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
            f'xmlns:p="{PROD_NS}" requiredextensions="p">\n'
            f' <metadata name="Application">BambuStudio-01.10.00.00</metadata>\n'
            f' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
            f' <metadata name="Title">{name}</metadata>\n'
            f' <resources>\n'
            f'  <object id="{obj_id}" p:UUID="{_uid()}" type="model">\n'
            f'   <components>\n{comps}   </components>\n'
            f'  </object>\n'
            f' </resources>\n'
            f' <build p:UUID="{_uid()}">\n'
            f'  <item objectid="{obj_id}" p:UUID="{_uid()}" '
            f'transform="1 0 0 0 1 0 0 0 1 {bx} {by} 0" printable="1"/>\n'
            f' </build>\n</model>\n')

    model_rels = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
                  f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                  f' <Relationship Target="/3D/Objects/object_1.model" Id="rel-1" Type="{REL_TYPE}"/>\n'
                  f'</Relationships>\n')

    cfg = ['<?xml version="1.0" encoding="UTF-8"?>\n<config>\n',
           f'  <object id="{obj_id}">\n',
           f'    <metadata key="name" value={quoteattr(name)}/>\n',
           f'    <metadata key="extruder" value="{parts[0]["slot"]}"/>\n']
    for i, p in enumerate(parts, start=1):
        cfg.append(f'    <part id="{i}" subtype="normal_part">\n'
                   f'      <metadata key="name" value={quoteattr(p["name"])}/>\n'
                   f'      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
                   f'      <metadata key="extruder" value="{p["slot"]}"/>\n'
                   f'    </part>\n')
    cfg.append('  </object>\n  <plate>\n'
               '    <metadata key="plater_id" value="1"/>\n'
               '    <metadata key="locked" value="false"/>\n'
               '    <model_instance>\n'
               f'      <metadata key="object_id" value="{obj_id}"/>\n'
               '      <metadata key="instance_id" value="0"/>\n'
               '      <metadata key="identify_id" value="1"/>\n'
               '    </model_instance>\n  </plate>\n</config>\n')

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("3D/3dmodel.model", main)
        z.writestr("3D/_rels/3dmodel.model.rels", model_rels)
        z.writestr("3D/Objects/object_1.model", "".join(sub))
        z.writestr("Metadata/model_settings.config", "".join(cfg))


def write_prusa(path, parts, name="figure", bed_center=(125.0, 105.0)):
    verts, tris, ranges, offset, first = [], [], [], 0, 0
    for p in parts:
        m = p["mesh"]
        verts.append(np.asarray(m.vertices))
        tris.append(np.asarray(m.faces) + offset)
        offset += len(m.vertices)
        ranges.append((first, first + len(m.faces) - 1))
        first += len(m.faces)

    class _M:  # minimal mesh-like holder for _mesh_xml
        vertices = np.vstack(verts)
        faces = np.vstack(tris)

    bx, by = bed_center
    model = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
             f'<model unit="millimeter" xml:lang="en-US" xmlns="{CORE_NS}" '
             f'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06">\n'
             f' <metadata name="slic3rpe:Version3mf">1</metadata>\n'
             f' <metadata name="Title">{name}</metadata>\n'
             f' <resources>\n  <object id="1" type="model">\n'
             + _mesh_xml(_M) +
             f'  </object>\n </resources>\n <build>\n'
             f'  <item objectid="1" transform="1 0 0 0 1 0 0 0 1 {bx} {by} 0" printable="1"/>\n'
             f' </build>\n</model>\n')

    cfg = ['<?xml version="1.0" encoding="UTF-8"?>\n<config>\n',
           ' <object id="1" instances_count="1">\n',
           f'  <metadata type="object" key="name" value={quoteattr(name)}/>\n']
    for p, (a, b) in zip(parts, ranges):
        cfg.append(f'  <volume firstid="{a}" lastid="{b}">\n'
                   f'   <metadata type="volume" key="name" value={quoteattr(p["name"])}/>\n'
                   f'   <metadata type="volume" key="volume_type" value="ModelPart"/>\n'
                   f'   <metadata type="volume" key="extruder" value="{p["slot"]}"/>\n'
                   f'  </volume>\n')
    cfg.append(" </object>\n</config>\n")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/Slic3r_PE_model.config", "".join(cfg))
