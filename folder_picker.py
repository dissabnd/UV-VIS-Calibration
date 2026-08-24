#!/usr/bin/env python3
"""
Folder selection widgets for the Streamlit app.

"Browse…" opens the **system folder dialog** of whatever machine Streamlit is
running on, using the first backend that works:

    macOS    osascript  ->  the standard Finder "choose folder" dialog
    Windows  PowerShell ->  the shell folder browser
    Linux    zenity / kdialog
    any      tkinter (if the Python has it), as a last resort

All of them run in a **separate process**, so a dialog can never block or
crash Streamlit's script thread. On macOS the dialog is raised to the front
via System Events, so it does not hide behind the browser window.

If no dialog backend is available (typically a headless/remote deployment),
"Browse…" falls back to an in-app folder browser and says why.

The selected path lives in ``st.session_state[key]``.
"""

import inspect
import os
import shutil
import subprocess
import sys
import tempfile

import streamlit as st

# Streamlit renamed the full-width flag: use_container_width -> width="stretch".
_FULL = ({"width": "stretch"}
         if "width" in inspect.signature(st.button).parameters
         else {"use_container_width": True})

DIALOG_TIMEOUT = 600  # seconds the user has to answer the dialog

CANCELLED = ""        # user closed the dialog without choosing


# --------------------------------------------------------------------------
# backends.  Each returns (path, error):
#   (path, "")      a folder was chosen
#   ("",   "")      the user cancelled
#   (None, "why")   this backend cannot be used here
# --------------------------------------------------------------------------

_APPLESCRIPT = '''on run argv
	set thePrompt to item 1 of argv
	set theStart to item 2 of argv
	set useLoc to false
	set defaultLoc to ""
	if theStart is not "" then
		try
			set defaultLoc to (POSIX file theStart) as alias
			set useLoc to true
		end try
	end if
	set out to ""
	try
		-- ask System Events so the dialog comes to the front
		set out to POSIX path of (my pickFront(thePrompt, defaultLoc, useLoc))
	on error errMsg number errNum
		if errNum is -128 then
			set out to ""
		else
			-- no permission to drive System Events: plain dialog instead
			try
				set out to POSIX path of (my pickPlain(thePrompt, defaultLoc, useLoc))
			on error number -128
				set out to ""
			end try
		end if
	end try
	return out
end run

on pickFront(p, loc, useLoc)
	tell application "System Events"
		activate
		if useLoc then
			set f to choose folder with prompt p default location loc
		else
			set f to choose folder with prompt p
		end if
	end tell
	return f
end pickFront

on pickPlain(p, loc, useLoc)
	if useLoc then
		set f to choose folder with prompt p default location loc
	else
		set f to choose folder with prompt p
	end if
	return f
end pickPlain
'''

_POWERSHELL = (
    "$ErrorActionPreference='Stop';"
    "$shell = New-Object -ComObject Shell.Application;"
    "$folder = $shell.BrowseForFolder(0, $args[0], 0, $args[1]);"
    "if ($folder -ne $null) { [Console]::Out.Write($folder.Self.Path) }"
)

_TK_SRC = r"""
import sys
import tkinter as tk
from tkinter import filedialog

root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
initial = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None
title = sys.argv[2] if len(sys.argv) > 2 else "Select folder"
path = filedialog.askdirectory(initialdir=initial, title=title, mustexist=False)
root.destroy()
sys.stdout.write(path or "")
"""


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=DIALOG_TIMEOUT, **kw)


def _osascript(initialdir, title):
    if sys.platform != "darwin":
        return None, "not macOS"
    exe = shutil.which("osascript")
    if not exe:
        return None, "osascript not found"
    start = initialdir if initialdir and os.path.isdir(initialdir) else ""
    fd, script = tempfile.mkstemp(suffix=".applescript")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(_APPLESCRIPT)
        proc = _run([exe, script, title, start])
    finally:
        try:
            os.unlink(script)
        except OSError:
            pass
    if proc.returncode != 0:
        return None, (proc.stderr or "osascript failed").strip()
    return proc.stdout.strip().rstrip("/") or CANCELLED, ""


def _powershell(initialdir, title):
    if sys.platform != "win32":
        return None, "not Windows"
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return None, "powershell not found"
    start = initialdir if initialdir and os.path.isdir(initialdir) else ""
    proc = _run([exe, "-NoProfile", "-STA", "-Command", _POWERSHELL, title, start])
    if proc.returncode != 0:
        return None, (proc.stderr or "powershell failed").strip()
    return proc.stdout.strip() or CANCELLED, ""


def _zenity(initialdir, title):
    exe = shutil.which("zenity")
    if exe:
        cmd = [exe, "--file-selection", "--directory", f"--title={title}"]
        if initialdir:
            cmd.append(f"--filename={os.path.join(initialdir, '')}")
        proc = _run(cmd)
        if proc.returncode == 0:
            return proc.stdout.strip(), ""
        if proc.returncode == 1:
            return CANCELLED, ""
        return None, (proc.stderr or "zenity failed").strip()
    exe = shutil.which("kdialog")
    if exe:
        proc = _run([exe, "--getexistingdirectory", initialdir or os.path.expanduser("~")])
        if proc.returncode == 0:
            return proc.stdout.strip(), ""
        if proc.returncode == 1:
            return CANCELLED, ""
        return None, (proc.stderr or "kdialog failed").strip()
    return None, "zenity/kdialog not found"


def _tk(initialdir, title):
    try:
        import tkinter  # noqa: F401
    except Exception as exc:
        return None, f"tkinter unavailable ({exc})"
    if sys.platform not in ("darwin", "win32") and not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return None, "no display for tkinter"
    proc = _run([sys.executable, "-c", _TK_SRC, initialdir or "", title])
    if proc.returncode != 0:
        return None, (proc.stderr or "tkinter dialog failed").strip()
    return proc.stdout.strip() or CANCELLED, ""


_BACKENDS = [("osascript", _osascript), ("powershell", _powershell),
             ("zenity/kdialog", _zenity), ("tkinter", _tk)]


def open_native_dialog(initialdir="", title="Select folder"):
    """Open the system folder dialog.

    Returns ``(path, backend, notes)``:
      * ``path``    the chosen folder, ``""`` if cancelled, ``None`` if no
                    dialog could be opened at all;
      * ``backend`` name of the backend that answered (``None`` if none did);
      * ``notes``   per-backend messages, useful for the diagnostics panel.
    """
    if os.environ.get("UVVIS_NO_NATIVE_DIALOG"):
        return None, None, ["disabled by UVVIS_NO_NATIVE_DIALOG"]
    notes = []
    for name, fn in _BACKENDS:
        try:
            path, err = fn(initialdir, title)
        except subprocess.TimeoutExpired:
            notes.append(f"{name}: timed out waiting for the dialog")
            continue
        except Exception as exc:                     # pragma: no cover
            notes.append(f"{name}: {exc}")
            continue
        if path is None:
            notes.append(f"{name}: {err}")
            continue
        return path, name, notes
    return None, None, notes


def dialog_backend():
    """Name of the backend that would be used, or None. Cheap - no dialog."""
    if os.environ.get("UVVIS_NO_NATIVE_DIALOG"):
        return None
    if sys.platform == "darwin" and shutil.which("osascript"):
        return "osascript"
    if sys.platform == "win32" and (shutil.which("powershell") or shutil.which("pwsh")):
        return "powershell"
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if sys.platform not in ("darwin", "win32") and not has_display:
        return None          # headless server: no dialog can reach a user
    if shutil.which("zenity") or shutil.which("kdialog"):
        return "zenity/kdialog"
    try:
        import tkinter  # noqa: F401
        return "tkinter"
    except Exception:
        return None


# --------------------------------------------------------------------------
# in-app fallback browser
# --------------------------------------------------------------------------

def _subdirs(path):
    try:
        with os.scandir(path) as it:
            names = [e.name for e in it if e.is_dir() and not e.name.startswith(".")]
    except (PermissionError, FileNotFoundError, NotADirectoryError):
        return None
    return sorted(names, key=str.lower)


def _goto(key, browse_key, path):
    """Move the in-app browser to `path`.

    The path text box is keyed on the folder itself (see ``_render_browser``),
    so a fresh box - showing the new path - is created on the next run.
    """
    st.session_state[browse_key] = os.path.abspath(os.path.expanduser(path))


def _set(key, value, on_change):
    st.session_state[key] = os.path.abspath(os.path.expanduser(value))
    if on_change:
        on_change(st.session_state[key])


def folder_selector(label, key, default="", help=None, on_change=None,
                    must_exist=True, browse_label="📂 Browse…"):
    """Render a folder chooser and return the selected absolute path.

    Parameters
    ----------
    label : str        heading shown above the control
    key : str          st.session_state key holding the selected path
    default : str      initial path when nothing is selected yet
    on_change : func   called with the new path whenever the selection changes
    must_exist : bool  warn when the selected folder does not exist
    """
    st.session_state.setdefault(
        key, os.path.abspath(os.path.expanduser(default or os.getcwd()))
    )
    browse_key = f"{key}__cwd"
    open_key = f"{key}__open"
    notes_key = f"{key}__notes"

    st.markdown(f"**{label}**")
    if help:
        st.caption(help)
    st.code(st.session_state[key], language=None)

    cols = st.columns([1, 3])
    if cols[0].button(browse_label, key=f"{key}__browsebtn", **_FULL):
        with st.spinner("Waiting for the folder dialog…"):
            path, backend, notes = open_native_dialog(st.session_state[key], label)
        st.session_state[notes_key] = notes
        if path:                       # a folder was chosen
            _set(key, path, on_change)
            _goto(key, browse_key, path)
            st.session_state[open_key] = False
            st.rerun()
        elif backend:                  # dialog opened, user cancelled
            st.rerun()
        else:                          # no dialog available -> in-app browser
            st.session_state[open_key] = True
            _goto(key, browse_key, st.session_state[key])

    notes = st.session_state.get(notes_key)
    if notes and st.session_state.get(open_key):
        st.warning("Could not open the system folder dialog — pick a folder below.")
        with st.expander("Why? (dialog diagnostics)"):
            st.write(f"platform: `{sys.platform}`, python: `{sys.executable}`")
            for line in notes:
                st.write(f"- {line}")

    if st.session_state.get(open_key):
        _render_browser(key, browse_key, open_key, on_change)

    path = st.session_state[key]
    if must_exist and not os.path.isdir(path):
        st.warning("This folder does not exist yet.")
    return path


def _render_browser(key, browse_key, open_key, on_change):
    with st.container(border=True):
        st.session_state.setdefault(browse_key, st.session_state[key])
        cur = st.session_state[browse_key]

        # The widget key includes the current folder, so navigating by button
        # rebuilds the box with the new path instead of keeping a stale value.
        typed = st.text_input(
            "Path", value=cur, key=f"{key}__typed__{abs(hash(cur))}",
            help="Type or paste a path, then press Enter",
        )
        typed = os.path.abspath(os.path.expanduser(typed)) if typed else cur
        if typed != cur:
            if os.path.isdir(typed):
                _goto(key, browse_key, typed)
                st.rerun()
            else:
                st.caption("⚠️ Not a folder: " + typed)

        nav = st.columns([1, 1, 1, 2])
        if nav[0].button("⬆ Up", key=f"{key}__up", **_FULL):
            _goto(key, browse_key, os.path.dirname(cur.rstrip(os.sep)) or os.sep)
            st.rerun()
        if nav[1].button("🏠 Home", key=f"{key}__home", **_FULL):
            _goto(key, browse_key, "~")
            st.rerun()
        if nav[2].button("↺ Reset", key=f"{key}__reset", **_FULL):
            _goto(key, browse_key, st.session_state[key])
            st.rerun()
        if nav[3].button("✅ Use this folder", key=f"{key}__use",
                        type="primary", **_FULL):
            _set(key, cur, on_change)
            st.session_state[open_key] = False
            st.rerun()

        names = _subdirs(cur)
        if names is None:
            st.error("Cannot read this folder (missing or no permission).")
            return
        if not names:
            st.caption("No sub-folders here.")
            return

        try:
            box = st.container(height=240)
        except TypeError:      # Streamlit < 1.31 has no scrollable container
            box = st.container()
        with box:
            for name in names:
                if st.button(f"📁 {name}", key=f"{key}__d__{name}", **_FULL):
                    _goto(key, browse_key, os.path.join(cur, name))
                    st.rerun()


if __name__ == "__main__":
    # Quick check outside Streamlit:  python folder_picker.py
    print("platform:", sys.platform)
    print("backend that will be used:", dialog_backend())
    path, backend, notes = open_native_dialog(os.getcwd(), "Select a folder")
    print("chosen:", repr(path), "via", backend)
    for n in notes:
        print("note:", n)
