"""Unit tests for tools/simobjects/package/msfs_native.py.

Run:  python tools/simobjects/package/test_msfs_native.py
"""

from __future__ import annotations

import base64
import json
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import msfs_native  # noqa: E402


def _cube_gltf_bytes(with_tangent_inputs: bool = True) -> bytes:
    """A tiny 2-triangle cube glTF with a data-URI buffer.

    When ``with_tangent_inputs`` is set the mesh carries NORMAL + TEXCOORD_0
    so the converter can compute TANGENT (the real models always do).
    """
    # 8 corners of a 2x2x2 cube centered at origin; 12 triangles.
    verts = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
             (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    # normals: outward unit vectors (same 8 directions as positions/2)
    normals = [(v[0] / 2, v[1] / 2, v[2] / 2) for v in verts]
    # uv: repeat 0..1 over 2x2 faces
    uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)] * 2
    tris = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
            (0, 4, 5), (0, 5, 1), (1, 5, 6), (1, 6, 2),
            (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0)]

    raw = b"".join(struct.pack("<fff", *v) for v in verts)
    pos_offset = 0
    nrm_offset = len(raw)
    raw += b"".join(struct.pack("<fff", *v) for v in normals)
    uv_offset = len(raw)
    raw += b"".join(struct.pack("<ff", *v) for v in uvs)
    idx_offset = len(raw)
    raw += b"".join(struct.pack("<3H", *t) for t in tris)

    accessors = [
        {"bufferView": 0, "byteOffset": 0, "componentType": 5126,
         "count": len(verts), "type": "VEC3", "min": [-1, -1, -1], "max": [1, 1, 1]},
        {"bufferView": 0, "byteOffset": nrm_offset, "componentType": 5126,
         "count": len(normals), "type": "VEC3"},
        {"bufferView": 0, "byteOffset": uv_offset, "componentType": 5126,
         "count": len(uvs), "type": "VEC2"},
        {"bufferView": 0, "byteOffset": idx_offset, "componentType": 5123,
         "count": len(tris) * 3, "type": "SCALAR"},
    ]
    attributes = {"POSITION": 0}
    if with_tangent_inputs:
        attributes["NORMAL"] = 1
        attributes["TEXCOORD_0"] = 2

    gltf = {
        "asset": {"version": "2.0", "generator": "test"},
        "scene": 0,
        "scenes": [{"nodes": [0, 1]}],
        "nodes": [
            {"name": "BODY", "mesh": 0},
            {"name": "LID", "mesh": 0, "translation": [0, 0, 2]},
        ],
        "meshes": [
            {
                "name": "Cube",
                "primitives": [
                    {
                        "attributes": attributes,
                        "indices": 3,
                        "mode": 4,
                        "material": 0,
                    }
                ],
            }
        ],
        "accessors": accessors,
        "bufferViews": [
            {"buffer": 0, "byteOffset": pos_offset, "byteLength": len(raw)},
        ],
        "buffers": [
            {
                "byteLength": len(raw),
                "uri": "data:application/octet-stream;base64,"
                + base64.b64encode(raw).decode(),
            }
        ],
        "materials": [
            {"name": "Plain", "pbrMetallicRoughness": {"baseColorFactor": [1, 0, 0, 1]}},
            {"name": "Glow", "emissiveFactor": [1, 1, 0.2]},
        ],
    }
    return json.dumps(gltf).encode()


def test_conversion(tmp: str) -> None:
    path = os.path.join(tmp, "PROBE.gltf")
    with open(path, "wb") as fh:
        fh.write(_cube_gltf_bytes())
    g = msfs_native.convert_file(path)

    # --- asset-level extensions -------------------------------------------
    aext = g["asset"]["extensions"]["ASOBO_asset_optimized"]
    assert aext["BoundingBoxMin"] == [-1.0, -1.0, -1.0], aext
    assert aext["BoundingBoxMax"] == [1.0, 1.0, 1.0], aext
    assert aext["MajorVersion"] == 4 and aext["MinorVersion"] == 6
    assert g["asset"]["extensions"]["ASOBO_normal_map_convention"] == {
        "tangent_space_convention": "DirectX"
    }

    # --- per-node unique ids on EVERY node --------------------------------
    for node in g["nodes"]:
        assert "ASOBO_unique_id" in node["extensions"], node
    assert g["nodes"][0]["extensions"]["ASOBO_unique_id"] == {"id": "BODY"}

    # --- emissive material extension ---------------------------------------
    glow = g["materials"][1]
    assert "ASOBO_material_emissive" in glow["extensions"]
    assert "ASOBO_material_emissive" not in g["materials"][0].get("extensions", {})

    # --- TANGENT computed and wired into the primitive ----------------------
    prim = g["meshes"][0]["primitives"][0]
    assert "TANGENT" in prim["attributes"], prim
    tan_acc = g["accessors"][prim["attributes"]["TANGENT"]]
    assert tan_acc["type"] == "VEC4"
    assert tan_acc["componentType"] == 5120  # signed byte /127 (MSFS corpus)
    assert tan_acc["count"] == 8, tan_acc

    # --- attribute quantization (MSFS 2024 requires byte/short) -------------
    attrs = prim["attributes"]
    pos_acc = g["accessors"][attrs["POSITION"]]
    nrm_acc = g["accessors"][attrs["NORMAL"]]
    uv_acc = g["accessors"][attrs["TEXCOORD_0"]]
    assert pos_acc["componentType"] == 5126 and pos_acc["type"] == "VEC3"  # stays float
    assert pos_acc.get("min") == [-1, -1, -1] and pos_acc.get("max") == [1, 1, 1]
    assert nrm_acc["componentType"] == 5120 and nrm_acc["type"] == "VEC4"  # byte VEC4
    assert uv_acc["componentType"] == 5122 and uv_acc["type"] == "VEC2"  # short VEC2
    # ASOBO v4.6 optimized repack: 8 verts * stride 36 + 36 ushort indices.
    assert g["buffers"][0]["byteLength"] == 8 * 36 + 36 * 2, g["buffers"][0]
    # cone-identical interleaved layout (see test_repack_cone_layout).
    assert len(g["bufferViews"]) == 2, g["bufferViews"]
    assert g["bufferViews"][0]["byteStride"] == 36
    assert g["bufferViews"][0]["target"] == 34962
    assert g["bufferViews"][1]["target"] == 34963
    assert prim.get("mode") == 4

    # --- baseColorTexture on every material + DXT1 DDS written ---------------
    for mat in g["materials"]:
        pbr = mat.get("pbrMetallicRoughness") or {}
        assert "baseColorTexture" in pbr, mat
    assert len(g["images"]) == 2
    assert len(g["textures"]) == 2
    assert len(g["samplers"]) == 1
    for img in g["images"]:
        dds_path = os.path.join(tmp, img["uri"])
        assert os.path.exists(dds_path), dds_path
        raw = open(dds_path, "rb").read()
        assert raw[:4] == b"DDS ", dds_path
        assert raw[84:88] == b"DXT1", dds_path  # fourcc
        # header + mip chain: 4x4 (1 block) + 2x2 (1) + 1x1 (1) = 24 bytes
        assert len(raw) == 128 + 24, len(raw)
        mips = struct.unpack_from("<I", raw, 28)[0]
        assert mips == 3, mips  # dwMipMapCount

    # --- MSFT_texture_dds extension on every texture + extensionsRequired ----
    for tex in g["textures"]:
        ext = tex.get("extensions", {}).get(msfs_native.MSFT_TEXTURE_DDS)
        assert ext is not None and "source" in ext, tex
    assert msfs_native.MSFT_TEXTURE_DDS in g["extensionsUsed"]
    assert g.get("extensionsRequired") == [msfs_native.MSFT_TEXTURE_DDS]

    # --- extensionsUsed ----------------------------------------------------
    for ext in ("ASOBO_asset_optimized", "ASOBO_normal_map_convention",
                "ASOBO_unique_id", "ASOBO_material_emissive"):
        assert ext in g["extensionsUsed"], ext

    # --- idempotent: converting again leaves structure identical ------------
    g2 = msfs_native.convert_file(path)
    assert g2 == g

    # --- written file is LF -------------------------------------------------
    with open(path, "rb") as fh:
        assert b"\r\n" not in fh.read()
    print("  PASS: test_conversion")


def test_no_tangent_inputs(tmp: str) -> None:
    """Primitives without NORMAL/TEXCOORD still convert (defaults filled)."""
    path = os.path.join(tmp, "NORMALS_ONLY.gltf")
    with open(path, "wb") as fh:
        fh.write(_cube_gltf_bytes(with_tangent_inputs=False))
    g = msfs_native.convert_file(path)
    prim = g["meshes"][0]["primitives"][0]
    # The repack fills every attribute slot (TANGENT defaults to +Z/w=127).
    assert "POSITION" in prim["attributes"] and "COLOR_0" in prim["attributes"]
    assert prim.get("mode") == 4
    # textures still added
    for mat in g["materials"]:
        assert "baseColorTexture" in (mat.get("pbrMetallicRoughness") or {}), mat
    print("  PASS: test_no_tangent_inputs")


def _png_bytes_red4() -> bytes:
    """Tiny 4x4 solid-red RGBA PNG (same encoder shape as Blender's output)."""
    import zlib as _zlib

    def chunk(typ: bytes, data: bytes) -> bytes:
        import struct as _s

        return _s.pack(">I", len(data)) + typ + data + _s.pack(">I", _zlib.crc32(typ + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes((255, 0, 0, 255)) * 4 for _ in range(4))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", _zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def test_existing_png_texture_converted(tmp: str) -> None:
    """A material whose baseColorTexture points at a PNG gets a DDS instead."""
    gltf = json.loads(_cube_gltf_bytes())
    # Give material 0 a real PNG base-color texture.
    png = _png_bytes_red4()
    gltf.setdefault("images", [])
    gltf.setdefault("textures", [])
    img_idx = len(gltf["images"])
    gltf["images"].append({"uri": "RED.png", "mimeType": "image/png"})
    tex_idx = len(gltf["textures"])
    gltf["textures"].append({"sampler": 0, "source": img_idx})
    gltf["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"] = {"index": tex_idx}
    path = os.path.join(tmp, "WITH_PNG.gltf")
    with open(path, "wb") as fh:
        fh.write(json.dumps(gltf).encode())
    with open(os.path.join(tmp, "RED.png"), "wb") as fh:
        fh.write(png)

    g = msfs_native.convert_file(path)
    img = g["images"][img_idx]
    assert img["uri"] == "RED.dds", img
    assert os.path.exists(os.path.join(tmp, "RED.dds"))
    # original PNG stays on disk as an unreferenced fallback (build_package
    # copies all *.png anyway); the glTF must reference only the DDS.
    assert os.path.exists(os.path.join(tmp, "RED.png"))
    tex = g["textures"][tex_idx]
    assert tex["extensions"][msfs_native.MSFT_TEXTURE_DDS] == {"source": img_idx}
    # every material still has a texture (material 1 got a generated one)
    for mat in g["materials"]:
        assert "baseColorTexture" in (mat.get("pbrMetallicRoughness") or {}), mat
    print("  PASS: test_existing_png_texture_converted")


def test_buffer_fallback(tmp: str) -> None:
    """Bounds must survive even when the exporter omitted accessor min/max."""
    gltf = json.loads(_cube_gltf_bytes())
    for acc in gltf["accessors"]:
        acc.pop("min", None)
        acc.pop("max", None)
    path = os.path.join(tmp, "NO_MINMAX.gltf")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(gltf, fh)
    g = msfs_native.convert_file(path)
    bmin = g["asset"]["extensions"]["ASOBO_asset_optimized"]["BoundingBoxMin"]
    bmax = g["asset"]["extensions"]["ASOBO_asset_optimized"]["BoundingBoxMax"]
    assert bmin == [-1.0, -1.0, -1.0], bmin
    assert bmax == [1.0, 1.0, 1.0], bmax
    print("  PASS: test_buffer_fallback")


def test_repack_cone_layout(tmp: str) -> None:
    """Assert the ASOBO v4.6 layout matches the FNX cone byte-for-byte.

    Verified against FNX_32X_Cone_LOD00.gltf (the proven MSFS 2024 SimObject
    on this machine): one interleaved vertex bufferView (stride 36, target
    34962), one index bufferView (target 34963), fixed attribute offsets,
    explicit mode 4, no normalized flags, min/max on POSITION only.
    """
    path = os.path.join(tmp, "CONE_LAYOUT.gltf")
    with open(path, "wb") as fh:
        fh.write(_cube_gltf_bytes())
    g = msfs_native.convert_file(path)

    views = g["bufferViews"]
    assert len(views) == 2, views
    assert views[0]["byteStride"] == 36 and views[0]["target"] == 34962
    assert views[1]["target"] == 34963
    assert views[1]["byteOffset"] == views[0]["byteLength"]

    prim = g["meshes"][0]["primitives"][0]
    assert prim.get("mode") == 4, prim
    accs = g["accessors"]
    expected = {
        "POSITION": (5126, "VEC3", 0),
        "TANGENT": (5120, "VEC4", 12),
        "NORMAL": (5120, "VEC4", 16),
        "TEXCOORD_0": (5122, "VEC2", 20),
        "TEXCOORD_1": (5122, "VEC2", 24),
        "COLOR_0": (5123, "VEC4", 28),
    }
    for sem, (ct, atype, off) in expected.items():
        a = accs[prim["attributes"][sem]]
        assert a["componentType"] == ct, (sem, a)
        assert a["type"] == atype, (sem, a)
        assert a["byteOffset"] == off, (sem, a)
        assert a.get("normalized") is None, (sem, a)
        assert a["bufferView"] == 0
        if sem == "POSITION":
            assert a["min"] == [-1.0, -1.0, -1.0] and a["max"] == [1.0, 1.0, 1.0]
        else:
            assert "min" not in a and "max" not in a, (sem, a)
    ia = accs[prim["indices"]]
    assert ia["componentType"] == 5123 and ia["type"] == "SCALAR"
    assert ia["bufferView"] == 1 and ia["byteOffset"] == 0
    assert ia["count"] == 36
    # white COLOR_0 payload
    buf = base64.b64decode(g["buffers"][0]["uri"].split(",", 1)[1])
    assert struct.unpack_from("<4H", buf, 28) == (65535, 65535, 65535, 65535)
    # vertex stride stays 4-byte aligned end to end
    assert views[1]["byteOffset"] % 4 == 0

    # idempotent: converting the already-repacked file is identical
    g2 = msfs_native.convert_file(path)
    assert g2 == g
    print("  PASS: test_repack_cone_layout")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        test_conversion(tmp)
        test_no_tangent_inputs(tmp)
        test_buffer_fallback(tmp)
        test_existing_png_texture_converted(tmp)
        test_repack_cone_layout(tmp)
    print("RESULTS: msfs_native tests PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
