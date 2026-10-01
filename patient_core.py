"""
patient_core.py
---------------
All non-GUI logic for the Patient Folder & Case Notes Creator:
  - reference data (dropdown lists)
  - CaseNotes text
  - Rx PDF parsing
  - file naming / routing / copying for case files

Keeping this separate from the GUI means it can be unit tested
(see test_patient_core.py) and reused by other tools later.
"""

import calendar
import filecmp
import json
import os
import sys
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path

try:
    import pdfplumber
    PDF_AVAILABLE = True
except Exception:
    PDF_AVAILABLE = False


# =============================================================================
# Reference data
# =============================================================================

# See JSON List
DESIGNERS = ['TEST DESIGNER']

ARCH_TYPES = ['UAO4 - Try-in', 'UAO4', 'Upper - MxOD', 'Upper - MxCD',
    'Double - MxCD-LAO4', 'Double - MxCD-LOD', 'Double - UOD-LAO4', 'Double - UAO4-LOD',
    'Double - MdCD-UAO4', 'Double - MdCD-UOD', 'MODEL ONLY', 'Double CD', 'Double OD',
    'DAO4 - Try-in', 'DAO4', 'Lower - MdCD', 'Lower - MdOD', 'LAO4 - Try-in', 'LAO4']


UPPER_ARCH = ARCH_TYPES[0:15]
LOWER_ARCH = ARCH_TYPES[4:19]

TOOTH_SHADES = ['A1', 'A2', 'A3', 'A3.5', 'A4', 'B1', 'B2', 'B3', 'B4', 'C1', 'C2',
    'C3', 'C4', 'D2', 'D3', 'D4', 'N/A', 'BL1', 'BL2', 'BL3', 'BL4']

SPLIT_OPTIONS = ['No', 'Upper', 'Lower', 'Double']
YESNO = ['Yes', 'No']
IOS_BOX = ['IOS', 'Box']

# See JSON list
CENTERS = ['TEST CENTER']

ID_RE = re.compile(r"[A-Za-z0-9]{4}-[A-Za-z0-9]{4}")
DESKTOP = Path.home() / "Desktop"

VIEWER_DIR = "3D Viewer"
SCREENSHOT_DIR = "Design Screenshots"


# =============================================================================
# Dates
# =============================================================================
_DATE_FORMATS = ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m.%d.%Y", "%m.%d.%y")


def parse_date(value):
    """Return a date for mm/dd/yyyy-style input (or a date object). None if blank or invalid."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(str(value).strip(), f).date()
        except ValueError:
            continue
    return None


def fmt_date(value, sep="/"):
    """m/dd/yyyy for notes, or M.D.YYYY for the folder name. Unparseable text is passed through."""
    if value in (None, ""):
        return ""
    d = parse_date(value)
    if d is None:
        return str(value)
    if sep == ".":
        return f"{d.month}.{d.day}.{d.year}"
    return f"{d.month}/{d.day:02d}/{d.year}"


def month_weeks(year, month):
    """Day numbers of a month as Sunday-first weeks, for the date picker. 0 = outside the month."""
    return calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)


def shift_month(year, month, delta):
    """(year, month) moved forward or back by delta months."""
    y, m = divmod(year * 12 + month - 1 + delta, 12)
    return y, m + 1


# =============================================================================
# Patient identity (the pieces every name is built from)
# =============================================================================
@dataclass(frozen=True)
class Patient:
    init2: str    # "R."
    name3: str    # "YEL"
    uid: str      # "B658-CGAF"
    first1: str   # "R"
    center: str   # "Chicago"


def patient_from(name_id, center):
    """Split 'R. Yel B658-CGAF' the same way the Excel formula does."""
    clean = name_id.replace(")", "").replace(" ", "")
    clean_p = clean.replace("(", "")
    return Patient(
        init2=clean[:2].upper(),
        name3=clean[2:5].upper(),
        uid=clean_p[-9:].upper(),
        first1=clean_p[:1].upper(),
        center=center,
    )


def is_upper(arch_type):
    return arch_type in UPPER_ARCH


def is_lower(arch_type):
    return arch_type in LOWER_ARCH


def stl_folder_name(uid):
    return f"{uid} STL"


def folder_name(d):
    """Patient folder name, e.g. '6.11.2026 R. YEL B658-CGAF Chicago'."""
    p = patient_from(d['name_id'], d['center'])
    model_only = " MODEL ONLY" if d.get('arch_type') == "MODEL ONLY" else ""
    return f"{fmt_date(d.get('rx_date'), '.')} {p.init2} {p.name3} {p.uid} {p.center}{model_only}"


# =============================================================================
# CaseNotes text (mirrors the Excel CONCATENATE exactly)
# =============================================================================
def build_casenotes(d, today=None):
    p = patient_from(d['name_id'], d['center'])
    uid, first1, name3, init2, C7 = p.uid, p.first1, p.name3, p.init2, p.center
    C8, C11, C12 = d['arch_type'], d['split_file'], d['cutback']
    up, lo = is_upper(C8), is_lower(C8)
    split = "" if C11 == "No" else f"{C11} Split File"
    today = today or date.today()

    out = f"Center: {C7}\n"
    out += f"Patient Name: {init2} {name3}\n"
    out += f"Unique ID: {uid}\n"
    out += f"STL Only: {d['stl_only']}\n"
    out += f"Cutback: {C12}\n"
    out += f"Arch Type: {C8} {split}\n"
    out += f"Tooth Shade: {d['tooth_shade']}\n"
    out += f"Due by Date: {fmt_date(d['due_date'])}\n"
    out += f"Surgery: {fmt_date(d['surgery_date'])}\n"
    out += f"Rx Date: {fmt_date(d['rx_date'])}\n"
    out += f"Scan Date: {fmt_date(d['scan_date'])}\n"
    out += f"IOS or Box? {d['ios_box']}\n"
    out += f"Designer: {d['designer']}\n"
    out += f"Awaiting Approval Date: {fmt_date(today)}\n"
    out += "Revisions: 0\n\n_______________________________________\n"

    if up:
        s = f"MAX STL NAME\n{uid}_MX_{first1}_{name3}_{C7}\n"
        if C11 in ("Upper", "Double"):
            s += f"{uid}_MX_BASE_{first1}_{name3}_{C7}\n{uid}_MX_TEETH_{first1}_{name3}_{C7}"
        s += f"\nMAX DCM NAME\n{uid}_MX_{first1}_{name3}"
        out += s
    out += "\n\n"
    if lo:
        s = f"MAND STL NAME\n{uid}_MD_{first1}_{name3}_{C7}\n"
        if C11 in ("Lower", "Double"):
            s += f"{uid}_MD_BASE_{first1}_{name3}_{C7}\n{uid}_MD_TEETH_{first1}_{name3}_{C7}"
        s += f"\nMAND DCM NAME\n{uid}_MD_{first1}_{name3}"
        out += s
    out += "\n\n"
    out += f"BITE STL NAME\n{uid}_BITE_{first1}_{name3}_{C7}"
    out += "\n\n"
    out += (f"MODELS\n{uid}_MDL_MX_{first1}_{name3}_{C7}\n{uid}_MDL_MD_{first1}_{name3}_{C7}\n"
            f"{uid}_WRK_MX_{first1}_{name3}\n{uid}_WRK_MD_{first1}_{name3}")
    out += "\n\n"
    out += (f"MAX CUTBACK STL NAME\n{uid}_MX_CUTBACK_{first1}_{name3}_{C7}"
            if (C12 == "Yes" and up) else "")
    out += "\n"
    out += (f"MAND CUTBACK STL NAME\n{uid}_MD_CUTBACK_{first1}_{name3}_{C7}"
            if (C12 == "Yes" and lo) else "")
    out += "\n_______________________________________\n"
    out += f"Patient Folder Name\n{folder_name(d)}\n"
    out += f"\nSTL Folder Name\n{stl_folder_name(uid)}\n"
    out += f"\nDental System Order ID Input\n{uid}_{first1}_{name3}_{C7}"
    return out


# =============================================================================
# Rx PDF parsing (best-effort pre-fill; everything stays editable in the GUI)
# =============================================================================
def _rows(page, tol=3):
    """Group a page's words into visual rows by their vertical position."""
    words = sorted(page.extract_words(), key=lambda w: (round(w['top']), w['x0']))
    rows, cur, cur_top = [], [], None
    for w in words:
        if cur_top is None or abs(w['top'] - cur_top) <= tol:
            cur.append(w)
            cur_top = w['top'] if cur_top is None else cur_top
        else:
            rows.append(cur)
            cur, cur_top = [w], w['top']
    if cur:
        rows.append(cur)
    return rows


def _right_of(row, x, xmax=10_000):
    return " ".join(w['text'] for w in row if x < w['x0'] < xmax).strip()


def arch_from_treatment(plan_of_treatment, upper_arch_value="", lower_arch_value=""):
    """Default arch type from the Plan of Treatment text.

    The PDF's arch checkboxes are not in th e text layer, so we infer the side:
    'Lower Zirconia Arch Replacement' -> LAO4, upper -> UAO4, both -> DAO4.
    """
    pot = (plan_of_treatment or "").lower()
    up = bool(upper_arch_value) or "upper" in pot
    lo = bool(lower_arch_value) or "lower" in pot
    if up and lo:
        return "DAO4"
    if lo:
        return "LAO4"
    if up:
        return "UAO4"
    return None


def parse_rx_pdf(path):
    """Return a dict of best-effort fields from a ClearChoice Lab Rx PDF."""
    out = {}
    if not PDF_AVAILABLE:
        return out
    with pdfplumber.open(path) as pdf:
        p1 = pdf.pages[0]
        full1 = p1.extract_text() or ""
        pot_parts, upper_at, lower_at = [], "", ""
        for row in _rows(p1):
            low = " ".join(w['text'] for w in row).lower()
            if 'name_id' not in out:
                rt = _right_of(row, 110)
                m = ID_RE.search(rt)
                if m and not low.startswith('unique'):
                    out['name_id'] = rt[:m.end()].strip()
            if 'due' in low and 'date:' in low:
                m = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", _right_of(row, 360))
                if m:
                    out['due_date'] = m.group(0)
            if low.startswith('surgical arch'):
                out['stl_only'] = 'Yes' if 'stl only' in _right_of(row, 120).lower() else 'No'
            if low.startswith('tooth shade:'):
                v = _right_of(row, 120)
                if v:
                    out['tooth_shade'] = v.split()[0]
            if low.startswith('plan of') or low.startswith('treatment:'):
                pot_parts.append(_right_of(row, 110, 300))
            if low.startswith('upper arch type'):
                upper_at = _right_of(row, 140)
            if low.startswith('lower arch type'):
                lower_at = _right_of(row, 140)
        m = ID_RE.search(full1)
        if m:
            out['unique_id'] = m.group(0).upper()
        pot = " ".join(p for p in pot_parts if p)
        if pot:
            out['plan_of_treatment'] = pot
        arch = arch_from_treatment(pot, upper_at, lower_at)
        if arch:
            out['arch_type'] = arch
        if len(pdf.pages) > 1:
            t2 = (pdf.pages[1].extract_text() or "").lower()
            if 'intraoral' in t2:
                out['ios_box'] = 'IOS'
            elif 'desktop' in t2:
                out['ios_box'] = 'Box'
    for c in sorted(CENTERS, key=len, reverse=True):
        base = c.split(" - ")[-1]
        if re.search(rf"\b{re.escape(base)}\b", full1, re.IGNORECASE):
            out['center'] = c
            break
    return out


# =============================================================================
# Case files: roles, naming, routing
# =============================================================================
STL_DIR = "__STL__"   # placeholder, resolved to '<uid> STL'
MAIN_DIR = ""         # the patient folder itself

# key: (label shown in GUI, name template or None to keep original name, destination)
ROLES = {
    "MX":         ("MAX STL",              "{uid}_MX_{f}_{n}_{c}",          (STL_DIR,)),
    "MX_BASE":    ("MAX BASE STL",         "{uid}_MX_BASE_{f}_{n}_{c}",     (STL_DIR,)),
    "MX_TEETH":   ("MAX TEETH STL",        "{uid}_MX_TEETH_{f}_{n}_{c}",    (STL_DIR,)),
    "MX_CUTBACK": ("MAX CUTBACK STL",      "{uid}_MX_CUTBACK_{f}_{n}_{c}",  (STL_DIR,)),
    "MX_DCM":     ("MAX DCM",              "{uid}_MX_{f}_{n}",              (VIEWER_DIR,)),
    "MD":         ("MAND STL",             "{uid}_MD_{f}_{n}_{c}",          (STL_DIR,)),
    "MD_BASE":    ("MAND BASE STL",        "{uid}_MD_BASE_{f}_{n}_{c}",     (STL_DIR,)),
    "MD_TEETH":   ("MAND TEETH STL",       "{uid}_MD_TEETH_{f}_{n}_{c}",    (STL_DIR,)),
    "MD_CUTBACK": ("MAND CUTBACK STL",     "{uid}_MD_CUTBACK_{f}_{n}_{c}",  (STL_DIR,)),
    "MD_DCM":     ("MAND DCM",             "{uid}_MD_{f}_{n}",              (VIEWER_DIR,)),
    "BITE":       ("BITE STL",             "{uid}_BITE_{f}_{n}_{c}",        (STL_DIR,)),
    "MDL_MX":     ("MAX MODEL",            "{uid}_MDL_MX_{f}_{n}_{c}",      (STL_DIR, VIEWER_DIR)),
    "MDL_MD":     ("MAND MODEL",           "{uid}_MDL_MD_{f}_{n}_{c}",      (STL_DIR, VIEWER_DIR)),
    "WRK_MX":     ("MAX WORKING MODEL",    "{uid}_WRK_MX_{f}_{n}",          (STL_DIR, VIEWER_DIR)),
    "WRK_MD":     ("MAND WORKING MODEL",   "{uid}_WRK_MD_{f}_{n}",          (STL_DIR, VIEWER_DIR)),
    "SCREENSHOT": ("Design Screenshot",    "{uid}_{f}_{n}_Screenshot_{num:02d}", (SCREENSHOT_DIR, )),
    "KEEP":       ("Other (keep name)",    None,                            (MAIN_DIR, )),
}
ROLE_LABELS = [v[0] for v in ROLES.values()]
LABEL_TO_ROLE = {v[0]: k for k, v in ROLES.items()}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*]')


def safe_name(name):
    """Remove characters Windows does not allow in file or folder names."""
    return _INVALID_CHARS.sub("", name).strip()


def guess_role(path, arch_type=""):
    """Best guess at a file's role from its name and extension. None means 'ask the user'."""
    p = Path(path)
    ext = p.suffix.lower()
    stem = p.stem.lower()
    tokens = set(t for t in re.split(r"[^a-z0-9]+", stem) if t)

    if ext in IMAGE_EXTS:
        return "SCREENSHOT"
    if "bite" in tokens or "bite" in stem:
        return "BITE"

    upper = bool(tokens & {"mx", "max", "upper", "maxilla", "maxillary"}) or "maxill" in stem or "upper" in stem
    lower = bool(tokens & {"md", "mand", "lower", "mandible", "mandibular"}) or "mandib" in stem or "lower" in stem
    if upper == lower:  # neither or both named: fall back on the arch type
        up_arch, lo_arch = is_upper(arch_type), is_lower(arch_type)
        upper, lower = up_arch and not lo_arch, lo_arch and not up_arch
    if not (upper or lower):
        return None
    side = "MX" if upper else "MD"

    if ext == ".dcm":
        return f"{side}_DCM"
    if "cutback" in stem:
        return f"{side}_CUTBACK"
    if "base" in tokens:
        return f"{side}_BASE"
    if "teeth" in tokens:
        return f"{side}_TEETH"
    if tokens & {"wrk", "working", "work"}:
        return f"WRK_{side}"
    if tokens & {"mdl", "model"}:
        return f"MDL_{side}"
    if ext in {".stl", ".ply", ".obj"}:
        return side
    return None


def _dest_dirs(role, uid):
    return [stl_folder_name(uid) if sub == STL_DIR else sub for sub in ROLES[role][2]]


def plan_file_copies(items, d, main_folder=None):
    """Work out where each case file will be copied and what it will be called.

    items: list of (source_path, role_key or None)
    Returns a list the same length as items: a destination Path, or None for
    files with no role yet. Nothing is written. Name collisions (with files
    already on disk or earlier in this batch) get _02, _03, ... appended.
    Screenshots are numbered after any that already exist.
    """
    p = patient_from(d['name_id'], d['center'])
    root = Path(main_folder) if main_folder else Path()
    taken = set()
    shot_num = 0
    results = []

    def free(path):
        return path not in taken and not (main_folder and path.exists())

    for src, role in items:
        if not role:
            results.append(None)
            continue
        src = Path(src)
        ext = src.suffix.lower()
        template = ROLES[role][1]
        fields = dict(uid=p.uid, f=p.first1, n=p.name3, c=p.center)

        folders = [root / d for d in _dest_dirs(role, p.uid)]

        def all_free(name):
            return all(free(f / name) for f in folders)

        if role == "SCREENSHOT":
            while True:
                shot_num += 1
                name = safe_name(template.format(num=shot_num, **fields)) + ext
                if all_free(name):
                    break
        else:
            base = src.stem if template is None else safe_name(template.format(**fields))
            name, n = f"{base}{ext}", 2
            while not all_free(name):
                name, n = f"{base}_{n:02d}{ext}", n + 1
        dests = [f / name for f in folders]
        taken.update(dests)
        results.append(dests)
    return results


def plan_rx_copy(pdf, main_folder):
    """Where the Rx PDF will be copied: the patient folder, beside CaseNotes.txt, original name.

    Returns a list of destinations like plan_file_copies does. It is empty when
    that exact file is already there (Create was clicked again for the same
    case); a different file with the same name gets _02, _03, ... instead.
    """
    src, main = Path(pdf), Path(main_folder)
    dest, n = main / src.name, 2
    while dest.exists():
        if filecmp.cmp(src, dest, shallow=False):
            return []
        dest, n = main / f"{src.stem}_{n:02d}{src.suffix}", n + 1
    return [dest]


# =============================================================================
# Settings (remembered between runs, per Windows user)
# =============================================================================
def settings_path():
    """%APPDATA%\\PatientAdminTool\\settings.json on Windows, ~/.patientfoldercreator elsewhere."""
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) / "PatientAdminTool" if appdata else Path.home() / ".patientadmintool"
    return base / "settings.json"


def load_settings(path=None):
    """Return saved settings, or {} if the file is missing or unreadable."""
    path = Path(path) if path else settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data, path=None):
    """Write settings. Failures are ignored: remembering a default is never worth an error."""
    path = Path(path) if path else settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


# =============================================================================
# Dropdown lists (lists.json beside the app)
# =============================================================================
LISTS_FILE = "lists.json"

# Only these lists are editable from the JSON. Arch types stay in code because the
# upper/lower CaseNotes logic depends on their exact order.
_EDITABLE = {"designers": DESIGNERS, "centers": CENTERS, "tooth_shades": TOOTH_SHADES}


def app_dir():
    """Folder the app runs from: next to the .exe when frozen, else this file's folder."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def default_lists_path():
    return app_dir() / LISTS_FILE


def apply_lists(paths):
    """Load the first readable lists file and update the lists in place.

    In-place updates (target[:] = new) matter: the GUI and parse_rx_pdf already
    hold references to these list objects.
    Returns (path used, version), or (None, None) if the built-in lists are in effect.
    """
    for path in paths:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for key, target in _EDITABLE.items():
            new = data.get(key)
            if isinstance(new, list) and new and all(isinstance(x, str) for x in new):
                target[:] = new
        return Path(path), str(data.get("version", "unknown"))
    return None, None


def load_lists():
    """Apply the lists.json that sits beside the app. (None, None) if it is missing or unreadable."""
    return apply_lists([default_lists_path()])


# =============================================================================
# Writing to disk
# =============================================================================
def create_folder_structure(main_folder, uid, notes=None):
    """Create the patient folder and its subfolders. Optionally write CaseNotes.txt."""
    main = Path(main_folder)
    main.mkdir(parents=True, exist_ok=True)
    for sub in (VIEWER_DIR, SCREENSHOT_DIR, stl_folder_name(uid)):
        (main / sub).mkdir(exist_ok=True)
    if notes is not None:
        (main / "CaseNotes.txt").write_text(notes, encoding="utf-8")
    return main


def copy_files(pairs):
    done = []
    for src, dests in pairs:
        for dest in dests:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            done.append(dest)
    return done
