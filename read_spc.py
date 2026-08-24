#!/usr/bin/env python3
"""
Read a Shimadzu .spc spectrum (IR / UV-Vis), export to CSV, and optionally plot.

This handles the Shimadzu binary variant (version byte 0x10) that the generic
GRAMS `spc` library cannot read. Layout, reverse-engineered from real files:

    offset 0x0A  float32  X start (e.g. 600.0)
    offset 0x0E  float32  X end   (e.g. 505.5)
    offset 0x76  uint16   number of data points N
    offset 0x78  float32  N Y values (data block runs to end of file)
    X for point i = Xstart + i * (Xend - Xstart) / (N - 1)

If the file is actually a standard GRAMS/Galactic .spc, it falls back to the
`spc-spectra` library when installed.

Usage:
    python read_spc.py D-WBL.SPC                 # -> D-WBL.csv
    python read_spc.py D-WBL.SPC -o out.csv      # custom output name
    python read_spc.py *.SPC                      # batch convert
    python read_spc.py D-WBL.SPC --plot          # also save a PNG

matplotlib is only needed for --plot:  pip install matplotlib
"""

import argparse
import glob
import os
import struct
import sys


def read_shimadzu_spc(path):
    """Parse a Shimadzu .spc file. Returns (x_list, y_list)."""
    with open(path, "rb") as fh:
        d = fh.read()

    if len(d) < 122:
        raise ValueError("file too small to be a Shimadzu .spc")

    x0 = struct.unpack_from("<f", d, 0x0A)[0]
    x1 = struct.unpack_from("<f", d, 0x0E)[0]
    n = struct.unpack_from("<H", d, 0x76)[0]

    expected = 0x78 + 4 * n
    if n == 0 or expected > len(d):
        raise ValueError(
            f"point count {n} inconsistent with file size {len(d)} "
            "(this may not be the Shimadzu variant)"
        )

    y = list(struct.unpack_from("<%df" % n, d, 0x78))
    step = (x1 - x0) / (n - 1) if n > 1 else 0.0
    x = [x0 + i * step for i in range(n)]
    return x, y


def read_grams_spc(path):
    """Fallback for standard GRAMS/Galactic .spc via the spc-spectra library."""
    try:
        import spc_spectra as spc
    except ImportError:
        try:
            import spc
        except ImportError:
            raise RuntimeError(
                "Not a Shimadzu .spc and the GRAMS reader isn't installed.\n"
                "Try: pip install --no-build-isolation spc-spectra\n"
                "(--no-build-isolation is required: its setup.py imports numpy)"
            )
    f = spc.File(path)
    sub = f.sub[0]
    x = list(getattr(sub, "x", getattr(f, "x", [])))
    y = list(sub.y)
    return x, y


def load(path):
    try:
        return read_shimadzu_spc(path)
    except (ValueError, struct.error):
        return read_grams_spc(path)


def write_csv(x, y, out_path):
    import csv
    with open(out_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["X", "Y"])
        w.writerows(zip(x, y))


def plot(x, y, png_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.figure(figsize=(8, 5))
    plt.plot(x, y, lw=1)
    plt.xlabel("X")
    plt.ylabel("Y")
    plt.tight_layout()
    plt.savefig(png_path, dpi=150)
    plt.close()


def main():
    ap = argparse.ArgumentParser(description="Convert Shimadzu .spc files to CSV.")
    ap.add_argument("files", nargs="+", help=".spc file(s); wildcards allowed")
    ap.add_argument("-o", "--output", help="output CSV (single-file mode only)")
    ap.add_argument("--plot", action="store_true", help="also save a PNG plot")
    args = ap.parse_args()

    paths = []
    for pattern in args.files:
        paths.extend(glob.glob(pattern) or [pattern])

    for path in paths:
        if not os.path.isfile(path):
            print(f"skip (not found): {path}")
            continue
        try:
            x, y = load(path)
        except Exception as e:
            print(f"error: {path}: {e}")
            continue
        base = os.path.splitext(path)[0]
        csv_path = args.output if (args.output and len(paths) == 1) else base + ".csv"
        write_csv(x, y, csv_path)
        rng = f"{x[0]:g}..{x[-1]:g}" if x else "?"
        print(f"{path} -> {csv_path}  ({len(y)} points, X {rng})")
        if args.plot:
            png_path = base + ".png"
            plot(x, y, png_path)
            print(f"{path} -> {png_path}")


if __name__ == "__main__":
    main()
