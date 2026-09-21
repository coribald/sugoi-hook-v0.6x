"""Main Tk window shell and scrollable layout."""

from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk
from typing import Callable


@dataclass
class MainWindowWidgets:
    canvas: tk.Canvas
    scrollbar: ttk.Scrollbar
    canvas_shell: ttk.Frame
    selection_cards_frame: ttk.Frame
    update_scrollbar_visibility: Callable[[], None]


class MainWindowView:
    """Own the window shell; callers provide section construction callbacks."""

    def __init__(self, root, colors):
        self.root, self.colors = root, colors

    def build(self, *, engine: str, create_process, create_hook, create_plugins, create_output, update_selection_layout, configure_wheel) -> MainWindowWidgets:
        header = ttk.Frame(self.root, style='TFrame', padding=(15, 15, 15, 0)); header.pack(fill=tk.X)
        shell = ttk.Frame(self.root, style='TFrame'); shell.pack(fill=tk.BOTH, expand=True, padx=15, pady=(10, 0))
        canvas = tk.Canvas(shell, bg=self.colors['bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(shell, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set); canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        container = ttk.Frame(canvas, style='TFrame', padding=(15, 15, 15, 0))
        window = canvas.create_window((0, 0), window=container, anchor='nw')
        scrollbar_visible = True

        def update_scrollbar(_event=None):
            nonlocal scrollbar_visible
            bbox = canvas.bbox('all')
            if not bbox:
                canvas.configure(scrollregion=(0, 0, 0, 0))
                if scrollbar_visible: scrollbar.pack_forget(); scrollbar_visible = False
                return
            x1, y1, x2, y2 = bbox; canvas.configure(scrollregion=(x1, y1, x2, y2))
            needed = y2 - y1 > max(1, canvas.winfo_height()) + 1
            if needed and not scrollbar_visible:
                scrollbar.pack(side=tk.RIGHT, fill=tk.Y); scrollbar_visible = True
            elif not needed and scrollbar_visible:
                scrollbar.pack_forget(); scrollbar_visible = False; canvas.yview_moveto(0)

        container.bind('<Configure>', update_scrollbar)
        canvas.bind('<Configure>', lambda event: (canvas.itemconfigure(window, width=event.width), update_scrollbar()))
        ttk.Label(header, text='🐾Sugoi Hook v0.6x', font=('Segoe UI', 18, 'bold'), foreground=self.colors['primary']).pack(side=tk.LEFT)
        content = ttk.Frame(container); content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1); content.rowconfigure(2, weight=1)
        selection = ttk.Frame(content); selection.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 12)); selection.columnconfigure(0, weight=1); selection.columnconfigure(1, weight=1)
        create_process(selection); create_hook(selection); update_selection_layout(); create_plugins(content); create_output(content)
        return MainWindowWidgets(canvas, scrollbar, shell, selection, update_scrollbar)
