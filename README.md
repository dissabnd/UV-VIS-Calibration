# UV-Vis Calibration

A small Streamlit app that gives you the **calibration equation of a UV-Vis
method** from a folder of Shimadzu `.spc` spectra.

Point it at a folder of standards, and it reads every spectrum, measures the
absorbance at the analytical peak, and fits absorbance against concentration:

```
A = slope × C + intercept        (with R², LOD and LOQ)
```

Alongside the equation it writes a calibration curve, a spectra overlay,
per-file CSVs, and an HTML validation report covering repeatability,
sensitivity and linearity.

## Install

```bash
git clone <this-repo>
cd <this-repo>
pip install -r requirements.txt
```

Python 3.9+.

**Optional — GRAMS/Galactic `.spc` files.** Shimadzu files (what this app is
built for) are read by the bundled reader and need nothing extra. Only if you
also have standard GRAMS `.spc` files:

```bash
pip install --no-build-isolation spc-spectra
```

The `--no-build-isolation` flag is required: `spc-spectra`'s `setup.py` imports
the package, which imports numpy, so a plain `pip install spc-spectra` fails
with *"Failed to build spc-spectra"* / `ModuleNotFoundError: No module named
'numpy'` inside pip's isolated build environment. This is why it is not in
`requirements.txt`.

## Run

```bash
streamlit run validation_app.py
```

The app picks its input mode automatically:

| Where it runs | Input | Output |
| --- | --- | --- |
| your own machine | **📁 Folder** — *Browse…* opens the Finder/Explorer folder dialog | written to a folder on disk |
| a server (Streamlit Cloud, any remote host) | **⬆️ Upload** — select the `.spc` files in the browser | downloaded as a ZIP |

Running locally you get both options and can switch between them; on a server
only upload is offered, because a server process cannot open a dialog on your
computer (see [Deploying](#deploying)).

Then:

1. **Raw data folder** — click *Browse…* and pick the folder in the normal
   Finder/Explorer dialog. No typing paths.
   *(Upload mode: select all the `.spc` files at once.)*
2. **Output folder** — defaults to `<raw data folder>/output`. Click *Browse…*
   if you want it elsewhere; *Use default* puts it back.
   *(Upload mode: results come back as **⬇ All results (ZIP)**.)*
3. Set the analytical wavelength (default 240 nm) and the peak search
   half-width (default ±5 nm).
4. **Run analysis** — the calibration equation appears at the top of the
   results, with R², LOD and LOQ.

## Deploying in Streamlit

```
https://uv-vis-calibration-irrd86awc6hkakegnz6kam.streamlit.app/
```


## Input file naming

Files must be named so the concentration and replicate can be read off:

```
Nia_<conc>pct_rep<n>.SPC
```

Examples: `Nia_0.25pct_rep1.SPC`, `Nia_0p25pct_rep2.SPC` (a `p` is read as a
decimal point), `Nia_1pct_rep3.SPC`. Concentrations are in percent.

## Output

Written into the output folder:

```
output/
├── validation_report.html     full report (equation, tables, embedded plots)
├── calibration_curve.png      absorbance vs concentration with the fitted line
├── spectra_overlay.png        mean spectrum per concentration
├── peak_measurements.csv      per-file peak wavelength and absorbance
├── repeatability.csv          per-level mean, SD and %RSD
├── csv/                       one wavelength/absorbance CSV per spectrum
└── png/                       one spectrum plot per file
```

## Command line

The analysis also runs without the UI:

```bash
python spc_validation.py /path/to/rawdata -o /path/to/output --peak 240 --window 5
```

And a single `.spc` file can be converted on its own:

```bash
python read_spc.py sample.SPC --plot
```

## How it works

| File | Role |
| --- | --- |
| `validation_app.py` | Streamlit UI (folder mode locally, upload mode on a server) |
| `folder_picker.py` | system folder dialog + in-app fallback browser |
| `spc_validation.py` | peak picking, repeatability, linear fit, report |
| `read_spc.py` | Shimadzu `.spc` binary reader (GRAMS fallback) |

The reader handles the Shimadzu binary variant (version byte `0x10`) that the
generic GRAMS `spc` library cannot open, and falls back to `spc-spectra` for
standard GRAMS/Galactic files.

Calibration statistics: the fit is an ordinary least-squares line through the
mean absorbance of each concentration level. LOD and LOQ use the calibration
residual standard deviation `s` as a noise proxy (`3.3·s/slope` and
`10·s/slope`); a measured blank gives a cleaner estimate. Levels with a mean
absorbance above 1.0 AU are flagged in the report, since Beer-Lambert
linearity often breaks there.

## Notes

Specificity/selectivity is not assessed — that needs blank/placebo and
interferent samples.

## License

MIT
