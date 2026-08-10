"""Convert plain Khronos Blender glTF exports into MSFS-native glTF.

MSFS 2020 (SU9+) and MSFS 2024 load glTF models, but the engine's loader keys
on the ASOBO extensions that Asobo's own exporters (3ds Max / the official
Blender plugin) write.  Models exported with the stock Khronos exporter lack
them, so the SimObject mounts and spawns but the model silently fails to load
-- nothing renders.

This module replicates the exact extension structure verified against the
proven-working models on this machine (the FNX 3ds-Max exports and the OPS
ROOM native API bridge):

    asset.extensions.ASOBO_asset_optimized
        {BoundingBoxMax, BoundingBoxMin, MajorVersion, MinorVersion,
         UseCheckerboardMaterialForMissingTextures, UseOnlyFilenameForImageURI}
    asset.extensions.ASOBO_normal_map_convention
        {"tangent_space_convention": "DirectX"}
    node.extensions.ASOBO_unique_id        {"id": <node name>}  (every node)
    material.extensions.ASOBO_material_emissive   {}  (materials with emissiveFactor)

Renderer-critical requirements that the stock exporter omits, proven by a
corpus scan of every working SimObject glTF on this machine (60 packages /
5592 meshes / 3607 glTFs):

    1. TANGENT vertex attribute on every mesh primitive.  5591/5592 working
       meshes carry TANGENT; the only mesh without it is our own bridge,
       which is invisible by design (alpha-0).

    2. Textures must be DDS/KTX2 referenced through the MSFT_texture_dds
       extension.  The corpus has 26,120 DDS + 7,299 KTX2 image references
       and only 24 PNG -- and every one of those 24 PNGs belongs to our own
       package (plus one FNX cockpit detail texture).  MSFS 2024's native
       renderer ignores PNG textures, so flat-colour materials rendered
       nothing at all.  This module therefore writes a DXT1/BC1 DDS texture
       (the most common fourcc in the corpus: 2694 files) per material and
       wires ``texture.extensions.MSFT_texture_dds`` + declares it in
       ``extensionsRequired`` exactly like the FNX cone.

    3. Vertex attributes must be QUANTIZED to the exact component types the
       2024 geometry compiler accepts.  Every one of the 49,546 working
       meshes ships NORMAL/TANGENT as signed byte VEC4 (values /127,
       tangent w = +/-1 handedness) and TEXCOORD_0/1 as signed short VEC2
       (/32767); POSITION alone stays float32.  ZERO working meshes use
       float NORMAL/TEXCOORD.  Float attributes are rejected by the
       geometry compiler: the glTF JSON loads (bitmap/node/draw counts all
       populate) but the geometry decodes to 0 static verts / 0 static
       faces -- the exact debug-panel signature we were chasing.  Tiled UVs
       (e.g. the barricade's 6-tile stripe) are fract-wrapped into [0,1),
       which is sampling-identical under the REPEAT sampler.

Solid-colour materials get a 4x4 white DDS (white x baseColorFactor = same
rendered colour).  Materials that already reference a PNG base-color texture
(the barricade stripe textures) have that PNG converted in place to DXT1 DDS.

The global bounding box is computed from the POSITION accessors of every mesh
(Blender always writes accessor min/max; the buffer is parsed as a fallback).

Pure stdlib -- runs both inside Blender's Python right after export and in the
package builder, so the produced files are identical either way.  The same
native files work for MSFS 2020 and MSFS 2024.

Usage:
    python msfs_native.py PATH_TO_MODEL_GLTF [MORE_GLTFS...]
"""

from __future__ import annotations

import base64
import json
import math
import struct
import sys
import zlib
from pathlib import Path

ASSET_EXTENSION = "ASOBO_asset_optimized"
NORMAL_CONVENTION = "ASOBO_normal_map_convention"
UNIQUE_ID = "ASOBO_unique_id"
MATERIAL_EMISSIVE = "ASOBO_material_emissive"
MSFT_TEXTURE_DDS = "MSFT_texture_dds"

#: Version markers used by Asobo's exporters (mirrors the FNX 3ds Max output).
MAJOR_VERSION = 4
MINOR_VERSION = 6

# glTF component types used by the TANGENT computation.
_COMPONENT_SIZES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
_COMPONENT_FMT = {5120: "<b", 5121: "<B", 5122: "<h", 5123: "<H", 5125: "<I", 5126: "<f"}
_TYPE_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _component_format(component_type: int) -> str | None:
    return _COMPONENT_FMT.get(component_type)


def _read_positions(gltf: dict, buf_data: bytes) -> list[tuple[float, float, float]]:
    """Read every mesh POSITION accessor's raw values from the buffer.

    Fallback used only when the exporter omitted accessor min/max.  Returns
    object-space values -- correct here because every closure-marker model
    has identity node transforms, so object space equals the culling space.
    """
    buffers = gltf.get("buffers", [])
    buffer_views = gltf.get("bufferViews", [])
    accessors = gltf.get("accessors", [])
    if not buffers or not buffer_views or not accessors:
        return []

    positions: list[tuple[float, float, float]] = []
    seen: set[int] = set()
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            acc_idx = (prim.get("attributes") or {}).get("POSITION")
            if acc_idx is None or acc_idx in seen:
                continue
            seen.add(acc_idx)
            acc = accessors[acc_idx] if acc_idx < len(accessors) else None
            if not acc or acc.get("type") != "VEC3":
                continue
            fmt = _component_format(acc.get("componentType", 5126))
            if not fmt:
                continue
            bv = buffer_views[acc["bufferView"]] if acc.get("bufferView") is not None else None
            if not bv:
                continue
            buf = buffers[bv.get("buffer", 0)] if bv.get("buffer", 0) < len(buffers) else None
            if not buf or not buf_data:
                continue
            offset = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
            stride = bv.get("byteStride") or 12
            count = acc.get("count", 0)
            for i in range(count):
                base = offset + i * stride
                if base + 12 > len(buf_data):
                    break
                x, y, z = struct.unpack_from("<fff", buf_data, base)
                positions.append((x, y, z))
    return positions


def _load_buffer(gltf_path: Path) -> bytes:
    gltf = json.loads(gltf_path.read_text(encoding="utf-8-sig"))
    buffers = gltf.get("buffers", [])
    if not buffers:
        return b""
    uri = buffers[0].get("uri", "")
    if uri.startswith("data:"):
        # data:application/octet-stream;base64,...
        return base64.b64decode(uri.split(",", 1)[1])
    return (gltf_path.parent / uri).read_bytes()


def _global_bounds(gltf: dict, buf_data: bytes) -> tuple[list[float], list[float]]:
    """Compute (min, max) over every mesh POSITION accessor."""
    mins: list[float] | None = None
    maxs: list[float] | None = None
    accessors = gltf.get("accessors", [])
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            acc_idx = (prim.get("attributes") or {}).get("POSITION")
            if acc_idx is None or acc_idx >= len(accessors):
                continue
            acc = accessors[acc_idx]
            if acc.get("type") != "VEC3":
                continue
            lo = acc.get("min")
            hi = acc.get("max")
            if not lo or not hi or len(lo) != 3:
                continue
            if mins is None:
                mins = list(lo)
                maxs = list(hi)
            else:
                for k in range(3):
                    mins[k] = min(mins[k], lo[k])
                    maxs[k] = max(maxs[k], hi[k])
    if mins is None or maxs is None:
        positions = _read_positions(gltf, buf_data)
        if positions:
            mins = [min(p[k] for p in positions) for k in range(3)]
            maxs = [max(p[k] for p in positions) for k in range(3)]
    if mins is None or maxs is None:
        mins = [0.0, 0.0, 0.0]
        maxs = [0.0, 0.0, 0.0]
    return mins, maxs


# ---------------------------------------------------------------------------
# TANGENT computation (standard per-vertex tangent space, glTF handedness w)
# ---------------------------------------------------------------------------

def _decode_accessor(gltf: dict, buf_data: bytes, acc_idx: int):
    """Decode one accessor into a flat list of component tuples.

    Supports tightly-packed and strided bufferViews; returns [] on any
    malformed input rather than raising, so a broken attribute never blocks
    the whole conversion.
    """
    accessors = gltf.get("accessors", [])
    views = gltf.get("bufferViews", [])
    buffers = gltf.get("buffers", [])
    if acc_idx is None or acc_idx >= len(accessors):
        return []
    acc = accessors[acc_idx]
    atype = acc.get("type")
    comps = _TYPE_COMPONENTS.get(atype, 0)
    fmt = _COMPONENT_FMT.get(acc.get("componentType"))
    if not comps or not fmt:
        return []
    bv = views[acc.get("bufferView")] if acc.get("bufferView") is not None else None
    if not bv:
        return []
    buf = buffers[bv.get("buffer", 0)] if bv.get("buffer", 0) < len(buffers) else None
    if buf is None:
        return []
    offset = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    size = struct.calcsize(fmt)
    stride = bv.get("byteStride") or (size * comps)
    count = acc.get("count", 0)
    out = []
    # "<f" * 3 is invalid struct syntax; build "<fff" properly.
    pack = "<" + fmt.lstrip("<@=!") * comps
    for i in range(count):
        base = offset + i * stride
        if base + size * comps > len(buf_data):
            break
        vals = struct.unpack_from(pack, buf_data, base)
        out.append(vals)
    return out


def _vec3(v):
    return (v[0], v[1], v[2])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length(a):
    return (a[0] * a[0] + a[1] * a[1] + a[2] * a[2]) ** 0.5


def _normalize(a):
    ln = _length(a)
    if ln < 1e-12:
        return (0.0, 1.0, 0.0)
    return (a[0] / ln, a[1] / ln, a[2] / ln)


def _compute_tangents_for_primitive(gltf: dict, buf_data: bytes, prim: dict) -> list[tuple] | None:
    """Compute per-vertex TANGENT (vec4, glTF handedness) for one primitive.

    Requires POSITION + NORMAL + TEXCOORD_0.  Uses the classic per-triangle
    accumulation + Gram-Schmidt orthogonalisation against the normal, exactly
    as the glTF reference pipelines (three.js / Blender) do.  Returns None if
    the primitive lacks any required attribute.
    """
    attrs = prim.get("attributes") or {}
    pos_i = attrs.get("POSITION")
    nrm_i = attrs.get("NORMAL")
    uv_i = attrs.get("TEXCOORD_0")
    if pos_i is None or nrm_i is None or uv_i is None:
        return None

    positions = _decode_accessor(gltf, buf_data, pos_i)
    normals = _decode_accessor(gltf, buf_data, nrm_i)
    uvs = _decode_accessor(gltf, buf_data, uv_i)
    if not positions or len(positions) != len(normals) or len(positions) != len(uvs):
        return None

    count = len(positions)
    tan_acc = [[0.0, 0.0, 0.0] for _ in range(count)]
    bitan_acc = [[0.0, 0.0, 0.0] for _ in range(count)]

    idx_i = prim.get("indices")
    if idx_i is not None:
        idx_raw = _decode_accessor(gltf, buf_data, idx_i)
        tris = [int(v[0]) for v in idx_raw]
    else:
        tris = list(range(count))

    for t in range(0, len(tris) - 2, 3):
        i0, i1, i2 = tris[t], tris[t + 1], tris[t + 2]
        if max(i0, i1, i2) >= count:
            continue
        p0 = _vec3(positions[i0]); p1 = _vec3(positions[i1]); p2 = _vec3(positions[i2])
        uv0 = uvs[i0]; uv1 = uvs[i1]; uv2 = uvs[i2]
        e1 = _sub(p1, p0); e2 = _sub(p2, p0)
        duv1 = (uv1[0] - uv0[0], uv1[1] - uv0[1])
        duv2 = (uv2[0] - uv0[0], uv2[1] - uv0[1])
        denom = duv1[0] * duv2[1] - duv2[0] * duv1[1]
        if abs(denom) < 1e-12:
            continue
        r = 1.0 / denom
        t_dir = (
            (e1[0] * duv2[1] - e2[0] * duv1[1]) * r,
            (e1[1] * duv2[1] - e2[1] * duv1[1]) * r,
            (e1[2] * duv2[1] - e2[2] * duv1[1]) * r,
        )
        b_dir = (
            (e2[0] * duv1[0] - e1[0] * duv2[0]) * r,
            (e2[1] * duv1[0] - e1[1] * duv2[0]) * r,
            (e2[2] * duv1[0] - e1[2] * duv2[0]) * r,
        )
        for vi in (i0, i1, i2):
            tan_acc[vi] = (tan_acc[vi][0] + t_dir[0], tan_acc[vi][1] + t_dir[1], tan_acc[vi][2] + t_dir[2])
            bitan_acc[vi] = (bitan_acc[vi][0] + b_dir[0], bitan_acc[vi][1] + b_dir[1], bitan_acc[vi][2] + b_dir[2])

    out = []
    for i in range(count):
        n = _normalize(_vec3(normals[i]))
        t = tan_acc[i]
        # Gram-Schmidt: t' = t - n * dot(n, t)
        t_ortho = (t[0] - n[0] * _dot(n, t), t[1] - n[1] * _dot(n, t), t[2] - n[2] * _dot(n, t))
        ln = _length(t_ortho)
        if ln < 1e-12:
            # Degenerate UVs / zero-area faces: pick an arbitrary tangent
            # perpendicular to the normal.
            ref = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
            t_ortho = _normalize(_cross(n, ref))
        else:
            t_ortho = (t_ortho[0] / ln, t_ortho[1] / ln, t_ortho[2] / ln)
        b = bitan_acc[i]
        w = 1.0 if _dot(_cross(n, t_ortho), b) >= 0.0 else -1.0
        out.append((t_ortho[0], t_ortho[1], t_ortho[2], w))
    return out


def _add_tangents(gltf: dict, buf_data: bytes) -> bytes:
    """Append TANGENT accessors to every mesh primitive; returns new buffer.

    Mutates ``gltf`` in place (primitives get a TANGENT attribute, new
    bufferView + accessor entries are appended) and returns the extended
    buffer bytes.  Idempotent: primitives that already carry TANGENT are
    skipped.  Primitive order is preserved so the packed layout matches the
    JSON bufferViews exactly.
    """
    accessors = gltf.setdefault("accessors", [])
    views = gltf.setdefault("bufferViews", [])
    buf = bytearray(buf_data)
    changed = False

    # Every closure-marker model ships a single buffer; the appended tangent
    # bufferViews are bound to it. Guard against multi-buffer glTFs silently
    # producing corrupt offsets.
    if len(gltf.get("buffers", [])) != 1:
        print("  [msfs-native] WARN: skipping TANGENT (expected exactly one buffer)")
        return bytes(buf)

    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            attrs = prim.setdefault("attributes", {})
            if "TANGENT" in attrs:
                continue
            tangents = _compute_tangents_for_primitive(gltf, bytes(buf), prim)
            if not tangents:
                print(
                    "  [msfs-native] WARN: primitive missing POSITION/NORMAL/TEXCOORD_0 "
                    "- no TANGENT added (mesh may not render)"
                )
                continue
            count = len(tangents)
            # 4-byte alignment for float32 accessors.
            aligned = (len(buf) + 3) & ~3
            buf.extend(b"\x00" * (aligned - len(buf)))
            bv_idx = len(views)
            views.append({"buffer": 0, "byteOffset": aligned, "byteLength": count * 16})
            acc_idx = len(accessors)
            accessors.append(
                {
                    "bufferView": bv_idx,
                    "componentType": 5126,
                    "count": count,
                    "type": "VEC4",
                }
            )
            for v in tangents:
                buf += struct.pack("<ffff", *v)
            attrs["TANGENT"] = acc_idx
            changed = True

    if changed and gltf.get("buffers"):
        gltf["buffers"][0]["byteLength"] = len(buf)
    return bytes(buf)


# ---------------------------------------------------------------------------
# Attribute quantization (MSFS 2024 geometry compiler requires byte/short)
# ---------------------------------------------------------------------------

#: Target format per semantic, from the working corpus (49,546 meshes):
#: NORMAL/TANGENT -> signed byte VEC4 (/127), TEXCOORD_0/1 -> signed short
#: VEC2 (/32767).  POSITION stays float32 with min/max; indices stay 5123.
_QUANTIZE_TARGETS = {
    "NORMAL": (5120, "VEC4"),
    "TANGENT": (5120, "VEC4"),
    "TEXCOORD_0": (5122, "VEC2"),
    "TEXCOORD_1": (5122, "VEC2"),
}


def _quantize_v(value: float, component_type: int) -> int:
    """Float -> quantized int in the target component type's range."""
    if component_type == 5120:  # signed byte, /127
        return max(-128, min(127, int(round(value * 127.0))))
    if component_type == 5122:  # signed short, /32767
        return max(-32768, min(32767, int(round(value * 32767.0))))
    return int(round(value))


def _fract(value: float) -> float:
    """Wrap into [0, 1): sampling-identical under a REPEAT sampler, and the
    only way tiled UVs (barricade stripes tile 6x along X) fit in the short
    range the corpus requires.  Negative UVs (mirrored back faces) wrap too.
    """
    return value - math.floor(value)


def _quantize_attributes(gltf: dict, buf_data: bytes) -> bytes:
    """Rewrite every vertex attribute to MSFS 2024's quantized component types.

    The geometry compiler rejects float NORMAL/TEXCOORD (0 static verts /
    0 static faces while bitmaps/nodes/draws load) -- the corpus is 100%
    byte/short.  NORMAL/TANGENT become signed byte VEC4 (w = 127 for
    NORMAL; TANGENT w keeps its +/-1 handedness, scaled to +/-127).
    TEXCOORD_0/1 become signed short VEC2 with UVs fract-wrapped into
    [0,1) (REPEAT sampling makes the wrap lossless for tiled textures;
    every sampler this pipeline emits uses REPEAT wrapS/wrapT, and the
    barricade stripe material is REPEAT in Blender too).
    POSITION stays float32 (min/max preserved) and indices stay 5123.

    Idempotent: accessors already at the target type are left untouched.
    Returns the rebuilt buffer bytes; mutates ``gltf`` (bufferViews +
    accessors replaced, primitives remapped).
    """
    accessors = gltf.get("accessors", [])
    views = gltf.get("bufferViews", [])
    buffers = gltf.get("buffers", [])
    if not accessors or not buffers:
        return buf_data
    # Same single-buffer contract as _add_tangents: all accessors are decoded
    # from buffer 0's bytes and the rebuilt buffer replaces buffers[0].
    if len(buffers) != 1:
        print("  [msfs-native] WARN: skipping quantization (expected exactly one buffer)")
        return buf_data

    # Figure out the semantic for every accessor index and whether the mesh
    # uses indices (to keep their bufferView target intact).
    semantic_of: dict[int, str] = {}
    index_accessors: set[int] = set()
    primitives = []
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            primitives.append(prim)
            for sem, acc_idx in (prim.get("attributes") or {}).items():
                semantic_of[acc_idx] = sem
            idx = prim.get("indices")
            if idx is not None:
                index_accessors.add(idx)

    # Determine which accessors need rewriting.
    rewrite: dict[int, tuple[int, str]] = {}  # acc_idx -> (componentType, type)
    for acc_idx, sem in semantic_of.items():
        if sem not in _QUANTIZE_TARGETS:
            continue
        if acc_idx >= len(accessors):
            continue
        target = _QUANTIZE_TARGETS[sem]
        acc = accessors[acc_idx]
        if acc.get("componentType") == target[0] and acc.get("type") == target[1]:
            continue  # already quantized
        rewrite[acc_idx] = target

    if not rewrite:
        return buf_data

    # Rebuild the whole buffer: every accessor gets its own bufferView, in
    # accessor order, 4-byte aligned (matches what Blender already emitted
    # and keeps POSITION min/max intact).
    new_buf = bytearray()
    new_views: list[dict] = []
    new_accessors: list[dict] = []
    remap: dict[int, int] = {}

    for acc_idx, acc in enumerate(accessors):
        # Decode the raw values (works for both float and already-quantized
        # accessors via _COMPONENT_FMT).
        values = _decode_accessor(gltf, buf_data, acc_idx)
        if not values:
            # Undecodable accessor: carry over verbatim as its own view
            # (aligned) so index numbering stays aligned.
            bv_idx = acc.get("bufferView")
            body = b""
            if bv_idx is not None and bv_idx < len(views):
                bv = views[bv_idx]
                off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
                body = buf_data[off:off + bv.get("byteLength", 0)]
            pad = (4 - (len(new_buf) % 4)) % 4
            new_buf += b"\x00" * pad
            new_acc = dict(acc)
            new_acc["bufferView"] = len(new_views)
            new_acc["byteOffset"] = 0
            new_views.append(
                {"buffer": 0, "byteOffset": len(new_buf), "byteLength": len(body),
                 "target": 34963 if acc_idx in index_accessors else 34962}
            )
            new_buf += body
            new_accessors.append(new_acc)
            remap[acc_idx] = len(new_accessors) - 1
            continue

        target = rewrite.get(acc_idx)
        if target is None:
            # POSITION / indices / untouched: copy the raw bytes verbatim
            # so float POSITION and 5123 indices survive bit-exact.
            body = bytearray()
            comp_type = acc.get("componentType", 5126)
            fmt = _COMPONENT_FMT.get(comp_type)
            n_comp = _TYPE_COMPONENTS.get(acc.get("type", ""), 0)
            if not fmt or not n_comp:
                pad = (4 - (len(new_buf) % 4)) % 4
                new_buf += b"\x00" * pad
                new_acc = dict(acc)
                new_acc["bufferView"] = len(new_views)
                new_acc["byteOffset"] = 0
                new_views.append(
                    {"buffer": 0, "byteOffset": len(new_buf), "byteLength": 0,
                     "target": 34963 if acc_idx in index_accessors else 34962}
                )
                new_accessors.append(new_acc)
                remap[acc_idx] = len(new_accessors) - 1
                continue
            pack = "<" + fmt.lstrip("<@=!") * n_comp
            for v in values:
                body += struct.pack(pack, *v)
            new_acc = dict(acc)
            new_acc["bufferView"] = len(new_views)
            new_acc["byteOffset"] = 0
        else:
            comp_type, atype = target
            body = bytearray()
            for v in values:
                if atype == "VEC4":
                    # NORMAL w is always +1 (127); TANGENT w keeps handedness.
                    sem = semantic_of.get(acc_idx)
                    w = 127
                    if sem == "TANGENT" and len(v) > 3:
                        w = 127 if v[3] >= 0.0 else -127
                    body += struct.pack(
                        "<4b",
                        _quantize_v(v[0], comp_type),
                        _quantize_v(v[1], comp_type),
                        _quantize_v(v[2], comp_type),
                        w,
                    )
                else:  # VEC2 (TEXCOORD)
                    u = _fract(v[0])
                    t = _fract(v[1])
                    body += struct.pack("<2h", _quantize_v(u, comp_type), _quantize_v(t, comp_type))
            new_acc = {
                "bufferView": len(new_views),
                "byteOffset": 0,
                "componentType": comp_type,
                "count": len(values),
                "type": atype,
            }

        # 4-byte alignment (component sizes are 1/2/4; align to the largest).
        pad = (4 - (len(new_buf) % 4)) % 4
        new_buf += b"\x00" * pad
        new_views.append(
            {
                "buffer": 0,
                "byteOffset": len(new_buf),
                "byteLength": len(body),
                "target": 34963 if acc_idx in index_accessors else 34962,
            }
        )
        new_buf += body
        new_accessors.append(new_acc)
        remap[acc_idx] = len(new_accessors) - 1

    # Remap primitives to the new accessor indices.
    for prim in primitives:
        attrs = prim.get("attributes") or {}
        for sem, acc_idx in list(attrs.items()):
            attrs[sem] = remap.get(acc_idx, acc_idx)
        idx = prim.get("indices")
        if idx is not None:
            prim["indices"] = remap.get(idx, idx)

    gltf["bufferViews"] = new_views
    gltf["accessors"] = new_accessors
    gltf["buffers"][0]["byteLength"] = len(new_buf)
    return bytes(new_buf)


# ---------------------------------------------------------------------------
# DXT1/BC1 DDS texture generation (MSFS 2024 needs DDS via MSFT_texture_dds)
# ---------------------------------------------------------------------------

_DDS_MAGIC = b"DDS "
_DDS_HEADER_SIZE = 124
_DDSF_CAPS = 0x1
_DDSF_HEIGHT = 0x2
_DDSF_WIDTH = 0x4
_DDSF_PIXELFORMAT = 0x1000
_DDSF_LINEARSIZE = 0x80000
_DDPF_FOURCC = 0x4
_DDSCAPS_TEXTURE = 0x1000


def _rgb565(r, g, b):
    """Pack an 8-bit RGB colour into a 565 word (little-endian in the file)."""
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _rgb565_to_rgb(v):
    r = (v >> 11) & 0x1F
    g = (v >> 5) & 0x3F
    b = v & 0x1F
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def _dxt1_block(pixels):
    """Encode 16 RGBA pixels (list of (r,g,b,a) 0..255) as one DXT1 block.

    Uses the classic bounding-box fit: the two endpoint colours are the
    min/max luminance pixels snapped to RGB565, palette interpolation is
    exactly the BC1 4-colour mode.  Solid-colour blocks (all pixels equal)
    degenerate to c0 == c1 == the colour, which decodes to the same colour.
    Returns 8 bytes: c0 (2) + c1 (2) + 16x 2-bit indices (4).
    """
    def lum(p):
        return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]

    if all(p == pixels[0] for p in pixels):
        c = pixels[0]
        cw = _rgb565(c[0], c[1], c[2])
        return struct.pack("<HHI", cw, cw, 0)  # all indices 0 -> c0

    lo = min(range(16), key=lambda i: lum(pixels[i]))
    hi = max(range(16), key=lambda i: lum(pixels[i]))
    c0 = _rgb565(pixels[hi][0], pixels[hi][1], pixels[hi][2])
    c1 = _rgb565(pixels[lo][0], pixels[lo][1], pixels[lo][2])
    # BC1 4-colour mode requires c0 > c1; swap if needed.
    if c0 < c1:
        c0, c1 = c1, c0
    r0, g0, b0 = _rgb565_to_rgb(c0)
    r1, g1, b1 = _rgb565_to_rgb(c1)
    pal = [
        (r0, g0, b0),
        (r1, g1, b1),
        ((2 * r0 + r1) // 3, (2 * g0 + g1) // 3, (2 * b0 + b1) // 3),
        ((r0 + 2 * r1) // 3, (g0 + 2 * g1) // 3, (b0 + 2 * b1) // 3),
    ]
    indices = 0
    for i, p in enumerate(pixels):
        best, bd = 0, None
        for k, pc in enumerate(pal):
            d = (p[0] - pc[0]) ** 2 + (p[1] - pc[1]) ** 2 + (p[2] - pc[2]) ** 2
            if bd is None or d < bd:
                best, bd = k, d
        indices |= best << (2 * i)
    return struct.pack("<HHI", c0, c1, indices)


def _dds_dxt1(width: int, height: int, rgba: bytes) -> bytes:
    """Encode RGBA8 pixels (width*height*4 bytes) as a DXT1 DDS file.

    Includes a full box-filtered mip chain down to 1x1 -- the corpus DDS files
    are ~99.7% mipmapped (only 21/6125 lack mips), and the sampler requests
    LINEAR_MIPMAP_LINEAR, so shipping mips matches the proven format.
    """
    levels: list[tuple[int, int, bytes]] = [(width, height, rgba)]
    w, h, px = width, height, rgba
    while w > 1 or h > 1:
        w2 = max(1, w // 2)
        h2 = max(1, h // 2)
        out = bytearray(w2 * h2 * 4)
        for y in range(h2):
            for x in range(w2):
                r = g = b = a = 0
                cnt = 0
                for sy in (2 * y, 2 * y + 1):
                    for sx in (2 * x, 2 * x + 1):
                        if sx >= w or sy >= h:
                            continue
                        o = (sy * w + sx) * 4
                        r += px[o]; g += px[o + 1]; b += px[o + 2]; a += px[o + 3]
                        cnt += 1
                o = (y * w2 + x) * 4
                if cnt:
                    out[o] = r // cnt; out[o + 1] = g // cnt
                    out[o + 2] = b // cnt; out[o + 3] = a // cnt
        levels.append((w2, h2, bytes(out)))
        w, h, px = w2, h2, bytes(out)

    data = bytearray()
    for lw, lh, lpx in levels:
        bw = (lw + 3) // 4
        bh = (lh + 3) // 4
        for by in range(bh):
            for bx in range(bw):
                block = []
                for py in range(4):
                    for pxx in range(4):
                        x = bx * 4 + pxx
                        y = by * 4 + py
                        if x < lw and y < lh:
                            o = (y * lw + x) * 4
                            block.append((lpx[o], lpx[o + 1], lpx[o + 2], lpx[o + 3]))
                        else:
                            # Pad out-of-bounds pixels with the last valid pixel.
                            block.append(block[-1] if block else (0, 0, 0, 255))
                data += _dxt1_block(block)

    top_bw = (width + 3) // 4
    top_bh = (height + 3) // 4
    top_pitch = top_bw * top_bh * 8
    flags = _DDSF_CAPS | _DDSF_HEIGHT | _DDSF_WIDTH | _DDSF_PIXELFORMAT | _DDSF_LINEARSIZE
    caps = _DDSCAPS_TEXTURE
    if len(levels) > 1:
        flags |= 0x20000  # DDSD_MIPMAPCOUNT
        caps |= 0x8 | 0x400000  # DDSCAPS_COMPLEX | DDSCAPS_MIPMAP
    # DDS header layout: magic + DDS_HEADER (7 I) + dwReserved1[11] +
    # DDS_PIXELFORMAT (8 I: size, flags, fourcc, rgbBitCount, 4x bitmask) +
    # dwCaps + dwCaps2/3/4 + dwReserved2 (5 I) = 128 bytes total.
    header = struct.pack(
        "<4s7I11I8I5I",
        _DDS_MAGIC,
        _DDS_HEADER_SIZE,
        flags,
        height,
        width,
        top_pitch,
        0,          # dwDepth
        len(levels),
        *([0] * 11),  # dwReserved1
        32,         # ddspf.dwSize
        _DDPF_FOURCC,
        0x31545844,  # 'DXT1'
        0,          # dwRGBBitCount
        0, 0, 0, 0,  # RGB bit masks
        caps,
        0, 0, 0,  # dwCaps2/3/4
        0,        # dwReserved2
    )
    assert len(header) == 4 + 124, len(header)
    return bytes(header) + bytes(data)


def _png_decode(path: Path):
    """Decode an 8-bit RGBA PNG (pure stdlib) -> (width, height, rgba bytes).

    Handles the RGB/RGBA (and greyscale / greyscale+alpha) non-interlaced PNGs
    the Blender scripts emit.  Returns None on anything unsupported so callers
    can fall back to a solid colour.  Palette-indexed (color type 3) PNGs are
    NOT decoded -- the Blender pipeline never produces them.
    """
    try:
        data = path.read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        pos = 8
        width = height = None
        bit_depth = color_type = None
        idat = bytearray()
        while pos < len(data):
            length = struct.unpack(">I", data[pos:pos + 4])[0]
            typ = data[pos + 4:pos + 8]
            chunk = data[pos + 8:pos + 8 + length]
            if typ == b"IHDR":
                width, height, bit_depth, color_type, interlace, _, _ = struct.unpack(">IIBBBBB", chunk)
            elif typ == b"IDAT":
                idat += chunk
            elif typ == b"IEND":
                break
            pos += 12 + length
        if width is None or height is None or bit_depth != 8 or interlace != 0:
            return None
        channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type)
        if channels is None:
            return None
        raw = zlib.decompress(bytes(idat))
        stride = width * channels
        out = bytearray()
        prev = bytearray(stride)
        pos = 0
        for y in range(height):
            f = raw[pos]
            pos += 1
            line = bytearray(raw[pos:pos + stride])
            pos += stride
            if f == 0:
                pass
            elif f == 1:  # Sub
                for i in range(channels, stride):
                    line[i] = (line[i] + line[i - channels]) & 0xFF
            elif f == 2:  # Up
                for i in range(stride):
                    line[i] = (line[i] + prev[i]) & 0xFF
            elif f == 3:  # Average
                for i in range(stride):
                    a = line[i - channels] if i >= channels else 0
                    line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
            elif f == 4:  # Paeth
                for i in range(stride):
                    a = line[i - channels] if i >= channels else 0
                    b = prev[i]
                    c = prev[i - channels] if i >= channels else 0
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                    line[i] = (line[i] + pr) & 0xFF
            else:
                return None
            out += line
            prev = line
        # Expand to RGBA8.
        rgba = bytearray()
        for i in range(0, len(out), channels):
            if color_type == 0:  # grey
                rgba += bytes((out[i], out[i], out[i], 255))
            elif color_type == 4:  # grey + alpha
                rgba += bytes((out[i], out[i], out[i], out[i + 1]))
            elif color_type == 2:  # RGB
                rgba += bytes((out[i], out[i + 1], out[i + 2], 255))
            else:  # 6 RGBA
                rgba += bytes((out[i], out[i + 1], out[i + 2], out[i + 3]))
        return width, height, bytes(rgba)
    except Exception:
        return None


def _solid_rgba(width: int, height: int, pixel: tuple[int, int, int, int]) -> bytes:
    return bytes(pixel) * (width * height)


def _add_base_color_textures(gltf: dict, gltf_path: Path) -> None:
    """Give every material a baseColorTexture backed by a DXT1 DDS file.

    Materials without a texture get a solid-white 4x4 DDS (white x
    baseColorFactor = same rendered colour).  Materials whose baseColorTexture
    points at a PNG (e.g. the barricade stripes) get that PNG converted in
    place to a DXT1 DDS.  Every texture then carries the MSFT_texture_dds
    extension exactly like the FNX cone, so MSFS 2024's renderer can load it.
    """
    materials = gltf.get("materials", [])
    if not materials:
        return
    images = gltf.setdefault("images", [])
    textures = gltf.setdefault("textures", [])
    samplers = gltf.setdefault("samplers", [])

    # Map every existing texture to its image (textures[].source -> images[]).
    for m_idx, mat in enumerate(materials):
        pbr = mat.setdefault("pbrMetallicRoughness", {})
        tex_info = pbr.get("baseColorTexture")
        if tex_info is not None and isinstance(tex_info, dict):
            tex_idx = tex_info.get("index")
            if tex_idx is None or tex_idx >= len(textures):
                continue
            tex = textures[tex_idx]
            img_idx = tex.get("source")
            if img_idx is None or img_idx >= len(images):
                continue
            img = images[img_idx]
            uri = img.get("uri", "")
            if uri.lower().endswith(".png"):
                src = gltf_path.parent / uri
                decoded = _png_decode(src)
                if decoded is None:
                    continue
                w, h, rgba = decoded
                dds_name = f"{uri.rsplit('.', 1)[0]}.dds"
                (gltf_path.parent / dds_name).write_bytes(_dds_dxt1(w, h, rgba))
                img["uri"] = dds_name
                img.pop("mimeType", None)
                # point the texture at the DDS via the extension (FNX pattern)
                tex.setdefault("extensions", {})[MSFT_TEXTURE_DDS] = {"source": img_idx}
            continue

        # No texture: generate a solid-white 4x4 DDS and wire it in.
        dds_name = f"{gltf_path.stem}_mat_{m_idx}.dds"
        (gltf_path.parent / dds_name).write_bytes(_dds_dxt1(4, 4, _solid_rgba(4, 4, (255, 255, 255, 255))))
        img_idx = len(images)
        images.append({"uri": dds_name})
        if not samplers:
            samplers.append(
                {
                    "magFilter": 9729,  # LINEAR
                    "minFilter": 9987,  # LINEAR_MIPMAP_LINEAR
                    "wrapS": 10497,     # REPEAT
                    "wrapT": 10497,
                }
            )
        tex_idx = len(textures)
        textures.append({"sampler": 0, "source": img_idx})
        textures[tex_idx].setdefault("extensions", {})[MSFT_TEXTURE_DDS] = {"source": img_idx}
        pbr["baseColorTexture"] = {"index": tex_idx}


def _add_texture_dds_extensions(gltf: dict) -> None:
    """Declare MSFT_texture_dds in extensionsUsed + extensionsRequired.

    Mirrors the FNX cone: the extension is mandatory so the loader can rely on
    the DDS variants.  Only applied when the glTF actually carries textures.
    """
    if not gltf.get("textures"):
        return
    used = gltf.setdefault("extensionsUsed", [])
    if MSFT_TEXTURE_DDS not in used:
        used.append(MSFT_TEXTURE_DDS)
    gltf["extensionsRequired"] = [MSFT_TEXTURE_DDS]



# ---------------------------------------------------------------------------
# ASOBO v4.6 optimized layout repack (interleaved, cone-identical)
# ---------------------------------------------------------------------------

#: The FNX cone's exact interleaved vertex layout (verified against
#: FNX_32X_Cone_LOD00, the proven-working MSFS 2024 SimObject on this
#: machine): stride 36, fixed attribute offsets, no ``normalized`` flags,
#: explicit primitive ``mode`` 4, only POSITION carrying min/max.
#:   POSITION    0   float32 VEC3
#:   TANGENT    12   signed byte VEC4 (w = +/-127 handedness)
#:   NORMAL     16   signed byte VEC4 (w = 127)
#:   TEXCOORD_0 20   signed short VEC2 (/32767)
#:   TEXCOORD_1 24   signed short VEC2 (/32767)
#:   COLOR_0    28   unsigned short VEC4 (/65535)
_OPT_STRIDE = 36
_OPT_OFFSETS = {
    "POSITION": 0,
    "TANGENT": 12,
    "NORMAL": 16,
    "TEXCOORD_0": 20,
    "TEXCOORD_1": 24,
    "COLOR_0": 28,
}
_OPT_ATTRS = [
    ("POSITION", 5126, "VEC3"),
    ("TANGENT", 5120, "VEC4"),
    ("NORMAL", 5120, "VEC4"),
    ("TEXCOORD_0", 5122, "VEC2"),
    ("TEXCOORD_1", 5122, "VEC2"),
    ("COLOR_0", 5123, "VEC4"),
]


def _repack_optimized(gltf: dict, buf_data: bytes) -> bytes:
    """Repack every mesh into the ASOBO v4.6 optimized layout the cone uses.

    MSFS 2024's geometry compiler decodes ASOBO_asset_optimized (v4) buffers
    through a strict fast path: ONE interleaved vertex bufferView (stride 36,
    target ARRAY_BUFFER) plus ONE index bufferView (target ELEMENT_ARRAY_
    BUFFER), explicit ``mode`` 4 on every primitive, and the quantized
    attributes at the fixed per-vertex offsets above.  The looser Khronos
    packing (separate bufferView per attribute, missing mode) makes the
    compiler report 0 static verts / 0 static faces while bitmaps/nodes/
    draws load -- the exact debug-panel signature we were chasing.

    Idempotent: decoding honours byteStride, so a second pass over an already
    repacked file reproduces the identical layout.  Mutates ``gltf``
    (bufferViews/accessors/primitives replaced, bounding box refreshed) and
    returns the new buffer bytes.
    """
    buffers = gltf.get("buffers", [])
    if len(buffers) != 1:
        print("  [msfs-native] WARN: skipping optimized repack (expected one buffer)")
        return buf_data

    vertex_buf = bytearray()
    index_buf = bytearray()
    new_accessors: list[dict] = []
    bmin = [math.inf, math.inf, math.inf]
    bmax = [-math.inf, -math.inf, -math.inf]

    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            attrs = prim.get("attributes") or {}
            pos = _decode_accessor(gltf, buf_data, attrs.get("POSITION"))
            if not pos:
                print(
                    "  [msfs-native] WARN: primitive with no POSITION skipped "
                    "in optimized repack"
                )
                continue
            nrm = _decode_accessor(gltf, buf_data, attrs.get("NORMAL"))
            tan = _decode_accessor(gltf, buf_data, attrs.get("TANGENT"))
            uv0 = _decode_accessor(gltf, buf_data, attrs.get("TEXCOORD_0"))
            idx = _decode_accessor(gltf, buf_data, prim.get("indices"))
            count = len(pos)

            pmin = [math.inf, math.inf, math.inf]
            pmax = [-math.inf, -math.inf, -math.inf]
            vstart = len(vertex_buf)
            for i in range(count):
                p = pos[i]
                vertex_buf += struct.pack("<3f", p[0], p[1], p[2])
                t = tan[i] if i < len(tan) and len(tan[i]) >= 4 else (0, 0, 1, 127)
                vertex_buf += struct.pack("<4b", t[0], t[1], t[2], t[3])
                n = nrm[i] if i < len(nrm) and len(nrm[i]) >= 4 else (0, 0, 1, 127)
                vertex_buf += struct.pack("<4b", n[0], n[1], n[2], n[3])
                u = uv0[i] if i < len(uv0) and len(uv0[i]) >= 2 else (0, 0)
                vertex_buf += struct.pack("<2h", u[0], u[1])
                vertex_buf += struct.pack("<2h", 0, 0)  # TEXCOORD_1 (unused)
                vertex_buf += struct.pack("<4H", 65535, 65535, 65535, 65535)  # COLOR_0 white
                for k in range(3):
                    v = p[k]
                    if v < pmin[k]:
                        pmin[k] = v
                    if v > pmax[k]:
                        pmax[k] = v
                    if v < bmin[k]:
                        bmin[k] = v
                    if v > bmax[k]:
                        bmax[k] = v

            pad = (4 - (len(index_buf) % 4)) % 4
            index_buf += b"\x00" * pad
            istart = len(index_buf)
            if idx:
                for iv in idx:
                    index_buf += struct.pack("<H", int(iv[0]) & 0xFFFF)
                index_count = len(idx)
            else:
                for iv in range(count):
                    index_buf += struct.pack("<H", iv)
                index_count = count

            prim_attrs: dict[str, int] = {}
            for sem, ctype, atype in _OPT_ATTRS:
                acc = {
                    "bufferView": 0,
                    "byteOffset": vstart + _OPT_OFFSETS[sem],
                    "componentType": ctype,
                    "count": count,
                    "type": atype,
                }
                if sem == "POSITION":
                    acc["min"] = list(pmin)
                    acc["max"] = list(pmax)
                prim_attrs[sem] = len(new_accessors)
                new_accessors.append(acc)
            new_accessors.append(
                {
                    "bufferView": 1,
                    "byteOffset": istart,
                    "componentType": 5123,
                    "count": index_count,
                    "type": "SCALAR",
                }
            )
            prim["attributes"] = prim_attrs
            prim["indices"] = len(new_accessors) - 1
            prim["mode"] = 4

    if not vertex_buf:
        print("  [msfs-native] WARN: optimized repack produced no geometry")
        return buf_data

    gltf["bufferViews"] = [
        {"buffer": 0, "byteOffset": 0, "byteLength": len(vertex_buf),
         "byteStride": _OPT_STRIDE, "target": 34962},
        {"buffer": 0, "byteOffset": len(vertex_buf), "byteLength": len(index_buf),
         "target": 34963},
    ]
    gltf["accessors"] = new_accessors
    gltf["buffers"][0]["byteLength"] = len(vertex_buf) + len(index_buf)
    ext = gltf.get("asset", {}).get("extensions", {}).get(ASSET_EXTENSION)
    if ext:
        ext["BoundingBoxMin"] = bmin
        ext["BoundingBoxMax"] = bmax
    return bytes(vertex_buf) + bytes(index_buf)


def convert_file(path: str | Path, write: bool = True) -> dict:
    """Convert one glTF to MSFS-native form and rewrite it (LF, compact).

    Adds the ASOBO extensions, per-vertex TANGENT attributes (with the .bin
    buffer extended in lockstep), and a DXT1 DDS baseColorTexture per material
    wired via the MSFT_texture_dds extension (MSFS 2024 requires DDS textures;
    the stock PNG output is invisible in-sim).  Returns the resulting glTF
    JSON dict (for tests/verification).
    """
    gltf_path = Path(path)
    gltf = json.loads(gltf_path.read_text(encoding="utf-8-sig"))
    buf_data = _load_buffer(gltf_path)

    bmin, bmax = _global_bounds(gltf, buf_data)

    # --- asset extensions -------------------------------------------------
    asset = gltf.setdefault("asset", {})
    extensions = asset.setdefault("extensions", {})
    extensions[ASSET_EXTENSION] = {
        "BoundingBoxMax": bmax,
        "BoundingBoxMin": bmin,
        "MajorVersion": MAJOR_VERSION,
        "MinorVersion": MINOR_VERSION,
        "UseCheckerboardMaterialForMissingTextures": True,
        "UseOnlyFilenameForImageURI": True,
    }
    extensions[NORMAL_CONVENTION] = {"tangent_space_convention": "DirectX"}

    # --- per-node unique ids ----------------------------------------------
    for idx, node in enumerate(gltf.get("nodes", [])):
        node_ext = node.setdefault("extensions", {})
        node_ext[UNIQUE_ID] = {"id": node.get("name") or f"Node_{idx}"}

    # --- emissive materials -------------------------------------------------
    has_emissive = False
    for mat in gltf.get("materials", []):
        if mat.get("emissiveFactor") is not None:
            mat.setdefault("extensions", {})[MATERIAL_EMISSIVE] = {}
            has_emissive = True

    # --- extensionsUsed / extensionsRequired --------------------------------
    used = gltf.setdefault("extensionsUsed", [])
    for ext in (ASSET_EXTENSION, NORMAL_CONVENTION, UNIQUE_ID):
        if ext not in used:
            used.append(ext)
    if has_emissive and MATERIAL_EMISSIVE not in used:
        used.append(MATERIAL_EMISSIVE)

    # --- renderer-critical: TANGENT + quantized attrs + DDS textures -------
    new_buf = _add_tangents(gltf, buf_data)
    new_buf = _quantize_attributes(gltf, new_buf)
    # ASOBO v4.6 interleaved layout (the layout the 2024 compiler decodes;
    # without it geometry reports 0 static verts / 0 static faces in-sim).
    new_buf = _repack_optimized(gltf, new_buf)
    _add_base_color_textures(gltf, gltf_path)
    _add_texture_dds_extensions(gltf)

    if write:
        if new_buf != buf_data:
            _write_buffer(gltf, gltf_path, new_buf)
        payload = json.dumps(gltf, indent=1)
        gltf_path.write_bytes(payload.replace("\r\n", "\n").encode("utf-8"))
    return gltf


def _write_buffer(gltf: dict, gltf_path: Path, data: bytes) -> None:
    """Write the extended buffer back (file URI or embedded data URI)."""
    buffers = gltf.get("buffers", [])
    if not buffers:
        return
    uri = buffers[0].get("uri", "")
    if uri.startswith("data:"):
        prefix = uri.split(",", 1)[0]
        buffers[0]["uri"] = f"{prefix},{base64.b64encode(data).decode()}"
    else:
        (gltf_path.parent / uri).write_bytes(data)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    for arg in sys.argv[1:]:
        gltf = convert_file(arg)
        print(f"  [msfs-native] {arg}: bounds={gltf['asset']['extensions'][ASSET_EXTENSION]['BoundingBoxMin']}.."
              f"{gltf['asset']['extensions'][ASSET_EXTENSION]['BoundingBoxMax']}, "
              f"extensionsUsed={gltf.get('extensionsUsed')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
