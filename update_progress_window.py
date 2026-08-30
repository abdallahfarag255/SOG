import tkinter as tk
from tkinter import ttk


class UpdateProgressWindow:
    def __init__(self):
        self._root = tk.Tk()
        self._root.title("تحديث SOG Monitoring")
        self._root.geometry("340x110")
        self._root.resizable(False, False)

        tk.Label(self._root, text="جاري تحميل التحديث...").pack(pady=(16, 6))
        self._progress = ttk.Progressbar(self._root, length=280, mode="determinate", maximum=100)
        self._progress.pack(pady=4)
        self._percent_label = tk.Label(self._root, text="0%")
        self._percent_label.pack()

    def update_progress(self, percent: int) -> None:
        self._progress["value"] = percent
        self._percent_label.config(text=f"{percent}%")
        self._root.update()

    def close(self) -> None:
        self._root.destroy()
