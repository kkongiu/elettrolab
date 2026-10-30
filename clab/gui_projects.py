import json
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .document import Document, slugify
from .gui_common import DATA, FAIL, MUTED, OK, PROJECTS
from .layouts import LAYOUTS


class ProjectMixin:
    def _show_start_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Benvenuto in elettrolab")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.protocol("WM_DELETE_WINDOW", self._on_close)
        dialog.grab_set()

        welcome = ttk.Frame(dialog, padding=24)
        welcome.pack(fill="both", expand=True)
        ttk.Label(welcome, text="Da dove vuoi iniziare?",
                  font=("DejaVu Sans", 15, "bold")).pack(pady=(0, 8))
        ttk.Label(welcome, text="Crea un nuovo progetto oppure scegli un esercizio da aprire.",
                  wraplength=360, justify="center").pack(pady=(0, 18))

        def begin_new():
            dialog.destroy()
            self._new()

        def show_exercises():
            welcome.pack_forget()
            chooser.pack(fill="both", expand=True)
            dialog.update_idletasks()
            dialog.geometry(f"{max(520, dialog.winfo_reqwidth())}x{max(420, dialog.winfo_reqheight())}")
            exercise_list.focus_set()

        def show_projects():
            dialog.destroy()
            self._show_project_dialog()

        ttk.Button(welcome, text="Nuovo progetto", command=begin_new,
                   style="Accent.TButton").pack(fill="x", pady=4)
        ttk.Button(welcome, text="Apri esercizio…", command=show_exercises).pack(
            fill="x", pady=4)
        ttk.Button(welcome, text="Apri progetto…", command=show_projects,
                   state="normal" if self._project_names() else "disabled").pack(
                       fill="x", pady=4)

        chooser = ttk.Frame(dialog, padding=16)
        ttk.Label(chooser, text="Scegli un esercizio",
                  font=("DejaVu Sans", 13, "bold")).pack(anchor="w", pady=(0, 8))
        list_frame = ttk.Frame(chooser)
        list_frame.pack(fill="both", expand=True)
        exercise_list = tk.Listbox(list_frame, width=54, height=14,
                                   exportselection=False)
        exercise_list.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical",
                                  command=exercise_list.yview)
        scrollbar.pack(side="right", fill="y")
        exercise_list.configure(yscrollcommand=scrollbar.set)
        for eid in self.ids:
            title = self.titles.get(eid, "")
            exercise_list.insert("end", f"{eid}  {title}" if title else eid)

        def open_selected(_event=None):
            selection = exercise_list.curselection()
            if not selection:
                return
            dialog.destroy()
            self._choose_exercise(selection[0])

        buttons = ttk.Frame(chooser)
        buttons.pack(fill="x", pady=(10, 0))
        def back_to_welcome():
            chooser.pack_forget()
            welcome.pack(fill="both", expand=True)
            dialog.update_idletasks()
            dialog.geometry(f"{max(420, dialog.winfo_reqwidth())}x{max(230, dialog.winfo_reqheight())}")

        ttk.Button(buttons, text="Indietro", command=back_to_welcome).pack(side="left")
        ttk.Button(buttons, text="Apri", command=open_selected,
                   style="Accent.TButton").pack(side="right")
        exercise_list.bind("<Double-Button-1>", open_selected)
        dialog.bind("<Return>", open_selected)
        dialog.update_idletasks()
        dialog.geometry(f"{max(420, dialog.winfo_reqwidth())}x{max(230, dialog.winfo_reqheight())}")
        dialog.wait_window()

    def _show_project_dialog(self):
        names = self._project_names()
        if not names:
            messagebox.showinfo("Progetti", "Non ci sono progetti salvati.", parent=self.root)
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Apri progetto")
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Scegli un progetto",
                  font=("DejaVu Sans", 13, "bold")).pack(anchor="w", pady=(0, 8))
        listing = tk.Listbox(frame, width=48, height=min(16, max(5, len(names))),
                             exportselection=False)
        listing.pack(fill="both", expand=True)
        for name in names:
            listing.insert("end", name)

        def open_selected(_event=None):
            selection = listing.curselection()
            if selection:
                name = names[selection[0]]
                dialog.destroy()
                self._open_project(name)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Annulla", command=dialog.destroy).pack(side="left")
        ttk.Button(buttons, text="Apri", command=open_selected,
                   style="Accent.TButton").pack(side="right")
        listing.bind("<Double-Button-1>", open_selected)
        dialog.bind("<Return>", open_selected)
        listing.selection_set(0)
        listing.focus_set()
        dialog.wait_window()

    def _confirm_discard(self):
        if not self.dirty:
            return True
        return messagebox.askyesno("Modifiche non salvate",
                                   "Scartare le modifiche al circuito corrente?",
                                   parent=self.root)

    def _select_exercise(self):
        if getattr(self, "_loading", False):
            return
        sel = self.ex_list.curselection()
        if not sel:
            return
        eid = self.ids[sel[0]]
        if not self._confirm_discard():
            cur = self.doc.meta.get("id") if self.doc else None
            self.ex_list.selection_clear(0, "end")
            if cur in self.ids:
                i = self.ids.index(cur)
                self.ex_list.selection_set(i)
                self.ex_list.activate(i)
            return
        raw = json.loads((DATA / "exercises" / f"{eid}.json").read_text(encoding="utf-8"))
        doc = Document(raw, self.db, layout=LAYOUTS.get(eid), builtin=True)
        self.proj_list.selection_clear(0, "end")
        self.status.configure(text="SIMULAZIONE...", foreground=MUTED)
        self.root.update_idletasks()
        cached = self.sim_cache.get(eid)
        self._load_doc(doc, res=cached)
        if cached is None and self.res is not None:
            self.sim_cache[eid] = self.res
        if self.res is not None:
            self.results[eid] = self.res.ok
            i = self.ids.index(eid)
            self._loading = True
            self.ex_list.delete(i)
            self.ex_list.insert(i, f"  {'PASS' if self.res.ok else 'FAIL'}   {eid}")
            self.ex_list.itemconfig(i, foreground=OK if self.res.ok else FAIL)
            self.ex_list.selection_set(i)
            self._loading = False
        self._update_summary()
        self._hint(f"Esercizio {eid} caricato. Salva una copia per modificarlo.")

    def _load_doc(self, doc, res=None):
        self.doc = doc
        self.schem = None
        self.selected = None
        self.selected_wire = None
        self.wire_from = None
        self.bb_wire_from = None
        self.armed = None
        self.drag = None
        self.mode = "select"
        self.history = []
        self.future = []
        self.dirty = False
        self.t_anim = 0.0
        self.code_editing = False
        self.code_btn.configure(text="Modifica")
        self.code_text.configure(state="disabled")
        self.code_view.configure(state="readonly")
        self.res = res
        self._after_change(simulate=res is None)

    def _new(self):
        if not self._confirm_discard():
            return
        doc = Document({"id": "nuovo", "title": "Nuovo circuito", "analysis": "dc",
                        "parts": {}, "nets": {}}, self.db,
                       layout={"parts": {}, "gnd_y": 330})
        self.proj_list.selection_clear(0, "end")
        self.ex_list.selection_clear(0, "end")
        self._load_doc(doc)
        self._hint("Nuovo circuito. Aggiungi componenti dalla palette.")

    def _save(self):
        if self.doc is None:
            return
        if self.doc.source and not self.doc.builtin:
            self.doc.save(self.doc.source, self.doc.source.with_suffix(".layout.json"),
                          self.doc.source.with_suffix(".board.json"))
            self.dirty = False
            self._update_header()
            self._refresh_projects()
            return
        self._save_as()

    def _save_as(self):
        if self.doc is None:
            return
        name = simpledialog.askstring("Salva progetto", "Nome del progetto:",
                                      initialvalue=self.doc.meta.get("title", "circuito"),
                                      parent=self.root)
        if not name:
            return
        slug = slugify(name)
        path = PROJECTS / f"{slug}.json"
        layout = PROJECTS / f"{slug}.layout.json"
        board = PROJECTS / f"{slug}.board.json"
        if path.exists() and not messagebox.askyesno(
                "Esiste già", f"{slug}.json esiste. Sovrascrivere?", parent=self.root):
            return
        self.doc.meta["id"] = slug
        self.doc.meta["title"] = name
        self.doc.save(path, layout, board)
        self.dirty = False
        self._refresh_projects(select=slug)
        self._update_header()
        self._hint(f"Salvato in {path}")

    def _exercise_label(self, eid):
        state = self.results.get(eid)
        mark = "" if state is None else ("PASS  " if state else "FAIL  ")
        title = self.titles.get(eid, "")
        return f"{mark}{eid}  {title}" if title else f"{mark}{eid}"

    def _project_names(self):
        return sorted(p.stem for p in PROJECTS.glob("*.json")
                      if not p.name.endswith((".layout.json", ".board.json")))

    def _choose_exercise(self, index):
        if not 0 <= index < len(self.ids):
            return
        self.ex_list.selection_clear(0, "end")
        self.ex_list.selection_set(index)
        self.ex_list.activate(index)
        self._select_exercise()

    def _refresh_projects(self, select=None):
        self.proj_list.delete(0, "end")
        names = self._project_names()
        for name in names:
            self.proj_list.insert("end", name)
        if select in names:
            i = names.index(select)
            self.proj_list.selection_set(i)
            self.proj_list.activate(i)
        self._build_menu()

    def _open_project(self, name=None):
        if name is None:
            sel = self.proj_list.curselection()
            if not sel:
                return
            name = self.proj_list.get(sel[0])
        if not self._confirm_discard():
            self.proj_list.selection_clear(0, "end")
            return
        path = PROJECTS / f"{name}.json"
        layout = PROJECTS / f"{name}.layout.json"
        board = PROJECTS / f"{name}.board.json"
        try:
            doc = Document.from_file(path, layout, self.db, board_path=board)
        except Exception as e:
            self._hint(f"Errore apertura: {e}")
            return
        self.ex_list.selection_clear(0, "end")
        self._load_doc(doc)
        self._hint(f"Progetto {name} aperto.")
