"""Barebones dicing launcher (Tkinter, Windows 7, Python 3.8, standard library only).

A thin wrapper so you never type paths: pick a set folder from a dropdown and click a
button. Each button runs the existing CLI script (optiscan.py, winlase_build_jobs.py,
dice_wafer.py) as a subprocess with the paths filled in and streams its output into the
log pane -- so all the verified safety logic (position verify, power/frequency check,
arm gate, controlled abort) runs unchanged. This UI adds no laser logic of its own.

Launch:  double-click run_ui.bat   (or:  pythonw dice_ui.py)
"""

import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

HERE = Path(__file__).resolve().parent
PYCON = str(Path(sys.executable).with_name("python.exe"))  # console python for children
OPTISCAN = HERE / "optiscan.py"
BUILD = HERE / "winlase_build_jobs.py"
DICE = HERE / "dice_wafer.py"
PASSES_CSV = HERE / "dice_passes.csv"
STOP_FLAG = HERE / ".dice_stop"        # UI writes this on STOP; dice_wafer polls it
ROOT_MEMO = HERE / ".dice_ui_root"     # remembers the last DXF folder
DEFAULT_PASSES = 175
CREATE_NEW_CONSOLE = 0x00000010


def is_set_dir(p: Path) -> bool:
    """A sliced set: has P1..P4 station subfolders."""
    return p.is_dir() and all((p / f"P{i}").is_dir() for i in (1, 2, 3, 4))


def passes_for(set_name: str) -> int:
    """Look up passes for a set from dice_passes.csv (exact, else 'default', else 175)."""
    import csv
    table = {}
    try:
        with PASSES_CSV.open(newline="", encoding="utf-8") as stream:
            for row in csv.reader(stream):
                if len(row) < 2 or not row[0].strip() or row[0].lstrip().startswith("#"):
                    continue
                if row[0].strip().lower() in ("set", "name"):
                    continue
                try:
                    table[row[0].strip()] = int(row[1])
                except ValueError:
                    pass
    except OSError:
        pass
    return table.get(set_name, table.get("default", DEFAULT_PASSES))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q = queue.Queue()
        self.busy = False
        root.title("Wafer Dicer")
        root.geometry("780x580")

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="DXF folder:").grid(row=0, column=0, sticky="w")
        self.root_var = tk.StringVar(value=self._load_root())
        ttk.Entry(top, textvariable=self.root_var).grid(row=0, column=1, sticky="we", padx=4)
        ttk.Button(top, text="Browse", command=self.browse_root).grid(row=0, column=2)
        ttk.Label(top, text="Set:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.set_var = tk.StringVar()
        self.set_combo = ttk.Combobox(top, textvariable=self.set_var, state="readonly")
        self.set_combo.grid(row=1, column=1, sticky="we", padx=4, pady=(6, 0))
        self.set_combo.bind("<<ComboboxSelected>>", lambda e: self._show_passes())
        ttk.Button(top, text="Refresh", command=self.refresh_sets).grid(row=1, column=2, pady=(6, 0))
        ttk.Label(top, text="Passes/station:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.passes_var = tk.StringVar(value=str(DEFAULT_PASSES))
        self.passes_spin = ttk.Spinbox(top, from_=1, to=100000, width=10,
                                       textvariable=self.passes_var)
        self.passes_spin.grid(row=2, column=1, sticky="w", padx=4, pady=(6, 0))
        ttk.Label(top, text="(pre-filled from dice_passes.csv; change to override this run)",
                  foreground="#666").grid(row=3, column=1, sticky="w", padx=4)
        ttk.Label(top, text="Est. time:").grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.eta_var = tk.StringVar(value="--")
        ttk.Label(top, textvariable=self.eta_var, foreground="#2d7d46",
                  font=("Segoe UI", 9, "bold")).grid(row=4, column=1, sticky="w",
                                                      padx=4, pady=(6, 0))
        top.columnconfigure(1, weight=1)

        btns = ttk.Frame(root, padding=(8, 4))
        btns.pack(fill="x")
        self.buttons = {}
        for i, (name, fn) in enumerate([
                ("Info", self.info), ("Home", self.home), ("Extract", self.extract),
                ("Jog", self.jog), ("Build jobs", self.build), ("Dry run", self.dry_run),
                ("DICE (arm)", self.dice)]):
            b = ttk.Button(btns, text=name, command=fn)
            b.grid(row=0, column=i, padx=3, sticky="we")
            btns.columnconfigure(i, weight=1)
            self.buttons[name] = b

        self.stop_btn = tk.Button(root, text="STOP  (controlled)", command=self.stop,
                                  bg="#c0392b", fg="white", font=("Segoe UI", 11, "bold"))
        self.stop_btn.pack(fill="x", padx=8, pady=4)

        self.log_txt = scrolledtext.ScrolledText(root, height=22, wrap="none", bg="black",
                                                  fg="#d0d0d0", font=("Consolas", 9))
        self.log_txt.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.log_txt.configure(state="disabled")

        self.refresh_sets()
        self.log("Ready. Pick a set, then: Build jobs -> Dry run -> DICE. STOP = controlled stop.")
        self._pump()

    # -- DXF folder memory ------------------------------------------------------
    def _load_root(self) -> str:
        try:
            return ROOT_MEMO.read_text(encoding="utf-8").strip() or str(HERE)
        except OSError:
            return str(HERE)

    def browse_root(self):
        d = filedialog.askdirectory(initialdir=self.root_var.get() or str(HERE))
        if d:
            self.root_var.set(d)
            try:
                ROOT_MEMO.write_text(d, encoding="utf-8")
            except OSError:
                pass
            self.refresh_sets()

    def refresh_sets(self):
        root = Path(self.root_var.get())
        sets = sorted(p.name for p in root.iterdir() if is_set_dir(p)) if root.is_dir() else []
        self.set_combo["values"] = sets
        if sets and self.set_var.get() not in sets:
            self.set_var.set(sets[0])
        elif not sets:
            self.set_var.set("")
        self._show_passes()

    def selected_set(self):
        name = self.set_var.get()
        if not name:
            messagebox.showwarning("Wafer Dicer", "Pick a set first (a folder with P1..P4).")
            return None
        return Path(self.root_var.get()) / name

    def _show_passes(self):
        """Pre-fill the passes box from the CSV when the selected set changes."""
        s = self.set_var.get()
        if s:
            self.passes_var.set(str(passes_for(s)))

    def _passes_value(self):
        """Validated passes count from the box, or None (with a warning) if invalid."""
        try:
            n = int(self.passes_var.get())
        except (ValueError, tk.TclError):
            n = 0
        if n < 1:
            messagebox.showwarning("Wafer Dicer", "Passes/station must be a whole number >= 1.")
            return None
        return n

    # -- subprocess plumbing ----------------------------------------------------
    def _run(self, argv):
        if self.busy:
            return
        try:
            STOP_FLAG.unlink()
        except OSError:
            pass
        self._set_busy(True)
        self.eta_var.set("--")
        cmd = [PYCON, "-u"] + [str(a) for a in argv]
        self.log("\n$ " + " ".join(cmd[2:]))

        def worker():
            try:
                p = subprocess.Popen(cmd, cwd=str(HERE), stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
                for line in iter(p.stdout.readline, ""):
                    self.q.put(line.rstrip("\n"))
                p.stdout.close()
                self.q.put(("__done__", p.wait()))
            except Exception as exc:
                self.q.put("ERROR launching: %s" % exc)
                self.q.put(("__done__", -1))

        threading.Thread(target=worker, daemon=True).start()

    def _pump(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__done__":
                    self.log("[exit %s]" % item[1])
                    self._set_busy(False)
                else:
                    if isinstance(item, str) and item.startswith("[eta] "):
                        self.eta_var.set(item[6:].strip())
                    self.log(item)
        except queue.Empty:
            pass
        self.root.after(120, self._pump)

    def _set_busy(self, busy):
        self.busy = busy
        for b in self.buttons.values():
            b.config(state="disabled" if busy else "normal")
        self.passes_spin.config(state="disabled" if busy else "normal")

    def log(self, text):
        self.log_txt.configure(state="normal")
        self.log_txt.insert("end", text + "\n")
        self.log_txt.see("end")
        self.log_txt.configure(state="disabled")

    # -- actions ----------------------------------------------------------------
    def info(self):
        self._run([OPTISCAN, "info"])

    def home(self):
        self._run([OPTISCAN, "home", "--yes"])

    def extract(self):
        self._run([OPTISCAN, "extract", "--yes"])

    def jog(self):
        # Keyboard jog needs a real console window (msvcrt), so open one.
        try:
            subprocess.Popen([PYCON, str(OPTISCAN), "jog", "--step", "2000"],
                             cwd=str(HERE), creationflags=CREATE_NEW_CONSOLE)
            self.log("(opened the jog tool in a separate console window)")
        except Exception as exc:
            messagebox.showwarning("Wafer Dicer", "could not open jog: %s" % exc)

    def build(self):
        s = self.selected_set()
        if s:
            self._run([BUILD, s])

    def dry_run(self):
        s = self.selected_set()
        if not s:
            return
        n = self._passes_value()
        if n is None:
            return
        self._run([DICE, s, "--passes", n, "--yes", "--extract-after", "--stop-flag", STOP_FLAG])

    def dice(self):
        s = self.selected_set()
        if not s:
            return
        n = self._passes_value()
        if n is None:
            return
        if not messagebox.askyesno(
                "ARM THE LASER",
                "Fire the laser and dice:\n\n    %s\n    %d passes/station\n\n"
                "Close the WinLase GUI first, and keep a hand on the e-stop.\n\nProceed?"
                % (s.name, n), icon="warning", default="no"):
            self.log("dice cancelled.")
            return
        self._run([DICE, s, "--arm", "--extract-after", "--yes", "--passes", n,
                   "--stop-flag", STOP_FLAG])

    def stop(self):
        try:
            STOP_FLAG.write_text("stop", encoding="utf-8")
            self.log("STOP requested -- dice/dry-run will controlled-stop at the next "
                     "pass/station (hardware e-stop for a true emergency).")
        except OSError as exc:
            messagebox.showwarning("Wafer Dicer", "could not write stop flag: %s" % exc)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
