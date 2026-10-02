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

The app is distributed as a PyInstaller exe; `core.app_dir()` resolves to the exe's folder when frozen, and the bundled `lists.json` is expected next to it. `lists.json` is gitignored (the designer and center lists are kept out of the repo), so a fresh clone has none and the lists in `patient_core.py` are placeholders.

## Architecture

Two modules, strict split:

- `patient_core.py` — all logic, no GUI imports. Unit tested by `test_patient_core.py`.
- `PatientAdminTool.py` — the Tk window only (`App` class). It collects form values into a plain dict `d` (keys: `name_id, center, designer, arch_type, tooth_shade, stl_only, split_file, cutback, ios_box, scan_date, rx_date, due_date, surgery_date`) and passes it to core functions. New logic belongs in core, not the GUI.

Workflow the code implements: Rx PDF → pre-filled form → CaseNotes.txt + patient folder on the Desktop (the Rx PDF is copied in beside CaseNotes.txt, original name, via `plan_rx_copy()`) → case files copied (never moved) into subfolders with standardized names.

### Key invariants

- **Naming mirrors a legacy Excel sheet.** `patient_from()` splits `"T. Est 1234-QWER"` exactly like the old Excel formula, and `build_casenotes()` mirrors its CONCATENATE output character-for-character (the `C7/C8/C11/C12` variable names are Excel cell refs). Don't "clean up" whitespace or blank lines in the output — downstream users rely on the exact text.
- **Arch types live in four groups**: `UPPER_ARCH`, `LOWER_ARCH`, `DOUBLE_ARCH`, `OTHER_ARCH` (e.g. `MODEL ONLY`). The group a type sits in, not its position, drives the upper/lower logic in CaseNotes and `guess_role` via `is_upper()` / `is_lower()`. Double and Other types count as both arches. `ARCH_TYPES` is the flattened dropdown list (upper, lower, double, other), rebuilt in place by `apply_lists()`. `arch_from_treatment()` and `folder_name()` still name `UAO4` / `LAO4` / `DAO4` / `MODEL ONLY` literally.
- **File roles** are defined once in `ROLES` (label, name template, destination subfolders). `STL_DIR` is a placeholder resolved to `"<uid> STL"`; `MAIN_DIR` (`""`) is the patient folder root. Some roles copy to two folders. `guess_role()` infers a role from filename tokens/extension, falling back on arch type; `None` means the user must choose.
- **`plan_file_copies()` is pure planning** — computes destinations, resolves collisions with `_02`, `_03`… suffixes (against disk and within the batch). Roles with no name template (screenshots, other) keep the original file name. `copy_files()` does the I/O. Keep the plan/execute split so the GUI can preview names live.
- **Rx PDF parsing** (`parse_rx_pdf`) is best-effort, using word x-positions (hard-coded column offsets like 110/120/140/300/360) for a specific ClearChoice Lab Rx layout. It reads every page, because a long Note pushes the lower form fields (tooth shade, scan type) onto page 2. The Note column (x ≥ 355) shares rows with the form labels, so `_rows()` sorts each row left to right and form values are read with an `xmax` of 300. Real Rx PDFs for checking the parser go in the gitignored `sample_rx/`; the unit tests use synthetic word positions. Arch checkboxes aren't in the text layer, so arch type is inferred from Plan of Treatment text.

### Dropdown lists (`lists.json`)

`designers`, `centers`, and the arch groups (`upper_arch`, `lower_arch`, `double_arch`, `other_arch`) can be overridden from JSON; a key that is missing, empty or not a list of strings keeps its built-in list. Tooth shades are hardcoded. The only source is the `lists.json` beside the app (`load_lists()`); if it is missing or unreadable the placeholder lists in `patient_core.py` stay in effect and the title shows "built-in lists". File → Reload Lists re-reads it. `apply_lists()` mutates the module-level lists **in place** (`target[:] = new`) because the GUI and `parse_rx_pdf` hold references to them — never rebind these names. Bump `version` in `lists.json` when editing it; it's shown in the window title.

Per-user settings (last designer) live in `%APPDATA%\PatientAdminTool\settings.json`; save failures are deliberately swallowed.
