"""
Patient Folder & Case Notes Creator
-----------------------------------
1. Drop (or browse for) the Rx PDF. It fills in what it can.
2. Pick the rest from the dropdowns and fill in the dates.
3. Drop case files (STLs, DCMs, screenshots, 3D viewer). Each gets a role,
   which decides its new name and subfolder. Check the "New name" column.
4. Click "Create Folder + Notes + Files". Files are copied, never moved.
   The Rx PDF is copied into the patient folder next to CaseNotes.txt.

All logic lives in patient_core.py; this file is only the window.

Optional packages (the app still runs without them, with fewer features):
  pip install pdfplumber      -> reads the Rx PDF
  pip install tkinterdnd2     -> drag-and-drop (otherwise click to browse)
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date
from pathlib import Path

import patient_core as core

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False

DATE_FIELDS = ("scan_date", "rx_date", "due_date", "surgery_date")
UNASSIGNED = "(choose a role)"


class DatePicker(tk.Toplevel):
    """Small month calendar that pops up under a date field. Calls on_pick(date) and closes."""

    def __init__(self, parent, anchor, initial, on_pick):
        super().__init__(parent)
        self.title("Pick a date")
        self.resizable(False, False)
        self.transient(parent)
        self.on_pick = on_pick
        self.selected = initial
        start = initial or date.today()
        self.year, self.month = start.year, start.month

        head = tk.Frame(self)
        head.pack(fill="x", padx=6, pady=(6, 2))
        tk.Button(head, text="◀", width=3, command=lambda: self._shift(-1)).pack(side="left")
        tk.Button(head, text="▶", width=3, command=lambda: self._shift(1)).pack(side="right")
        self.month_label = tk.Label(head, font=("Arial", 10, "bold"))
        self.month_label.pack(side="left", expand=True)

        self.grid_frame = tk.Frame(self)
        self.grid_frame.pack(padx=6)
        tk.Button(self, text="Today", font=("Arial", 8),
                  command=lambda: self._pick(date.today())).pack(pady=6)
        self._draw()

        self.bind("<Escape>", lambda e: self.destroy())
        self.geometry(f"+{anchor.winfo_rootx()}+{anchor.winfo_rooty() + anchor.winfo_height()}")
        self.grab_set()
        self.focus_set()

    def _shift(self, delta):
        self.year, self.month = core.shift_month(self.year, self.month, delta)
        self._draw()

    def _draw(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.month_label.config(text=date(self.year, self.month, 1).strftime("%B %Y"))
        for c, name in enumerate(("Su", "Mo", "Tu", "We", "Th", "Fr", "Sa")):
            tk.Label(self.grid_frame, text=name, font=("Arial", 8), fg="#555555").grid(row=0, column=c)
        for r, week in enumerate(core.month_weeks(self.year, self.month), start=1):
            for c, day in enumerate(week):
                if not day:
                    continue
                d = date(self.year, self.month, day)
                b = tk.Button(self.grid_frame, text=str(day), width=3, relief="flat",
                              command=lambda d=d: self._pick(d))
                if d == self.selected:
                    b.config(bg="#1565C0", fg="white")
                elif d == date.today():
                    b.config(bg="#BBDEFB")
                b.grid(row=r, column=c, padx=1, pady=1)

    def _pick(self, d):
        self.destroy()
        self.on_pick(d)


class App:
    def __init__(self, root):
        self.root = root
        root.title("Patient Admin Tool")
        root.geometry("1150x900")
        root.minsize(1000, 800)

        self.vars = {}
        self.combos = {}
        self.files = []  # each: {"src": Path, "role": role key or None}
        self.rx_pdf = None  # the loaded Rx PDF, copied into the patient folder on Create
        self.settings = core.load_settings()
        # Load lists.json before building the form so the dropdowns start current.
        self.lists_source, self.lists_version = core.load_lists()
        self._update_title()

        self._build_menu()
        self._build_pdf_zone()
        body = tk.Frame(root)
        body.pack(fill="both", expand=True, padx=10, pady=4)
        self._build_form(body)
        self._build_preview(body)
        self._build_files_panel()
        self._build_action_bar()
        self.update_preview()

    # ------------------------------------------------------------------ layout
    def _build_menu(self):
        bar = tk.Menu(self.root)
        m = tk.Menu(bar, tearoff=False)
        m.add_command(label="New Case", command=self.new_case)
        m.add_command(label="Open Rx PDF...", command=self.browse_pdf)
        m.add_command(label="Add Case Files...", command=self.browse_files)
        m.add_separator()
        m.add_command(label="Save Case Notes As...", command=self.save_notes_only)
        m.add_separator()
        m.add_command(label="Reload Lists", command=self.reload_lists)
        m.add_separator()
        m.add_command(label="Exit", command=self.root.destroy)
        bar.add_cascade(label="File", menu=m)
        self.root.config(menu=bar)

    def _build_pdf_zone(self):
        self.pdf_zone = tk.Label(
            self.root, text=self._pdf_zone_text(), relief="ridge", bd=2, height=2,
            bg="#EEF4FF", fg="#1A3C6E", font=("Arial", 11, "bold"), cursor="hand2")
        self.pdf_zone.pack(fill="x", padx=10, pady=(10, 4))
        self.pdf_zone.bind("<Button-1>", lambda e: self.browse_pdf())
        if DND_AVAILABLE:
            self.pdf_zone.drop_target_register(DND_FILES)
            self.pdf_zone.dnd_bind("<<Drop>>", self.on_pdf_drop)

    def _build_form(self, parent):
        form = tk.LabelFrame(parent, text="Case Information", font=("Arial", 10, "bold"),
                             padx=10, pady=6)
        form.pack(side="left", fill="y")

        def label(r, text):
            tk.Label(form, text=text, font=("Arial", 9)).grid(row=r, column=0, sticky="w", pady=3)

        def combo(r, text, key, values):
            label(r, text)
            v = tk.StringVar()
            cb = ttk.Combobox(form, textvariable=v, values=values, width=26)
            cb.grid(row=r, column=1, sticky="w", padx=8, pady=3)
            cb.bind("<<ComboboxSelected>>", lambda e: self.update_preview())
            cb.bind("<KeyRelease>", lambda e: self.update_preview())
            self.vars[key] = v
            self.combos[key] = cb

        def entry(r, text, key):
            label(r, text)
            v = tk.StringVar()
            e = tk.Entry(form, textvariable=v, width=29)
            e.grid(row=r, column=1, sticky="w", padx=8, pady=3)
            e.bind("<KeyRelease>", lambda ev: self.update_preview())
            self.vars[key] = v
            return e

        def date_entry(r, text, key):
            e = entry(r, text, key)
            e.bind("<Double-Button-1>", lambda ev: self._pick_date(key, e))
            tk.Button(form, text="📅", font=("Segoe UI Emoji", 8),
                      command=lambda: self._pick_date(key, e)).grid(row=r, column=2, sticky="w")

        entry(0, "Name & ID:", "name_id")
        combo(1, "Center:", "center", core.CENTERS)
        combo(2, "Designer:", "designer", core.DESIGNERS)
        combo(3, "Arch Type:", "arch_type", core.ARCH_TYPES)
        combo(4, "Tooth Shade:", "tooth_shade", core.TOOTH_SHADES)
        combo(5, "STL Only?:", "stl_only", core.YESNO)
        combo(6, "Split File?:", "split_file", core.SPLIT_OPTIONS)
        combo(7, "Cutback?:", "cutback", core.YESNO)
        combo(8, "IOS or Box?:", "ios_box", core.IOS_BOX)
        date_entry(9, "Scan Date (mm/dd/yyyy):", "scan_date")
        date_entry(10, "Rx Date (mm/dd/yyyy):", "rx_date")
        date_entry(11, "Due by Date (mm/dd/yyyy):", "due_date")
        date_entry(12, "Surgery Date (mm/dd/yyyy):", "surgery_date")

        tk.Button(form, text="Today", font=("Arial", 8),
                  command=lambda: self._set_today("scan_date")).grid(row=9, column=3, sticky="w", padx=(4, 0))
        tk.Button(form, text="Today", font=("Arial", 8),
                  command=lambda: self._set_today("rx_date")).grid(row=10, column=3, sticky="w", padx=(4, 0))

        self.folder_label = tk.Label(form, text="", font=("Consolas", 9), fg="#1565C0",
                                     wraplength=330, justify="left")
        self.folder_label.grid(row=13, column=0, columnspan=4, sticky="w", pady=(8, 0))

        self._set_defaults()

    def _build_preview(self, parent):
        right = tk.LabelFrame(parent, text="CaseNotes.txt Preview",
                              font=("Arial", 10, "bold"), padx=6, pady=6)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.preview = tk.Text(right, wrap="none", font=("Consolas", 9), height=20)
        ys = tk.Scrollbar(right, command=self.preview.yview)
        self.preview.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        self.preview.pack(side="left", fill="both", expand=True)

    def _build_files_panel(self):
        frame = tk.LabelFrame(self.root, text="Case Files (STL, DCM, screenshots, 3D viewer)",
                              font=("Arial", 10, "bold"), padx=8, pady=6)
        frame.pack(fill="both", padx=10, pady=4)

        self.file_zone = tk.Label(
            frame, text=self._file_zone_text(), relief="ridge", bd=2, height=2,
            bg="#F1F8E9", fg="#33691E", font=("Arial", 10, "bold"), cursor="hand2")
        self.file_zone.pack(fill="x", pady=(0, 6))
        self.file_zone.bind("<Button-1>", lambda e: self.browse_files())
        if DND_AVAILABLE:
            self.file_zone.drop_target_register(DND_FILES)
            self.file_zone.dnd_bind("<<Drop>>", self.on_files_drop)

        table = tk.Frame(frame)
        table.pack(fill="both", expand=True)
        cols = ("original", "role", "new_name")
        self.tree = ttk.Treeview(table, columns=cols, show="headings", height=7,
                                 selectmode="extended")
        for col, text, width in (("original", "Original file", 260),
                                 ("role", "Role", 170),
                                 ("new_name", "New name (subfolder\\file)", 560)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w")
        self.tree.tag_configure("unassigned", foreground="#C62828")
        ys = tk.Scrollbar(table, command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_file_select)

        controls = tk.Frame(frame)
        controls.pack(fill="x", pady=(6, 0))
        tk.Label(controls, text="Role for selected file(s):", font=("Arial", 9)).pack(side="left")
        self.role_var = tk.StringVar()
        role_cb = ttk.Combobox(controls, textvariable=self.role_var, values=core.ROLE_LABELS,
                               state="readonly", width=24)
        role_cb.pack(side="left", padx=6)
        role_cb.bind("<<ComboboxSelected>>", self.apply_role)
        tk.Button(controls, text="Remove Selected", command=self.remove_selected).pack(side="left", padx=4)
        tk.Button(controls, text="Clear All", command=self.clear_files).pack(side="left", padx=4)

    def _build_action_bar(self):
        bar = tk.Frame(self.root)
        bar.pack(fill="x", padx=10, pady=(4, 10))
        tk.Button(bar, text="Create Folder + Notes + Files", command=self.create_all,
                  bg="#4CAF50", fg="white", font=("Arial", 11, "bold"),
                  padx=14, pady=6).pack(side="right", padx=4)
        tk.Button(bar, text="Save Case Notes Only (.txt)", command=self.save_notes_only,
                  bg="#2196F3", fg="white", font=("Arial", 10, "bold"),
                  padx=10, pady=6).pack(side="right", padx=4)
        tk.Button(bar, text="New Case", command=self.new_case,
                  font=("Arial", 10), padx=10, pady=6).pack(side="left")

    # ------------------------------------------------------------------ lists
    def _update_title(self):
        suffix = f"lists {self.lists_version}" if self.lists_source else "built-in lists"
        self.root.title(f"Patient Admin Tool  ({suffix})")

    def reload_lists(self):
        self.lists_source, self.lists_version = core.load_lists()
        for key, values in (("designer", core.DESIGNERS), ("center", core.CENTERS),
                            ("arch_type", core.ARCH_TYPES)):
            self.combos[key].config(values=values)
        self._update_title()
        if not self.lists_source:
            messagebox.showwarning("Lists not found",
                                   f"Couldn't read {core.LISTS_FILE} next to the app:\n"
                                   f"{core.default_lists_path()}")
            return
        messagebox.showinfo("Lists reloaded", f"Using lists version {self.lists_version}.")

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _pdf_zone_text():
        if not core.PDF_AVAILABLE:
            return "PDF reading unavailable: run  pip install pdfplumber"
        if DND_AVAILABLE:
            return "Drag & drop the Rx PDF here  (or click to browse)"
        return "Click here to browse for the Rx PDF"

    @staticmethod
    def _file_zone_text():
        if DND_AVAILABLE:
            return "Drag & drop case files here  (or click to browse)"
        return "Click here to add case files"

    def _set_defaults(self):
        # The designer carries over between cases: keep what's on screen,
        # otherwise use the one saved from the last case.
        designer = self.vars["designer"].get().strip() or self.settings.get("designer", "")
        for v in self.vars.values():
            v.set("")
        self.vars["split_file"].set("No")
        self.vars["cutback"].set("No")
        self.vars["designer"].set(designer)

    def _remember(self, d):
        """Save the designer so the next case (even after a restart) starts with it."""
        if d.get("designer") and d["designer"] != self.settings.get("designer"):
            self.settings["designer"] = d["designer"]
            core.save_settings(self.settings)

    def _set_date(self, key, d):
        self.vars[key].set(d.strftime("%m/%d/%Y"))
        self.update_preview()

    def _set_today(self, key):
        self._set_date(key, date.today())

    def _pick_date(self, key, anchor):
        """Open the calendar under a date field, starting on the date already typed there."""
        DatePicker(self.root, anchor, core.parse_date(self.vars[key].get().strip()),
                   lambda d: self._set_date(key, d))
        return "break"   # a double-click shouldn't also select text behind the popup

    def _collect(self):
        d = {k: v.get().strip() for k, v in self.vars.items()}
        for k in ("split_file", "cutback"):
            d[k] = d[k] or "No"
        return d

    @staticmethod
    def _names_ready(d):
        """Enough info to build file names (not necessarily a folder)."""
        return bool(core.ID_RE.search(d.get("name_id", ""))) and bool(d.get("center"))

    @staticmethod
    def _main_folder(d):
        return core.DESKTOP / core.safe_name(core.folder_name(d))

    def _problems(self, d):
        """Everything that blocks creating the folder, as readable lines."""
        out = []
        if not core.ID_RE.search(d.get("name_id", "")):
            out.append("Name & ID (needs an ID like 1234-QWER)")
        for key, text in (("center", "Center"), ("arch_type", "Arch Type")):
            if not d.get(key):
                out.append(text)
        if not d.get("rx_date"):
            out.append("Rx Date (used in the folder name)")
        for key in DATE_FIELDS:
            if d.get(key) and core.parse_date(d[key]) is None:
                out.append(f"{key.replace('_', ' ').title()} is not a valid date (mm/dd/yyyy)")
        return out

    @staticmethod
    def _split_drop(root, data):
        """tkinterdnd2 sends paths as one Tcl list string; {} wraps paths with spaces."""
        return [Path(p) for p in root.tk.splitlist(data)]

    # ------------------------------------------------------------------ preview
    def update_preview(self, event=None):
        d = self._collect()
        if not core.ID_RE.search(d.get("name_id", "")):
            text = "Drop or browse for an Rx PDF above to see the CaseNotes preview."
            self.folder_label.config(text="")
        else:
            try:
                text = core.build_casenotes(d)
            except Exception as e:
                text = f"(Preview error: {e})"
            problems = self._problems(d)
            if problems:
                self.folder_label.config(text="Still needed: " + "; ".join(problems), fg="#C62828")
            else:
                self.folder_label.config(text=f"Folder: Desktop\\{core.safe_name(core.folder_name(d))}",
                                         fg="#1565C0")
        self.preview.delete("1.0", tk.END)
        self.preview.insert("1.0", text)
        self.refresh_files()

    # ------------------------------------------------------------------ Rx PDF
    def browse_pdf(self):
        path = filedialog.askopenfilename(title="Select Rx PDF",
                                          filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if path:
            self.load_pdf(Path(path))

    def on_pdf_drop(self, event):
        pdfs = [p for p in self._split_drop(self.root, event.data) if p.suffix.lower() == ".pdf"]
        if not pdfs:
            messagebox.showwarning("Not a PDF", "Please drop the Rx .pdf file here.\n"
                                                "Case files go in the green box below.")
            return
        self.load_pdf(pdfs[0])

    def load_pdf(self, path):
        if not core.PDF_AVAILABLE:
            messagebox.showinfo("PDF support needed",
                                "Reading PDFs requires the 'pdfplumber' package.\n\n"
                                "Install it with:\n    pip install pdfplumber")
            return
        try:
            data = core.parse_rx_pdf(path)
        except Exception as e:
            messagebox.showerror("Error reading PDF", str(e))
            return
        self.rx_pdf = path
        self.pdf_zone.config(text=f"Loaded: {path.name}   (click or drop to load a different PDF)")
        if not data:
            messagebox.showwarning("Nothing found",
                                   "Couldn't read any case details from that PDF.\n"
                                   "You can still fill in the form by hand.")
            return

        self._set_defaults()
        self.vars["name_id"].set(data.get("name_id") or data.get("unique_id", ""))
        for key in ("center", "tooth_shade", "stl_only", "ios_box", "due_date", "arch_type"):
            if data.get(key):
                self.vars[key].set(data[key])
        self.update_preview()

    # ------------------------------------------------------------------ case files
    def browse_files(self):
        paths = filedialog.askopenfilenames(title="Select case files")
        if paths:
            self.add_files([Path(p) for p in paths])

    def on_files_drop(self, event):
        self.add_files(self._split_drop(self.root, event.data))

    def add_files(self, paths):
        arch = self.vars["arch_type"].get().strip()
        known = {f["src"] for f in self.files}
        skipped = []
        for p in paths:
            if p.is_dir():
                skipped.append(p.name)
                continue
            if p in known:
                continue
            self.files.append({"src": p, "role": core.guess_role(p, arch)})
            known.add(p)
        if skipped:
            messagebox.showinfo("Folders skipped",
                                "Folders can't be added, only files:\n" + "\n".join(skipped))
        self.refresh_files()

    def refresh_files(self):
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())

        d = self._collect()
        # Re-guess files the user hasn't assigned, in case the arch type changed.
        for f in self.files:
            if f["role"] is None:
                f["role"] = core.guess_role(f["src"], d.get("arch_type", ""))

        plan = [None] * len(self.files)
        if self._names_ready(d):
            main = self._main_folder(d) if not self._problems(d) else None
            plan = core.plan_file_copies([(f["src"], f["role"]) for f in self.files], d, main)

        for i, (f, dest) in enumerate(zip(self.files, plan)):
            role_text = core.ROLES[f["role"]][0] if f["role"] else UNASSIGNED
            if f["role"] is None:
                new_name = "Pick a role below"
            elif dest is None:
                new_name = "(fill in Name & ID and Center)"
            else:
                new_name = " + ".join(f"{d.parent.name}\\{d.name}" for d in dest)
                if core.ROLES[f["role"]][2] == (core.MAIN_DIR,):
                    new_name = f"(patient folder)\\{dest[0].name}"
            tags = ("unassigned",) if f["role"] is None else ()
            self.tree.insert("", "end", iid=str(i), values=(f["src"].name, role_text, new_name), tags=tags)

        keep = [iid for iid in selected if self.tree.exists(iid)]
        if keep:
            self.tree.selection_set(keep)

    def _selected_indexes(self):
        return [int(iid) for iid in self.tree.selection()]

    def on_file_select(self, event=None):
        idx = self._selected_indexes()
        roles = {self.files[i]["role"] for i in idx}
        if len(roles) == 1 and None not in roles:
            self.role_var.set(core.ROLES[roles.pop()][0])
        else:
            self.role_var.set("")

    def apply_role(self, event=None):
        idx = self._selected_indexes()
        if not idx:
            messagebox.showinfo("No file selected", "Select one or more files in the list first.")
            return
        role = core.LABEL_TO_ROLE[self.role_var.get()]
        for i in idx:
            self.files[i]["role"] = role
        self.refresh_files()

    def remove_selected(self):
        for i in sorted(self._selected_indexes(), reverse=True):
            del self.files[i]
        self.refresh_files()

    def clear_files(self):
        self.files.clear()
        self.refresh_files()

    # ------------------------------------------------------------------ actions
    def save_notes_only(self):
        d = self._collect()
        problems = self._problems(d)
        if problems:
            messagebox.showerror("Missing info", "Please provide:\n- " + "\n- ".join(problems))
            return
        path = filedialog.asksaveasfilename(title="Save Case Notes", defaultextension=".txt",
                                            initialfile="CaseNotes.txt",
                                            filetypes=[("Text files", "*.txt")])
        if not path:
            return
        try:
            Path(path).write_text(core.build_casenotes(d), encoding="utf-8")
            self._remember(d)
            messagebox.showinfo("Saved", f"Case notes saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def create_all(self):
        d = self._collect()
        problems = self._problems(d)
        if problems:
            messagebox.showerror("Missing info", "Please provide:\n- " + "\n- ".join(problems))
            return
        unassigned = [f["src"].name for f in self.files if f["role"] is None]
        if unassigned:
            messagebox.showerror("Files need a role",
                                 "Pick a role for these files (or remove them):\n- "
                                 + "\n- ".join(unassigned))
            return
        # The Rx PDF goes in beside CaseNotes.txt, unless it's already in the file list.
        rx = self.rx_pdf if self.rx_pdf not in [f["src"] for f in self.files] else None
        missing = [p.name for p in [f["src"] for f in self.files] + ([rx] if rx else [])
                   if not p.exists()]
        if missing:
            messagebox.showerror("Files not found",
                                 "These files were moved or deleted since you added them:\n- "
                                 + "\n- ".join(missing))
            return

        main = self._main_folder(d)
        if main.exists() and not messagebox.askyesno(
                "Folder already exists",
                f"{main.name}\n\nalready exists on the Desktop.\n"
                "Update its CaseNotes.txt and add the files? Existing files are not overwritten."):
            return

        try:
            core.create_folder_structure(main, core.patient_from(d["name_id"], d["center"]).uid,
                                         notes=core.build_casenotes(d))
            if rx:
                core.copy_files([(rx, core.plan_rx_copy(rx, main))])
            plan = core.plan_file_copies([(f["src"], f["role"]) for f in self.files], d, main)
            copied = core.copy_files(list(zip([f["src"] for f in self.files], plan)))
        except Exception as e:
            messagebox.showerror("Error", f"Something went wrong:\n{e}\n\n"
                                          "Check the folder; some files may have been copied.")
            return

        self._remember(d)
        contents = "CaseNotes.txt, the Rx PDF" if rx else "CaseNotes.txt"
        messagebox.showinfo("Done", f"Folder ready with {contents} and {len(copied)} file(s):\n\n{main}")
        self.clear_files()

    def new_case(self):
        if self.files and not messagebox.askyesno("New case", "Clear the form and file list?"):
            return
        self._set_defaults()
        self.files.clear()
        self.rx_pdf = None
        self.pdf_zone.config(text=self._pdf_zone_text())
        self.update_preview()


if __name__ == "__main__":
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    App(root)
    root.mainloop()
