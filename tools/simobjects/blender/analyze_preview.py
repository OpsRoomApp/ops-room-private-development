"""Standalone plain-Python pixel analysis of a Blender preview PNG.

Verifies the QA render checklist objectively without touching Blender
(bpy.data.images.load can hang a --background Blender that just used EEVEE).

Decodes the PNG (RGB/RGBA, non-interlaced) with stdlib zlib and classifies
sampled pixels by HUE + saturation + value, NOT by exact RGB distance - a lit
EEVEE/Cycles render of an orange surface comes out darker/desaturated (tan),
so exact-match against the material color always false-negatives.

Run:
    python analyze_preview.py <png> [--orange] [--white] [--amber] [--yellow] [--red] [--all]
"""

import argparse
import struct
import zlib


def decode_png(path: str) -> tuple:
    with open(path, "rb") as fh:
        data = fh.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, w, h, ct, idat = 8, 0, 0, 0, b""
    while pos < len(data):
        (ln,) = struct.unpack(">I", data[pos:pos + 4])
        typ = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, _bd, ct, _cm, _filt, inter = struct.unpack(">IIBBBBB", chunk)
            assert inter == 0, "interlaced PNG not supported"
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
        pos += 12 + ln
    raw = zlib.decompress(idat)
    bpp = 4 if ct == 6 else (3 if ct == 2 else None)
    if bpp is None:
        raise ValueError(f"unsupported PNG color type {ct}")
    stride = w * bpp
    out = bytearray(w * h * 4)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if ft == 1:
                line[x] = (line[x] + a) & 255
            elif ft == 2:
                line[x] = (line[x] + b) & 255
            elif ft == 3:
                line[x] = (line[x] + ((a + b) // 2)) & 255
            elif ft == 4:
                # Paeth (PNG spec): p = a + b - c, then pick a/b/c by the
                # smallest |p - x|. Do NOT use the "shortcut" pc=|a-b|:
                # it is NOT equivalent to |p-c| = |a+b-2c| and silently
                # corrupts every Paeth row (the error only shows on real
                # image data, never on flat Up-filtered background rows).
                pv = a + b - c
                pa = abs(pv - a)
                pb = abs(pv - b)
                pc = abs(pv - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 255
        prev = line
        for x in range(w):
            base = (y * w + x) * 4
            if bpp == 4:
                out[base:base + 4] = line[x * 4:x * 4 + 4]
            else:
                out[base:base + 3] = line[x * 3:x * 3 + 3]
                out[base + 3] = 255
    return w, h, out


def classify(r: int, g: int, b: int) -> str:
    """Hue/saturation/value classification -> one of
    white | orange | amber | yellow | other."""
    mx, mn = max(r, g, b), min(r, g, b)
    sat = (mx - mn) / 255.0
    val = mx / 255.0
    if val < 0.06:
        return "other"  # black
    if sat < 0.13 and val > 0.55:
        return "white"  # near-neutral bright (the white variant rail)
    if sat < 0.13:
        return "other"  # neutral mid/dark (background, shadows)
    # hue in degrees (0-360)
    if mx == mn:
        h = 0.0
    elif mx == r:
        h = (60.0 * ((g - b) / (mx - mn))) % 360.0
    elif mx == g:
        h = 60.0 * ((b - r) / (mx - mn)) + 120.0
    else:
        h = 60.0 * ((r - g) / (mx - mn)) + 240.0
    if (h < 8.0 or h >= 352.0) and sat > 0.15 and val > 0.4:
        return "red"         # warning-red beacon (hue wraps through 0/360).
                             # Checked before orange on purpose: a red emission
                             # core renders at hue ~3-8 (EEVEE bloom pushes it
                             # pink - sat ~0.25-0.35, hence the low sat gate),
                             # while international orange is hue ~17+ and
                             # orange/white AA blend pixels sit at hue 15-17 -
                             # so hue <= 8 keeps the bands cleanly separated
                             # (no false red from orange stripe edges).
    if 42.0 <= h <= 58.0 and val > 0.35:
        return "amber"       # emissive amber lens (checked before yellow so
                             # the bright lens cores classify as amber)
    if 30.0 <= h <= 78.0 and val > 0.40:
        return "yellow"      # safety yellow frame (incl. #E5A93C ~40 deg)
    if 8.0 <= h <= 45.0 and val > 0.22:
        return "orange"      # international orange + lit variants
    return "other"


def fraction(pixels, w, h, target, step=4):
    n_hit = n_tot = 0
    for y in range(0, h, step):
        row = y * w * 4
        for x in range(0, w, step):
            i = row + x * 4
            r, g, b, a = pixels[i], pixels[i + 1], pixels[i + 2], pixels[i + 3]
            if a < 12:
                continue
            n_tot += 1
            if classify(r, g, b) == target:
                n_hit += 1
    return (100.0 * n_hit / n_tot) if n_tot else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("png")
    ap.add_argument("--orange", action="store_true")
    ap.add_argument("--white", action="store_true")
    ap.add_argument("--amber", action="store_true")
    ap.add_argument("--yellow", action="store_true")
    ap.add_argument("--red", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    w, h, pixels = decode_png(args.png)
    print(f"[PNG] {args.png} {w}x{h}")

    checks = [k for k in ("orange", "white", "amber", "yellow", "red") if getattr(args, k) or args.all]
    for name in checks:
        if name == "red":
            # A single beacon dome is TINY in a 1280x1280 frame (~0.03 %), so
            # a percentage threshold can never pass it. Count red pixels at
            # step 2 instead: PASS = a visible cluster (>= 8 samples), which
            # separates a real red light from zero/noise.
            count = 0
            for y in range(0, h, 2):
                row = y * w * 4
                for x in range(0, w, 2):
                    i = row + x * 4
                    r, g, b, a = pixels[i], pixels[i + 1], pixels[i + 2], pixels[i + 3]
                    if a >= 12 and classify(r, g, b) == "red":
                        count += 1
            pct = 100.0 * count / max((h // 2) * (w // 2), 1)
            flag = "PASS" if count >= 8 else ("WEAK" if count >= 2 else "FAIL")
            print(f"[PIXEL] red    : {pct:.2f}% ({count} px) -> {flag}")
        else:
            pct = fraction(pixels, w, h, name)
            flag = "PASS" if pct > 1.5 else ("WEAK" if pct > 0.3 else "FAIL")
            print(f"[PIXEL] {name:6s}: {pct:.2f}% -> {flag}")


if __name__ == "__main__":
    main()
