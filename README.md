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

## Deploying

Push the repo and point Streamlit Community Cloud at `validation_app.py` —
`requirements.txt` is all it needs.

**There is no folder dialog on a hosted app, and there cannot be one.** The app
process runs in a datacenter, not on your laptop: a dialog it opened would
appear on the server, and paths it browses are the server's filesystem. Browsers
deliberately never expose local paths to a page. So the hosted app detects that
it has no dialog backend and switches to upload mode — the browser's own file
picker sends the spectra to the server, and the results come back as a ZIP.
Uploaded files live in a per-session temp folder and go away with the session.

Streamlit Cloud's default upload cap is 200 MB per file; raise it in
`.streamlit/config.toml` if you ever need to:

```toml
[server]
maxUploadSize = 400
```

### The folder dialog (local runs)

*Browse…* opens the system folder chooser of the machine Streamlit runs on,
using the first backend that works:

| Platform | Backend | Needs installing? |
| --- | --- | --- |
| macOS | `osascript` (Finder "choose folder") | no — built into macOS |
| Windows | PowerShell shell folder browser | no |
| Linux | `zenity` / `kdialog` | `sudo apt install zenity` |
| any | `tkinter` (last resort) | `brew install python-tk` etc. |

Each runs in its own process, so a dialog can never freeze Streamlit, and on
macOS it is raised to the front via System Events so it doesn't hide behind the
browser window.

To check the dialog outside the app:

```bash
python folder_picker.py     # prints the backend, then opens the dialog
```

If nothing can open a dialog, folder mode is not offered at all and the app
uses upload mode. Should a dialog fail unexpectedly on a local run, *Browse…*
falls back to an in-app folder browser and shows exactly why each backend was
skipped. Set `UVVIS_NO_NATIVE_DIALOG=1` to force upload mode locally.

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
