#!/usr/bin/env python3
"""
Streamlit interface for Nia UV-Vis method validation.

Two ways to give it spectra, chosen automatically:

  * running on your own machine  -> pick the folder of .spc files with the
    system folder dialog, results are written next to it;
  * running on a server (Streamlit Community Cloud, any remote host) -> upload
    the .spc files through the browser, results come back as a ZIP. A server
    cannot open a dialog on your computer, so folder picking is hidden there.

Either way it derives the calibration equation (absorbance vs concentration)
plus repeatability, sensitivity and linearity, and writes per-file CSVs,
spectrum PNGs, a calibration curve and an HTML report.

Run:
    pip install -r requirements.txt
    streamlit run validation_app.py
"""

import os
import shutil
import tempfile

import pandas as pd
import streamlit as st

from folder_picker import dialog_backend, folder_selector
from spc_validation import analyze

IN_KEY = "rawdir"
OUT_KEY = "outdir"
OUT_MANUAL = "outdir_is_manual"

# A system folder dialog is only meaningful when the app and the browser are on
# the same machine. On a hosted deployment there is no dialog backend at all.
LOCAL = dialog_backend() is not None

st.set_page_config(page_title="Nia UV validation", page_icon="📈", layout="wide")
st.title("Nia UV-Vis method validation")
st.caption("Calibration equation, repeatability, sensitivity and linearity from "
           "Shimadzu .spc spectra (files named Nia_<conc>pct_rep<n>.SPC)")


def default_output_for(rawdir: str) -> str:
    return os.path.join(rawdir, "output")


def _input_changed(new_path: str):
    """Keep the output folder pinned to <input>/output until the user picks one."""
    if not st.session_state.get(OUT_MANUAL):
        st.session_state[OUT_KEY] = default_output_for(new_path)


def _output_changed(_new_path: str):
    st.session_state[OUT_MANUAL] = True


def _session_dir(kind: str) -> str:
    """A temp folder that lives as long as this browser session."""
    key = f"_tmp_{kind}"
    if key not in st.session_state or not os.path.isdir(st.session_state[key]):
        st.session_state[key] = tempfile.mkdtemp(prefix=f"uvvis_{kind}_")
    return st.session_state[key]


def render_results(res, outdir, zip_path=None):
    lin = res["linearity"]
    sign = "+" if lin["intercept"] >= 0 else "-"
    st.subheader("Calibration equation")
    st.latex(r"A = %.5g \times C\ %s\ %.5g \qquad R^2 = %.5f"
             % (lin["slope"], sign, abs(lin["intercept"]), lin["r2"]))
    st.caption("A = peak absorbance (AU), C = concentration (% Nia)")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Slope (AU / %)", f"{lin['slope']:.4g}")
    m2.metric("R²", f"{lin['r2']:.5f}")
    m3.metric("LOD (%)", f"{lin['lod_pct']:.3g}")
    m4.metric("LOQ (%)", f"{lin['loq_pct']:.3g}")

    st.subheader("Repeatability")
    rep_df = pd.DataFrame(res["rep_rows"]).rename(columns={
        "conc": "Conc (%)", "n": "n", "mean": "Mean Abs", "sd": "SD", "rsd_pct": "%RSD"})
    st.dataframe(rep_df, hide_index=True)

    g1, g2 = st.columns(2)
    with g1:
        st.subheader("Calibration / linearity")
        st.image(os.path.join(outdir, "calibration_curve.png"))
    with g2:
        st.subheader("Mean spectra")
        st.image(os.path.join(outdir, "spectra_overlay.png"))

    st.subheader("Per-file measurements")
    st.dataframe(pd.DataFrame(res["file_rows"]), hide_index=True)

    d1, d2 = st.columns(2)
    with open(res["report"], "rb") as fh:
        d1.download_button("⬇ HTML report", fh.read(),
                           file_name="validation_report.html", mime="text/html")
    if zip_path:
        with open(zip_path, "rb") as fh:
            d2.download_button("⬇ All results (ZIP)", fh.read(),
                               file_name="uv_validation_results.zip",
                               mime="application/zip", type="primary")


def run(rawdir, outdir, peak, window, make_zip=False):
    try:
        with st.spinner("Reading spectra and computing statistics…"):
            res = analyze(rawdir, outdir, target=peak, window=window)
    except Exception as e:
        st.error(f"Analysis failed: {e}")
        return
    zip_path = None
    if make_zip:
        base = os.path.join(_session_dir("zip"), "uv_validation_results")
        zip_path = shutil.make_archive(base, "zip", outdir)
    else:
        st.success(f"Done. Outputs saved to  {os.path.abspath(outdir)}")
    st.session_state["last_run"] = (res, outdir, zip_path)


# --------------------------------------------------------------------------
# input selection
# --------------------------------------------------------------------------

if LOCAL:
    source = st.radio(
        "Where are the spectra?",
        ["📁 Folder on this computer", "⬆️ Upload .spc files"],
        horizontal=True,
    )
else:
    source = "⬆️ Upload .spc files"
    st.info("This app is running on a server, so it cannot open a folder dialog "
            "on your computer — upload the .spc files instead. "
            "Run it locally (`streamlit run validation_app.py`) to pick a folder.")

uploaded = None
rawdir = outdir = None

if source.endswith("Folder on this computer"):
    st.session_state.setdefault(IN_KEY, os.path.abspath("rawdata"))
    st.session_state.setdefault(OUT_KEY, default_output_for(st.session_state[IN_KEY]))
    st.session_state.setdefault(OUT_MANUAL, False)

    col1, col2 = st.columns(2)
    with col1:
        rawdir = folder_selector(
            "Raw data folder", key=IN_KEY,
            help="Folder containing the .SPC files",
            on_change=_input_changed,
        )
    with col2:
        outdir = folder_selector(
            "Output folder", key=OUT_KEY,
            help="Where CSVs, PNGs and the report are written "
                 "(default: a new 'output' folder inside the raw data folder)",
            on_change=_output_changed,
            must_exist=False,
        )
        if st.session_state[OUT_MANUAL]:
            if st.button("↺ Use default (input folder / output)", key="out_default"):
                st.session_state[OUT_KEY] = default_output_for(st.session_state[IN_KEY])
                st.session_state[OUT_MANUAL] = False
                st.rerun()
else:
    uploaded = st.file_uploader(
        "Upload the .spc files (select them all at once)",
        type=["spc", "SPC"], accept_multiple_files=True,
        help="Names must follow Nia_<conc>pct_rep<n>.SPC, e.g. Nia_0.25pct_rep1.SPC",
    )
    if uploaded:
        st.caption(f"{len(uploaded)} file(s) ready: " +
                   ", ".join(f.name for f in uploaded[:6]) +
                   ("…" if len(uploaded) > 6 else ""))

c1, c2 = st.columns(2)
with c1:
    peak = st.number_input("Nia peak wavelength (nm)", value=240.0, step=1.0)
with c2:
    window = st.number_input("Peak search half-width (± nm)", value=5.0, step=0.5)

# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------

if st.button("Run analysis", type="primary"):
    st.session_state.pop("last_run", None)
    if uploaded is not None:
        if not uploaded:
            st.error("Upload at least one .spc file first.")
            st.stop()
        updir, tmp_out = _session_dir("in"), _session_dir("out")
        for d in (updir, tmp_out):          # start each run from a clean slate
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d, exist_ok=True)
        for f in uploaded:
            with open(os.path.join(updir, os.path.basename(f.name)), "wb") as fh:
                fh.write(f.getbuffer())
        run(updir, tmp_out, peak, window, make_zip=True)
    else:
        if not os.path.isdir(rawdir):
            st.error(f"Folder not found: {rawdir}")
            st.stop()
        run(rawdir, outdir, peak, window)

if "last_run" in st.session_state:
    render_results(*st.session_state["last_run"])
