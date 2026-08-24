#!/usr/bin/env python3
"""
Nia UV-Vis method-validation analysis from Shimadzu .spc files.

Given a folder of files named  Nia_<conc>pct_rep<n>.SPC  (e.g. Nia_0.25pct_rep2.SPC),
this module:
  * reads every spectrum (Shimadzu binary variant, GRAMS fallback),
  * saves a per-file CSV and spectrum PNG,
  * measures the analytical signal at the Nia peak (~240 nm),
  * computes repeatability (%RSD per level), calibration sensitivity (slope),
    linearity (R^2, residuals) and LOD/LOQ,
  * writes an HTML validation report plus results CSVs.

Concentration is parsed in percent. 'p' is treated as a decimal point, so
Nia_0p25pct_rep1.SPC and Nia_0.25pct_rep1.SPC both mean 0.25 %.
"""

import os
import re
import csv
import glob
import struct
import base64
import datetime as _dt

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from read_spc import read_shimadzu_spc, read_grams_spc


# ----------------------------- parsing ------------------------------------

_CONC_RE = re.compile(r"([0-9]+(?:[.p][0-9]+)?)\s*pct", re.IGNORECASE)
_REP_RE = re.compile(r"rep[_-]?([0-9]+)", re.IGNORECASE)


def parse_filename(name):
    """Return (concentration_percent, replicate_int) from a filename, or (None, None)."""
    stem = os.path.splitext(os.path.basename(name))[0]
    cm = _CONC_RE.search(stem)
    rm = _REP_RE.search(stem)
    conc = float(cm.group(1).replace("p", ".")) if cm else None
    rep = int(rm.group(1)) if rm else 1
    return conc, rep


def load_spectrum(path):
    """Read one .spc file -> (x_array, y_array) as numpy arrays."""
    try:
        x, y = read_shimadzu_spc(path)
    except (ValueError, struct.error):
        x, y = read_grams_spc(path)
    return np.asarray(x, float), np.asarray(y, float)


def peak_signal(x, y, target=240.0, window=5.0):
    """Absorbance at the Nia peak: max y within [target-window, target+window].
    Falls back to the nearest wavelength if the window is empty.
    Returns (peak_wavelength, peak_absorbance)."""
    mask = (x >= target - window) & (x <= target + window)
    if mask.any():
        idx = np.where(mask)[0]
        j = idx[np.argmax(y[idx])]
    else:
        j = int(np.argmin(np.abs(x - target)))
    return float(x[j]), float(y[j])


# ----------------------------- statistics ---------------------------------

def repeatability(records):
    """records: list of dicts with 'conc' and 'abs'. Returns per-level stats."""
    levels = {}
    for r in records:
        levels.setdefault(r["conc"], []).append(r["abs"])
    rows = []
    for conc in sorted(levels):
        vals = np.array(levels[conc], float)
        mean = vals.mean()
        sd = vals.std(ddof=1) if len(vals) > 1 else 0.0
        rsd = 100 * sd / mean if mean else float("nan")
        rows.append({"conc": conc, "n": len(vals), "mean": mean, "sd": sd, "rsd_pct": rsd})
    return rows


def linearity(rep_rows):
    """Linear fit of mean absorbance vs concentration.
    Returns dict with slope, intercept, r2, residual SD, LOD, LOQ."""
    concs = np.array([r["conc"] for r in rep_rows], float)
    means = np.array([r["mean"] for r in rep_rows], float)

    slope, intercept = np.polyfit(concs, means, 1)
    pred = slope * concs + intercept
    ss_res = float(np.sum((means - pred) ** 2))
    ss_tot = float(np.sum((means - means.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")

    # Residual standard deviation of the calibration (proxy for blank noise).
    dof = len(concs) - 2
    resid_sd = float(np.sqrt(ss_res / dof)) if dof > 0 else float("nan")
    lod = 3.3 * resid_sd / slope if slope else float("nan")
    loq = 10.0 * resid_sd / slope if slope else float("nan")

    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "r2": float(r2),
        "resid_sd": resid_sd,
        "lod_pct": float(lod),
        "loq_pct": float(loq),
        "concs": concs.tolist(),
        "means": means.tolist(),
    }


# ----------------------------- plotting -----------------------------------

def save_spectrum_png(x, y, target, window, out_png, title):
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(x, y, lw=1)
    ax.axvspan(target - window, target + window, color="orange", alpha=0.15)
    wl, ab = peak_signal(x, y, target, window)
    ax.plot([wl], [ab], "ro", ms=4)
    ax.annotate(f"{ab:.4g} @ {wl:g} nm", (wl, ab),
                textcoords="offset points", xytext=(6, 6), fontsize=8)
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Absorbance")
    ax.set_title(title, fontsize=9)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


def save_calibration_png(lin, out_png):
    concs = np.array(lin["concs"]); means = np.array(lin["means"])
    xs = np.linspace(concs.min(), concs.max(), 100)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(concs, means, "o", label="mean absorbance")
    ax.plot(xs, lin["slope"] * xs + lin["intercept"], "-",
            label=f"y = {lin['slope']:.4g}x + {lin['intercept']:.4g}\n$R^2$ = {lin['r2']:.5f}")
    ax.set_xlabel("Concentration (% Nia)")
    ax.set_ylabel("Peak absorbance")
    ax.set_title("Calibration / linearity")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


def save_overlay_png(spectra, target, window, out_png):
    fig, ax = plt.subplots(figsize=(7, 4))
    for label, (x, y) in sorted(spectra.items()):
        ax.plot(x, y, lw=1, label=label)
    ax.axvspan(target - window, target + window, color="orange", alpha=0.12)
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Absorbance")
    ax.set_title("Mean spectrum per concentration")
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(out_png, dpi=130)
    plt.close(fig)


# ----------------------------- report -------------------------------------

def _b64(path):
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode()


def build_report(out_html, meta, file_rows, rep_rows, lin, calib_png, overlay_png):
    def fmt(v, p=4):
        return "" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{p}g}"

    file_tbl = "\n".join(
        f"<tr><td>{r['file']}</td><td>{fmt(r['conc'])}</td><td>{r['rep']}</td>"
        f"<td>{fmt(r['peak_wl'])}</td><td>{fmt(r['abs'],5)}</td></tr>"
        for r in file_rows)

    rep_tbl = "\n".join(
        f"<tr><td>{fmt(r['conc'])}</td><td>{r['n']}</td><td>{fmt(r['mean'],5)}</td>"
        f"<td>{fmt(r['sd'],3)}</td><td>{fmt(r['rsd_pct'],3)}</td></tr>"
        for r in rep_rows)

    sat = [r["conc"] for r in rep_rows if r["mean"] > 1.0]
    sat_note = (f"<p class='warn'>Note: mean absorbance &gt; 1.0 AU at "
                f"{', '.join(fmt(c) for c in sat)} % — Beer-Lambert linearity may "
                f"break here; consider excluding or diluting these levels and refitting "
                f"the linear sub-range.</p>") if sat else ""

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Nia UV method validation</title>
<style>
 body{{font-family:system-ui,Arial,sans-serif;margin:32px;color:#222;max-width:900px}}
 h1{{font-size:20px}} h2{{font-size:15px;margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:4px}}
 table{{border-collapse:collapse;font-size:13px;margin:8px 0}}
 th,td{{border:1px solid #ccc;padding:4px 8px;text-align:right}} th{{background:#f4f4f4}}
 td:first-child,th:first-child{{text-align:left}}
 .kv{{font-size:14px}} .kv b{{display:inline-block;min-width:230px}}
 .warn{{color:#a15c00;background:#fff6e5;padding:8px;border-radius:4px;font-size:13px}}
 img{{max-width:100%;border:1px solid #eee;margin:6px 0}}
</style></head><body>
<h1>Nia UV-Vis method validation report</h1>
<p class="kv">Generated {meta['date']} &middot; source folder: <code>{meta['rawdir']}</code><br>
Analytical peak: {fmt(meta['target'])} nm (window &plusmn;{fmt(meta['window'])} nm) &middot;
{meta['n_files']} spectra, {len(rep_rows)} concentration levels</p>

<h2>1. Repeatability (precision)</h2>
<p class="kv">Per-level %RSD of peak absorbance. Acceptance is method-specific
(commonly &lt;2% mid-range; higher tolerated near the detection limit).</p>
<table><tr><th>Conc (%)</th><th>n</th><th>Mean Abs</th><th>SD</th><th>%RSD</th></tr>
{rep_tbl}</table>

<h2>2. Sensitivity &amp; linearity</h2>
<p class="kv">
<b>Calibration sensitivity (slope):</b> {fmt(lin['slope'],5)} AU per %<br>
<b>Intercept:</b> {fmt(lin['intercept'],5)} AU<br>
<b>Coefficient of determination R&sup2;:</b> {fmt(lin['r2'],6)}<br>
<b>Residual SD (s):</b> {fmt(lin['resid_sd'],4)} AU<br>
<b>LOD (3.3&middot;s/slope):</b> {fmt(lin['lod_pct'],3)} %<br>
<b>LOQ (10&middot;s/slope):</b> {fmt(lin['loq_pct'],3)} %</p>
{sat_note}
<img src="data:image/png;base64,{_b64(calib_png)}" alt="calibration curve">

<h2>3. Spectra</h2>
<img src="data:image/png;base64,{_b64(overlay_png)}" alt="overlay">

<h2>4. Per-file measurements</h2>
<table><tr><th>File</th><th>Conc (%)</th><th>Rep</th><th>Peak nm</th><th>Abs</th></tr>
{file_tbl}</table>

<p class="kv" style="color:#888;margin-top:24px">Specificity/selectivity not assessed:
no blank/placebo or interferent samples were provided. LOD/LOQ here use the
calibration residual SD as a noise proxy; a measured blank gives a cleaner estimate.</p>
</body></html>"""

    with open(out_html, "w") as fh:
        fh.write(html)
    return out_html


# ----------------------------- driver -------------------------------------

def analyze(rawdir, outdir, target=240.0, window=5.0):
    """Run the full validation over a folder of .spc files. Returns a results dict."""
    os.makedirs(outdir, exist_ok=True)
    csv_dir = os.path.join(outdir, "csv")
    png_dir = os.path.join(outdir, "png")
    os.makedirs(csv_dir, exist_ok=True)
    os.makedirs(png_dir, exist_ok=True)

    files = sorted(
        p for p in glob.glob(os.path.join(rawdir, "*"))
        if p.lower().endswith(".spc")
    )
    if not files:
        raise FileNotFoundError(f"No .spc files found in {rawdir}")

    file_rows = []
    by_conc_spectra = {}      # conc -> list of (x,y) for averaging
    for path in files:
        conc, rep = parse_filename(path)
        x, y = load_spectrum(path)
        stem = os.path.splitext(os.path.basename(path))[0]

        # per-file CSV
        with open(os.path.join(csv_dir, stem + ".csv"), "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(["Wavelength_nm", "Absorbance"])
            w.writerows(zip(x, y))
        # per-file spectrum PNG
        save_spectrum_png(x, y, target, window,
                          os.path.join(png_dir, stem + ".png"), stem)

        wl, ab = peak_signal(x, y, target, window)
        file_rows.append({"file": os.path.basename(path), "conc": conc,
                          "rep": rep, "peak_wl": wl, "abs": ab})
        if conc is not None:
            by_conc_spectra.setdefault(conc, []).append((x, y))

    usable = [r for r in file_rows if r["conc"] is not None]
    if not usable:
        raise ValueError("No filenames matched the Nia_<conc>pct_rep<n> pattern.")

    rep_rows = repeatability(usable)
    lin = linearity(rep_rows)

    # mean spectrum per concentration for the overlay (assumes shared x-grid)
    mean_spectra = {}
    for conc, specs in by_conc_spectra.items():
        x0 = specs[0][0]
        ys = np.vstack([s[1] for s in specs if len(s[1]) == len(x0)])
        mean_spectra[f"{conc:g}%"] = (x0, ys.mean(axis=0))

    calib_png = os.path.join(outdir, "calibration_curve.png")
    overlay_png = os.path.join(outdir, "spectra_overlay.png")
    save_calibration_png(lin, calib_png)
    save_overlay_png(mean_spectra, target, window, overlay_png)

    # results CSVs
    with open(os.path.join(outdir, "peak_measurements.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["file", "conc_pct", "rep", "peak_wl", "absorbance"])
        for r in file_rows:
            w.writerow([r["file"], r["conc"], r["rep"], r["peak_wl"], r["abs"]])
    with open(os.path.join(outdir, "repeatability.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["conc_pct", "n", "mean_abs", "sd", "rsd_pct"])
        for r in rep_rows:
            w.writerow([r["conc"], r["n"], r["mean"], r["sd"], r["rsd_pct"]])

    meta = {"date": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "rawdir": os.path.abspath(rawdir), "target": target,
            "window": window, "n_files": len(file_rows)}
    report = build_report(os.path.join(outdir, "validation_report.html"),
                          meta, file_rows, rep_rows, lin, calib_png, overlay_png)

    return {"file_rows": file_rows, "rep_rows": rep_rows, "linearity": lin,
            "report": report, "outdir": outdir}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Nia .spc method-validation analysis.")
    ap.add_argument("rawdir", help="folder of Nia_<conc>pct_rep<n>.SPC files")
    ap.add_argument("-o", "--outdir", default="output", help="output folder")
    ap.add_argument("--peak", type=float, default=240.0, help="analytical wavelength (nm)")
    ap.add_argument("--window", type=float, default=5.0, help="peak search half-width (nm)")
    a = ap.parse_args()
    res = analyze(a.rawdir, a.outdir, a.peak, a.window)
    print("Report:", res["report"])
    for r in res["rep_rows"]:
        print(f"  {r['conc']:>6g}%  n={r['n']}  mean={r['mean']:.4g}  %RSD={r['rsd_pct']:.3g}")
    L = res["linearity"]
    print(f"  slope={L['slope']:.4g}  R2={L['r2']:.5f}  LOD={L['lod_pct']:.3g}%  LOQ={L['loq_pct']:.3g}%")
