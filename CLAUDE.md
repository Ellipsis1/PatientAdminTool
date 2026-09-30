# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Windows-only Tkinter desktop app. A virtualenv lives in `.venv/`.

```
pip install -r requirements.txt          # pyinstaller, tkinterdnd2, pdfplumber
python PatientAdminTool.py               # run the GUI
python -m unittest -v                    # all tests
python -m unittest test_patient_core.DateTests.test_formats   # single test
```

`pdfplumber` and `tkinterdnd2` are optional at runtime: imports are guarded (`core.PDF_AVAILABLE`, `DND_AVAILABLE`) and the GUI degrades to click-to-browse / manual entry. Keep new optional deps behind the same pattern.

The app is distributed as a PyInstaller exe; `core.app_dir()` resolves to the exe's folder when frozen, and the bundled `lists.json` is expected next to it.

## Architecture

Two modules, strict split:

- `patient_core.py` — all logic, no GUI imports. Unit tested by `test_patient_core.py`.
- `PatientAdminTool.py` — the Tk window only (`App` class). It collects form values into a plain dict `d` (keys: `name_id, center, designer, arch_type, tooth_shade, stl_only, split_file, cutback, ios_box, scan_date, rx_date, due_date, surgery_date`) and passes it to core functions. New logic belongs in core, not the GUI.

Workflow the code implements: Rx PDF → pre-filled form → CaseNotes.txt + patient folder on the Desktop → case files copied (never moved) into subfolders with standardized names.

### Key invariants

- **Naming mirrors a legacy Excel sheet.** `patient_from()` splits `"R. Yel B658-CGAF"` exactly like the old Excel formula, and `build_casenotes()` mirrors its CONCATENATE output character-for-character (the `C7/C8/C11/C12` variable names are Excel cell refs). Don't "clean up" whitespace or blank lines in the output — downstream users rely on the exact text.
- **`ARCH_TYPES` order is load-bearing.** `UPPER_ARCH = ARCH_TYPES[0:15]` and `LOWER_ARCH = ARCH_TYPES[4:19]` (the "Double" types overlap both). Inserting or reordering entries changes upper/lower logic in CaseNotes and `guess_role`. This is why arch types are *not* editable via `lists.json`.
- **File roles** are defined once in `ROLES` (label, name template, destination subfolders). `STL_DIR` is a placeholder resolved to `"<uid> STL"`; `MAIN_DIR` (`""`) is the patient folder root. Some roles copy to two folders. `guess_role()` infers a role from filename tokens/extension, falling back on arch type; `None` means the user must choose.
- **`plan_file_copies()` is pure planning** — computes destinations, resolves collisions with `_02`, `_03`… suffixes (against disk and within the batch), numbers screenshots after existing ones. `copy_files()` does the I/O. Keep the plan/execute split so the GUI can preview names live.
- **Rx PDF parsing** (`parse_rx_pdf`) is best-effort, using word x-positions on page 1 (hard-coded column offsets like 110/120/140/360) for a specific ClearChoice Lab Rx layout. Arch checkboxes aren't in the text layer, so arch type is inferred from Plan of Treatment text.

### Dropdown lists (`lists.json`)

`designers`, `centers`, and `tooth_shades` can be overridden from JSON. Sources, in priority order: local cache at `%APPDATA%\PatientAdminTool\lists.json` (refreshed from the OneDrive/SharePoint shortcut at `%OneDriveCommercial%\PatientAdminTool\lists.json` if present and valid), then the `lists.json` beside the app, then the hard-coded lists in `patient_core.py`. `apply_lists()` mutates the module-level lists **in place** (`target[:] = new`) because the GUI and `parse_rx_pdf` hold references to them — never rebind these names. Bump `version` in `lists.json` when editing it; it's shown in the window title.

Per-user settings (last designer) live in `%APPDATA%\PatientAdminTool\settings.json`; save failures are deliberately swallowed.
