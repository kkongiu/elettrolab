import queue
import threading

from .solver import check, simulate
from .gui_common import FAIL, MUTED, OK, WARN


class SimulationMixin:
    def _init_simulation(self):
        self._async_queue = queue.SimpleQueue()
        self._sim_generation = 0
        self._sim_after = None
        self._sim_pending = False
        self._sim_thread = None
        self._sim_waiting = None

    def _update_summary(self):
        done = [v for v in self.results.values() if v is not None]
        passed = sum(1 for v in done if v)
        total = len(self.ids)
        if len(done) < total:
            self.summary.configure(text=f"{passed}/{total} test superati ({total - len(done)} da eseguire)")
        else:
            self.summary.configure(text=f"{passed}/{total} test superati")

    def _initialize_exercise_list(self):
        self.results = {eid: None for eid in self.ids}
        self.ex_list.delete(0, "end")
        for eid in self.ids:
            label = f"   —     {eid}  {self.titles.get(eid, '')}".rstrip()
            self.ex_list.insert("end", label)
        self._update_summary()

    def _invalidate_simulation(self):
        self._sim_generation += 1
        self._sim_pending = False
        self._sim_waiting = None
        if self._sim_after is not None:
            self.root.after_cancel(self._sim_after)
            self._sim_after = None

    def _schedule_simulation(self):
        self._invalidate_simulation()
        generation = self._sim_generation
        self.problems_list = self.doc.problems()
        self.res = None
        if any(p["severity"] == "error" for p in self.problems_list):
            return
        try:
            circ = self.doc.to_circuit()
        except Exception as e:
            self.problems_list.append({
                "severity": "error", "code": getattr(e, "code", "error"),
                "message": getattr(e, "message", str(e))})
            return
        self._sim_pending = True
        self._sim_waiting = (generation, circ)
        self._sim_after = self.root.after(
            120, lambda: self._start_simulation(generation, circ))

    def _start_simulation(self, generation, circ):
        if generation != self._sim_generation:
            return
        self._sim_after = None
        if self._sim_thread is not None and self._sim_thread.is_alive():
            self._sim_waiting = (generation, circ)
            return
        self._sim_waiting = None
        self._sim_thread = threading.Thread(
            target=self._simulate_worker, args=(generation, circ), daemon=True)
        self._sim_thread.start()

    def _simulate_worker(self, generation, circ):
        result = None
        problems = []
        try:
            result = simulate(circ)
            check(circ, result)
        except Exception as e:
            problems.append({
                "severity": "error", "code": getattr(e, "code", "error"),
                "message": getattr(e, "message", str(e))})
        self._async_queue.put(("simulation", generation, result, problems))

    def _poll_async_results(self):
        while True:
            try:
                item = self._async_queue.get_nowait()
            except queue.Empty:
                break
            _, generation, result, problems = item
            if generation != self._sim_generation:
                continue
            self._sim_pending = False
            self.res = result
            self.problems_list.extend(problems)
            self.schem = self._new_schem()
            self.bb = self._make_bb(self.doc.board)
            self._update_header()
            self._update_problems()
            self._fill()
            self._plot()
            eid = self.doc.meta.get("id")
            if result is not None and self.doc.builtin and not self.dirty and eid in self.ids:
                self.sim_cache[eid] = result
                self.results[eid] = result.ok
                index = self.ids.index(eid)
                self._loading = True
                self.ex_list.delete(index)
                self.ex_list.insert(index, f"  {'PASS' if result.ok else 'FAIL'}   {eid}")
                self.ex_list.itemconfig(index, foreground=OK if result.ok else FAIL)
                self._loading = False
                self._update_summary()
        if (self._sim_waiting is not None and
                (self._sim_thread is None or not self._sim_thread.is_alive())):
            generation, circ = self._sim_waiting
            self._start_simulation(generation, circ)

    def _update_header(self):
        if self.doc is None:
            return
        title = self.doc.meta.get("title") or self.doc.meta.get("id", "circuito")
        star = " *" if self.dirty else ""
        self.title.configure(text=f"{title}{star}")
        self.notes.configure(text=self.doc.meta.get("notes", ""))
        errors = [p for p in self.problems_list if p["severity"] == "error"]
        warnings = [p for p in self.problems_list if p["severity"] == "warning"]
        if errors:
            self.status.configure(text=f"INCOMPLETO  ({len(errors)} errori)",
                                  foreground=FAIL)
        elif self.res is not None and self.res.checks:
            if self.res.ok:
                self.status.configure(text="TEST SUPERATO", foreground=OK)
            else:
                self.status.configure(text="TEST FALLITO", foreground=FAIL)
        elif self.res is not None:
            self.status.configure(text="SIMULAZIONE OK", foreground=OK)
        elif self._sim_pending:
            self.status.configure(text="SIMULAZIONE...", foreground=MUTED)
        else:
            self.status.configure(text=f"PRONTO  ({len(warnings)} avvisi)",
                                  foreground=WARN)
        self.viol.configure(text=" | ".join(v["message"] for v in
                                            (self.res.violations if self.res else [])))

    def _update_problems(self):
        items = self.problems_list
        lines = []
        for p in items[:20]:
            mark = "x" if p["severity"] == "error" else "!"
            lines.append(f"{mark} {p['message']}")
        if not lines:
            lines = ["Nessun problema."]
        self.problems.configure(state="normal")
        self.problems.delete("1.0", "end")
        self.problems.insert("1.0", "\n".join(lines))
        self.problems.configure(state="disabled")
