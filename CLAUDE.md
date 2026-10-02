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

Build the exe (no spec file is kept; `build/`, `dist/` and `*.spec` are gitignored), then copy `lists.json` into `dist/`:

```
pyinstaller --noconfirm --clean --onefile --windowed --name PatientAdminTool --collect-all tkinterdnd2 PatientAdminTool.py
```

The app is distributed as a PyInstaller exe; `core.app_dir()` resolves to the exe's folder when frozen, and the bundled `lists.json` is expected next to it. `lists.json` is gitignored (the designer and center lists are kept out of the repo), so a fresh clone has none and the lists in `patient_core.py` are placeholders.

## Architecture

Two modules, strict split:

- `patient_core.py` — all logic, no GUI imports. Unit tested by `test_patient_core.py`.
- `PatientAdminTool.py` — the Tk window only (`App` class). It collects form values into a plain dict `d` (keys: `name_id, center, designer, arch_type, tooth_shade, stl_only, split_file, cutback, ios_box, scan_date, rx_date, due_date, surgery_date, revisions`) and passes it to core functions. New logic belongs in core, not the GUI.

Workflow the code implements, in two steps:

1. **Start** — Rx PDF → pre-filled form → "Create Initial Folder + CaseNotes" (`create_initial_folder()`): a working folder `T. EST 1234-QWER Chicago` on the Desktop (`base_folder_name()`, no date) holding fresh CaseNotes and the Rx PDF, which is **moved** in. The designer saves models and screenshots there and edits the CaseNotes by hand.
2. **Finish** — the working folder's CaseNotes file is dropped in → form filled by `parse_casenotes()` (Revisions included), and `working_folder_files()` lists the folder's Rx and case files → "Create Folder + Notes + Files": the dated patient folder (`folder_name()`), case files and Rx copied (never moved) into subfolders with standardized names, plus a new CaseNotes holding the case information only.

Dropping an Rx PDF and going straight to "Create Folder + Notes + Files" still does everything at once, building the (case-information-only) CaseNotes from the form.

### Key invariants

- **Naming mirrors a legacy Excel sheet.** `patient_from()` splits `"T. Est 1234-QWER"` exactly like the old Excel formula, and `build_casenotes()` mirrors its CONCATENATE output character-for-character (the `C7/C8/C11/C12` variable names are Excel cell refs). Don't "clean up" whitespace or blank lines in the output — downstream users rely on the exact text.
- **CaseNotes and the Rx PDF are named per patient**: `<uid>_<F>_<NAM>_CaseNotes.txt` (`casenotes_name()`) and `<uid>_<F>_<NAM>_Rx.pdf` (`plan_rx_copy()`), both in the patient folder root. In the working folder the same names get `WORKING_PREFIX` (`!`) in front (`working=True`), so Explorer's name sort keeps them above whatever the designer saves there; the finished folder's copies have no prefix. Folders made by older versions hold a plain `CaseNotes.txt` and the Rx under its original name; these are never renamed or deleted.
- **Two CaseNotes shapes.** The working folder gets the full text (`build_casenotes()`: case information, a ruled line, then the file-naming examples the designer works from). The finished patient folder gets the case information only (`casenotes_header()`: everything above the first ruled line, ending at `Revisions:`). The preview always shows the full text.
- **A loaded CaseNotes file is never rebuilt.** When the form was filled from a CaseNotes file, Create cuts the finished folder's notes from that file (`write_final_casenotes()`) instead of calling `build_casenotes()`, so hand edits to the header survive. Case Information changed on the form after loading is written in line by line (`apply_case_info()`): only header lines whose value differs from the form are rewritten, in `build_casenotes()` wording; `Awaiting Approval Date` and any lines the designer added are left alone. The same changes are written back to the loaded file so the working copy stays current (its naming examples below the ruled line are not regenerated). Before writing, the GUI lists the differences (`casenotes_changes()`, compared against the file as it is on disk at that moment) and asks to continue. Files are read with `read_casenotes()` (UTF-8, else cp1252 for old Excel-sheet files) and written back in the same encoding with their line endings kept. Loading an Rx PDF afterwards goes back to building the notes.
- **What moves and what copies.** Only the Rx PDF going into the working folder (step 1) is moved. Everything else is copied or written new; the working folder is left complete after step 2. "Create Initial" asks before replacing CaseNotes that already exist in the working folder, since they may hold the designer's edits.
- **`working_folder_files()` only searches a folder named for the patient** (folder name contains the unique ID), so CaseNotes dropped from the Desktop or Downloads don't pull in their neighbours. It recurses, but skips the three subfolders a finished patient folder has.
- **`parse_casenotes()` is the inverse of the `build_casenotes()` header.** If a header line is added or reworded in one, update the other; `ParseCaseNotesTests.test_round_trip` checks they agree.
- **Arch types live in four groups**: `UPPER_ARCH`, `LOWER_ARCH`, `DOUBLE_ARCH`, `OTHER_ARCH` (e.g. `MODEL ONLY`). The group a type sits in, not its position, drives the upper/lower logic in CaseNotes and `guess_role` via `is_upper()` / `is_lower()`. Double and Other types count as both arches. `ARCH_TYPES` is the flattened dropdown list (upper, lower, double, other), rebuilt in place by `apply_lists()`. `arch_from_treatment()` and `folder_name()` still name `UAO4` / `LAO4` / `DAO4` / `MODEL ONLY` literally.
- **File roles** are defined once in `ROLES` (label, name template, destination subfolders). `STL_DIR` is a placeholder resolved to `"<uid> STL"`; `MAIN_DIR` (`""`) is the patient folder root. Some roles copy to two folders. `guess_role()` infers a role from filename tokens/extension, falling back on arch type; `None` means the user must choose. Name tokens (cutback, base, teeth, working, model) are checked before the extension, so a `.dcm` working model is `WRK_*`; only a `.dcm` with none of those tokens gets the plain `*_DCM` role.
- **Only `.stl` files belong in the STL folder.** `non_stl_for_stl_folder()` lists the source files whose role routes to `STL_DIR` but whose extension is not `.stl` (so `.ply`, `.obj` and `.dcm` count). At "Create Folder + Notes + Files" the GUI shows them in a warning and asks to continue, before anything is written; it is a warning, not a block.
- **Zip files keep their name.** `guess_role()` gives any `.zip` the `KEEP` role (checked before the name tokens), so it lands in the patient folder root unrenamed. Since the name is then the only sign of whose case it is, `zips_not_for_patient()` lists the zips whose name has neither the unique ID (separators and case ignored), nor its first or last four characters (standing alone, not inside a longer number or word), nor a word starting with the patient name (`EST` or `TEST`). The GUI warns about them right after the STL folder warning, the same way: a warning, not a block.
- **`plan_file_copies()` is pure planning** — computes destinations, resolves collisions with `_02`, `_03`… suffixes (against disk and within the batch). Roles with no name template (screenshots, other) keep the original file name. `copy_files()` does the I/O. Keep the plan/execute split so the GUI can preview names live.
- **Rx PDF parsing** (`parse_rx_pdf`) is best-effort, using word x-positions (hard-coded column offsets like 110/120/140/300/360) for one specific Lab Rx layout. It reads every page, because a long Note pushes the lower form fields (tooth shade, scan type) onto page 2. The Note column (x ≥ 355) shares rows with the form labels, so `_rows()` sorts each row left to right and form values are read with an `xmax` of 300. Real Rx PDFs for checking the parser go in the gitignored `sample_rx/`; the unit tests use synthetic word positions. Arch checkboxes aren't in the text layer, so arch type is inferred from Plan of Treatment text.

### Dropdown lists (`lists.json`)

`designers`, `centers`, and the arch groups (`upper_arch`, `lower_arch`, `double_arch`, `other_arch`) can be overridden from JSON; a key that is missing, empty or not a list of strings keeps its built-in list. Tooth shades are hardcoded. The only source is the `lists.json` beside the app (`load_lists()`); if it is missing or unreadable the placeholder lists in `patient_core.py` stay in effect and the title shows "built-in lists". File → Reload Lists re-reads it. `apply_lists()` mutates the module-level lists **in place** (`target[:] = new`) because the GUI and `parse_rx_pdf` hold references to them — never rebind these names. Bump `version` in `lists.json` when editing it; it's shown in the window title.

Per-user settings (last designer) live in `%APPDATA%\PatientAdminTool\settings.json`; save failures are deliberately swallowed.
