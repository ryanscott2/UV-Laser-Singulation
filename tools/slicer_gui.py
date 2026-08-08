"""Desktop front end for the four-window slicer.

    python tools/slicer_gui.py

Pick a file, choose which layer holds the cutlines, set the cutline width, and
run. Uses only the standard library plus the `klayout` wheel, and shells out to
`run_splitter.py` so a crash in the slicer cannot take the window with it.

The production field geometry is deliberately not editable here: the field size,
window centers, and stitch overlap are locked together by the relation the
splitter enforces, so they are shown read-only.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_SPLITTER = REPO_ROOT / "tools" / "run_splitter.py"
SOURCE_TYPES = [("Layout files", "*.dxf *.gds *.oas"), ("All files", "*.*")]
PAD = {"padx": 8, "pady": 4}


def load_layer_inspector():
    """Imported lazily so the window can still open and explain a missing wheel."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from run_splitter import inspect_layers  # noqa: PLC0415 - deliberate lazy import

    return inspect_layers


class SlicerApp(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=10)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.layer_choice = tk.StringVar()
        self.cut_width = tk.StringVar(value="50")
        self.width_mode = tk.StringVar(value="cap")
        self.extension = tk.StringVar(value=".dxf")
        self.clip_mode = tk.StringVar(value="partition")
        self.global_x = tk.StringVar(value="0")
        self.global_y = tk.StringVar(value="0")
        self.anchors = tk.BooleanVar(value=True)
        self.header_extents = tk.BooleanVar(value=True)
        self.allow_outside = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Choose a source file to begin.")
        self.width_hint = tk.StringVar(value="")

        self._layers: dict[str, object] = {}
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._running = False

        self._build_source()
        self._build_cutlines()
        self._build_output()
        self._build_options()
        self._build_run()
        self.rowconfigure(5, weight=1)

    # ------------------------------------------------------------------ layout

    def _build_source(self) -> None:
        box = ttk.LabelFrame(self, text="1. Source", padding=8)
        box.grid(row=0, column=0, sticky="ew", **PAD)
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="File").grid(row=0, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.input_path).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(box, text="Browse...", command=self.pick_input).grid(row=0, column=2)

    def _build_cutlines(self) -> None:
        box = ttk.LabelFrame(self, text="2. Cutlines", padding=8)
        box.grid(row=1, column=0, sticky="ew", **PAD)
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="Layer").grid(row=0, column=0, sticky="w")
        self.layer_combo = ttk.Combobox(box, textvariable=self.layer_choice, state="readonly")
        self.layer_combo.grid(row=0, column=1, columnspan=2, sticky="ew", padx=6)
        self.layer_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_width_hint())
        ttk.Button(box, text="Reload", command=self.load_layers).grid(row=0, column=3)

        ttk.Label(box, text="Width (um)").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(box, textvariable=self.cut_width, width=10).grid(
            row=1, column=1, sticky="w", padx=6, pady=(6, 0)
        )
        modes = ttk.Frame(box)
        modes.grid(row=1, column=2, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Radiobutton(modes, text="Cap at this width", value="cap",
                        variable=self.width_mode).pack(side="left")
        ttk.Radiobutton(modes, text="Force to this width", value="force",
                        variable=self.width_mode).pack(side="left", padx=(10, 0))

        hint = ttk.Label(box, textvariable=self.width_hint, wraplength=560,
                         foreground="#b35900")
        hint.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

    def _build_output(self) -> None:
        box = ttk.LabelFrame(self, text="3. Output", padding=8)
        box.grid(row=2, column=0, sticky="ew", **PAD)
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="Folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.output_path).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(box, text="Browse...", command=self.pick_output).grid(row=0, column=2)
        ttk.Label(box, text="Format").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(box, textvariable=self.extension, state="readonly", width=8,
                     values=[".dxf", ".gds", ".oas"]).grid(row=1, column=1, sticky="w",
                                                           padx=6, pady=(6, 0))

    def _build_options(self) -> None:
        box = ttk.LabelFrame(self, text="4. Options", padding=8)
        box.grid(row=3, column=0, sticky="ew", **PAD)

        left = ttk.Frame(box)
        left.grid(row=0, column=0, sticky="nw")
        ttk.Checkbutton(left, text="Registration anchors on a non-marking layer",
                        variable=self.anchors).pack(anchor="w")
        ttk.Checkbutton(left, text="Declare the window in the DXF header",
                        variable=self.header_extents).pack(anchor="w")
        ttk.Checkbutton(left, text="Allow discarding geometry outside the windows",
                        variable=self.allow_outside).pack(anchor="w")

        right = ttk.Frame(box)
        right.grid(row=0, column=1, sticky="nw", padx=(24, 0))
        ttk.Label(right, text="Calibration shift, um").grid(row=0, column=0, columnspan=4,
                                                           sticky="w")
        ttk.Label(right, text="X").grid(row=1, column=0, sticky="w")
        ttk.Entry(right, textvariable=self.global_x, width=8).grid(row=1, column=1, padx=(2, 8))
        ttk.Label(right, text="Y").grid(row=1, column=2, sticky="w")
        ttk.Entry(right, textvariable=self.global_y, width=8).grid(row=1, column=3, padx=2)
        ttk.Label(right, text="Clip mode").grid(row=2, column=0, columnspan=2, sticky="w",
                                                pady=(6, 0))
        ttk.Combobox(right, textvariable=self.clip_mode, state="readonly", width=12,
                     values=["partition", "full_window"]).grid(row=2, column=2, columnspan=2,
                                                               sticky="w", pady=(6, 0))

        locked = ttk.Label(
            box,
            text=("Field 52.000 mm  .  centers +/-25.400 mm  .  stitch 1.200 mm  "
                  "(locked together; edit the splitter to change them)"),
            foreground="#606060",
        )
        locked.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _build_run(self) -> None:
        bar = ttk.Frame(self)
        bar.grid(row=4, column=0, sticky="ew", **PAD)
        bar.columnconfigure(1, weight=1)
        self.run_button = ttk.Button(bar, text="Slice into four jobs", command=self.start_run)
        self.run_button.grid(row=0, column=0)
        ttk.Label(bar, textvariable=self.status).grid(row=0, column=1, sticky="w", padx=10)

        log_box = ttk.LabelFrame(self, text="Log", padding=6)
        log_box.grid(row=5, column=0, sticky="nsew", **PAD)
        log_box.columnconfigure(0, weight=1)
        log_box.rowconfigure(0, weight=1)
        self.log = tk.Text(log_box, height=14, wrap="word", state="disabled",
                           font=("Consolas", 9))
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_box, command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log["yscrollcommand"] = scroll.set

    # ----------------------------------------------------------------- actions

    def pick_input(self) -> None:
        chosen = filedialog.askopenfilename(title="Select cut geometry",
                                            filetypes=SOURCE_TYPES)
        if not chosen:
            return
        self.input_path.set(chosen)
        if not self.output_path.get():
            self.output_path.set(str(Path(chosen).with_suffix("").parent /
                                     f"{Path(chosen).stem}_four_windows"))
        self.load_layers()

    def pick_output(self) -> None:
        chosen = filedialog.askdirectory(title="Select output folder")
        if chosen:
            self.output_path.set(chosen)

    def load_layers(self) -> None:
        path = Path(self.input_path.get())
        if not path.is_file():
            messagebox.showwarning("No file", "Choose a source file first.")
            return
        try:
            inspect_layers = load_layer_inspector()
            layers = inspect_layers(path)
        except ImportError:
            messagebox.showerror(
                "KLayout missing",
                "The klayout Python wheel is required.\n\nInstall it with:\n\n"
                "    pip install klayout",
            )
            return
        except Exception as exc:  # noqa: BLE001 - surface any read failure to the user
            messagebox.showerror("Could not read file", str(exc))
            return

        if not layers:
            self.status.set("No layers found in that file.")
            return

        self._layers = {}
        labels = []
        for entry in layers:
            label = entry.describe()
            labels.append(label)
            self._layers[label] = entry
        self.layer_combo["values"] = labels

        # Default to whichever layer holds the most drawn area; that is the
        # cutline layer in every file this toolchain has seen.
        best = max(layers, key=lambda e: e.area_mm2)
        self.layer_choice.set(best.describe())
        self.status.set(f"{len(layers)} layer(s) found in {path.name}.")
        self.refresh_width_hint()

    def refresh_width_hint(self) -> None:
        entry = self._layers.get(self.layer_choice.get())
        if entry is None:
            self.width_hint.set("")
            return
        if entry.paths == 0:
            self.width_hint.set(
                f"This layer holds {entry.polygons} filled polygon(s) and no paths, so the "
                "width setting will not change it. Filled shapes carry their drawn size as "
                "geometry; width only applies to native paths."
            )
        else:
            widths = ", ".join(f"{w:g}" for w in entry.widths_um) or "unknown"
            self.width_hint.set(
                f"{entry.paths} path(s) with existing width(s) of {widths} um. "
                "Cap narrows anything wider; force sets them all to your value."
            )

    def start_run(self) -> None:
        if self._running:
            return
        source = Path(self.input_path.get())
        if not source.is_file():
            messagebox.showwarning("No file", "Choose a source file first.")
            return
        try:
            width = float(self.cut_width.get())
            if width <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Bad width", "Cutline width must be a positive number.")
            return
        for label, value in (("X", self.global_x.get()), ("Y", self.global_y.get())):
            try:
                float(value)
            except ValueError:
                messagebox.showwarning("Bad offset", f"Calibration {label} must be a number.")
                return

        entry = self._layers.get(self.layer_choice.get())
        command = [
            sys.executable, str(RUN_SPLITTER),
            "--input", str(source),
            "--cut-width", str(width),
            "--width-mode", self.width_mode.get(),
            "--clip-mode", self.clip_mode.get(),
            "--global-x", self.global_x.get(),
            "--global-y", self.global_y.get(),
            "--extension", self.extension.get(),
        ]
        if self.output_path.get().strip():
            command += ["--output", self.output_path.get().strip()]
        if entry is not None:
            command += ["--layer", entry.selector]
        if not self.anchors.get():
            command.append("--no-anchors")
        if not self.header_extents.get():
            command.append("--no-header-extents")
        if self.allow_outside.get():
            command.append("--allow-outside")

        self._running = True
        self.run_button.state(["disabled"])
        self.status.set("Slicing...")
        self._write_log(f"$ {' '.join(command[1:])}\n\n", clear=True)
        threading.Thread(target=self._worker, args=(command,), daemon=True).start()
        self.after(80, self._drain)

    def _worker(self, command: list[str]) -> None:
        try:
            process = subprocess.run(
                command, cwd=str(REPO_ROOT), capture_output=True, text=True
            )
            if process.stdout:
                self._queue.put(process.stdout)
            if process.stderr:
                self._queue.put(process.stderr)
            self._queue.put(
                "\nDone.\n" if process.returncode == 0
                else f"\nFailed with exit code {process.returncode}.\n"
            )
        except Exception as exc:  # noqa: BLE001 - report to the log rather than die
            self._queue.put(f"\nCould not run the slicer: {exc}\n")
        finally:
            self._queue.put(None)

    def _drain(self) -> None:
        finished = False
        while True:
            try:
                chunk = self._queue.get_nowait()
            except queue.Empty:
                break
            if chunk is None:
                finished = True
                break
            self._write_log(chunk)
        if finished:
            self._running = False
            self.run_button.state(["!disabled"])
            text = self.log.get("1.0", "end")
            if "Failed with exit code" in text or "Traceback" in text:
                self.status.set("Failed. See the log.")
            elif "WARNING" in text:
                self.status.set("Finished with warnings. See the log.")
            else:
                self.status.set("Finished.")
        else:
            self.after(80, self._drain)

    def _write_log(self, text: str, clear: bool = False) -> None:
        self.log["state"] = "normal"
        if clear:
            self.log.delete("1.0", "end")
        self.log.insert("end", text)
        self.log.see("end")
        self.log["state"] = "disabled"


def main() -> int:
    root = tk.Tk()
    root.title("UV Laser Singulation - Slicer")
    root.minsize(700, 640)
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass  # Any platform default is fine.
    SlicerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
