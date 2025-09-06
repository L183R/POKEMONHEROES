"""Simple GUI for launching multiple PowerShell scripts simultaneously.

This utility lets the user select one or more ``.ps1`` files and execute each
in its own PowerShell console window. The processes are started with
``subprocess.Popen`` so they run concurrently without blocking the GUI.

The script is intended for Windows environments where PowerShell is available.
"""

from __future__ import annotations

import os
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox


def _is_windows() -> bool:
    """Return ``True`` if running on a Windows platform."""
    return os.name == "nt"


class ScriptRunnerGUI(tk.Tk):
    """Tkinter window that manages the list of scripts to execute."""

    def __init__(self) -> None:
        super().__init__()
        self.title("PowerShell Script Runner")
        self.geometry("500x300")

        self.script_list = tk.Listbox(self, selectmode=tk.MULTIPLE)
        self.script_list.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=5)

        tk.Button(btn_frame, text="Add Script", command=self.add_script).pack(
            side=tk.LEFT, padx=5
        )
        tk.Button(btn_frame, text="Remove Selected", command=self.remove_selected).pack(
            side=tk.LEFT, padx=5
        )
        tk.Button(btn_frame, text="Run Selected", command=self.run_selected).pack(
            side=tk.LEFT, padx=5
        )

    def add_script(self) -> None:
        """Open a file dialog and add the chosen script to the list."""
        path = filedialog.askopenfilename(
            title="Select PowerShell script",
            filetypes=[("PowerShell Scripts", "*.ps1"), ("All files", "*.*")],
        )
        if path:
            self.script_list.insert(tk.END, path)

    def remove_selected(self) -> None:
        """Remove highlighted entries from the list."""
        for index in reversed(self.script_list.curselection()):
            self.script_list.delete(index)

    def run_selected(self) -> None:
        """Launch each selected script in its own PowerShell console."""
        if not _is_windows():
            messagebox.showerror("Unsupported OS", "This tool requires Windows.")
            return

        selections = [self.script_list.get(i) for i in self.script_list.curselection()]
        if not selections:
            messagebox.showinfo("No selection", "Select at least one script to run.")
            return

        for script in selections:
            if not os.path.exists(script):
                messagebox.showerror("File not found", f"{script} not found.")
                continue

            try:
                subprocess.Popen(
                    ["powershell", "-NoExit", "-File", script],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            except Exception as exc:  # pragma: no cover - GUI error reporting
                messagebox.showerror("Execution error", f"Could not run {script}\n{exc}")


if __name__ == "__main__":
    app = ScriptRunnerGUI()
    app.mainloop()