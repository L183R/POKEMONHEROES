import os
import shlex
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox


class ScriptLauncher(tk.Tk):
    """Simple GUI to run other Python scripts in the background."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Ejecutor de scripts")
        self.geometry("400x300")

        self.script_var = tk.StringVar()
        self.args_var = tk.StringVar()

        self._build_widgets()
        self._load_scripts()

    def _build_widgets(self) -> None:
        frame = ttk.Frame(self, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Script:").grid(row=0, column=0, sticky=tk.W)
        self.script_combo = ttk.Combobox(frame, textvariable=self.script_var, state="readonly")
        self.script_combo.grid(row=0, column=1, sticky=tk.EW)

        ttk.Label(frame, text="Argumentos:").grid(row=1, column=0, sticky=tk.W, pady=(10, 0))
        args_entry = ttk.Entry(frame, textvariable=self.args_var)
        args_entry.grid(row=1, column=1, sticky=tk.EW, pady=(10, 0))

        run_btn = ttk.Button(frame, text="Ejecutar", command=self.run_script)
        run_btn.grid(row=2, column=0, columnspan=2, pady=10)

        self.log = tk.Text(frame, height=8)
        self.log.grid(row=3, column=0, columnspan=2, sticky=tk.NSEW)

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1)

    def _load_scripts(self) -> None:
        scripts = [f for f in os.listdir() if f.endswith(".py") and f != os.path.basename(__file__)]
        self.script_combo["values"] = scripts
        if scripts:
            self.script_var.set(scripts[0])

    def run_script(self) -> None:
        script = self.script_var.get()
        if not script:
            messagebox.showerror("Error", "No hay script seleccionado")
            return
        args = shlex.split(self.args_var.get())
        cmd = [sys.executable, script] + args
        try:
            proc = subprocess.Popen(cmd)
            self.log.insert(tk.END, f"Iniciado {script} (PID {proc.pid})\n")
            self.log.see(tk.END)
        except Exception as exc:
            messagebox.showerror("Error al ejecutar", str(exc))


if __name__ == "__main__":
    app = ScriptLauncher()
    app.mainloop()