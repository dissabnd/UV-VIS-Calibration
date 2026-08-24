#!/usr/bin/env python3
"""
Streamlit interface for Nia UV-Vis method validation.

Point it at a folder of Shimadzu .spc files named  Nia_<conc>pct_rep<n>.SPC.
It derives the calibration equation (absorbance vs concentration) and saves
per-file CSVs + spectrum PNGs, a calibration curve, and an HTML report
covering repeatability, sensitivity and linearity.

Run:
    pip install -r requirements.txt
    streamlit run validation_app.py
"""

import os

import pandas as pd
import streamlit as st

from folder_picker import folder_selector
from spc_validation import analyze

IN_KEY = "rawdir"
OUT_KEY = "outdir"
OUT_MANUAL = "outdir_is_manual"

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

c1, c2 = st.columns(2)
with c1:
    peak = st.number_input("Nia peak wavelength (nm)", value=240.0, step=1.0)
with c2:
    window = st.number_input("Peak search half-width (± nm)", value=5.0, step=0.5)

if st.button("Run analysis", type="primary"):
    if not os.path.isdir(rawdir):
        st.error(f"Folder not found: {rawdir}")
        st.stop()
    try:
        with st.spinner("Reading spectra and computing statistics…"):
            res = analyze(rawdir, outdir, target=peak, window=window)
    except Exception as e:
        st.error(f"Analysis failed: {e}")
        st.stop()

    st.success(f"Done. Outputs saved to  {os.path.abspath(outdir)}")

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

    with open(res["report"], "rb") as fh:
        st.download_button("Download HTML report", fh.read(),
                           file_name="validation_report.html", mime="text/html")
    st.caption(f"Full report: {res['report']}")
