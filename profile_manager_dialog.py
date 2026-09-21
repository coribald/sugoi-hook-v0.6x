"""Tk view for browsing and editing saved game profiles."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable


class ProfileManagerDialog:
    """Own profile-manager widgets while delegating state changes to callbacks."""

    def __init__(self, root, colors, profiles: dict[str, dict[str, Any]], *, commit: Callable[[dict[str, dict[str, Any]]], bool], launch: Callable[[str, dict[str, Any]], None], notify: Callable[..., None]):
        self.root, self.colors, self.profiles = root, colors, profiles
        self.commit, self.launch, self.notify = commit, launch, notify

    def open(self) -> None:
        manager = tk.Toplevel(self.root)
        manager.title('💾 Manage Game Profiles')
        manager.geometry('1500x550')
        manager.minsize(1500, 550)
        manager.configure(bg=self.colors['bg'])
        manager.transient(self.root)
        manager.grab_set()
        container = ttk.Frame(manager, style='TFrame')
        container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        container.columnconfigure(0, weight=1); container.rowconfigure(1, weight=1)
        title = ttk.Frame(container, style='Card.TFrame', padding=15)
        title.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
        ttk.Label(title, text='💾 Saved Game Profiles', font=('Segoe UI', 16, 'bold'), foreground=self.colors['primary']).pack()
        count = ttk.Label(title, text=f'Total profiles: {len(self.profiles)}', font=('Segoe UI', 10), foreground=self.colors['text_dim'])
        count.pack(pady=(5, 0))
        card = ttk.Frame(container, style='Card.TFrame', padding=15)
        card.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 15)); card.columnconfigure(0, weight=1); card.rowconfigure(0, weight=1)
        columns = ('game', 'engine', 'hook_type', 'hook_info', 'last_used')
        tree = ttk.Treeview(card, columns=columns, show='headings', height=12)
        for column, label, width in (('game', 'Game', 180), ('engine', 'Engine', 80), ('hook_type', 'Type', 80), ('hook_info', 'Hook Info', 280), ('last_used', 'Last Used', 140)):
            tree.heading(column, text=label); tree.column(column, width=width, anchor='center')
        scrollbar = ttk.Scrollbar(card, orient=tk.VERTICAL, command=tree.yview); tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S)); scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        def populate():
            tree.delete(*tree.get_children())
            for game_id, profile in self.profiles.items():
                hook_type = '🔧 Manual' if profile['hook_type'] == 'manual' else '🎯 Auto'
                hook_info = profile.get('hook_data', 'Unknown')
                if profile['hook_type'] == 'auto': hook_info = f"ID {hook_info} - {profile.get('hook_function', 'Unknown')}"
                tree.insert('', tk.END, text=game_id, values=(profile['exe_name'], '🌙 Luna', hook_type, hook_info, profile.get('last_used', 'Unknown')))
            count.config(text=f'Total profiles: {len(self.profiles)}')

        def selected():
            selection = tree.selection()
            if not selection: return None, None
            game_id = tree.item(selection[0], 'text')
            return game_id, tree.item(selection[0])

        def delete_selected():
            game_id, item = selected()
            if not game_id:
                messagebox.showwarning('No Selection', 'Please select a profile to delete.'); return
            game_name = item['values'][0]
            if not messagebox.askyesno('Confirm Deletion', f"Delete profile for '{game_name}'?"): return
            updated = dict(self.profiles); del updated[game_id]
            if self.commit(updated):
                self.profiles = updated; populate(); self.notify('Profile deleted.', level='success')

        def launch_selected():
            game_id, _item = selected()
            if not game_id:
                messagebox.showwarning('No Selection', 'Please select a profile to launch.'); return
            profile = self.profiles.get(game_id)
            if profile is None: return
            if self.launch(game_id, profile):
                manager.destroy()

        def clear_all():
            if not self.profiles:
                messagebox.showinfo('Info', 'No profiles to clear.'); return
            if not messagebox.askyesno('Confirm Clear All', f'Delete all {len(self.profiles)} profiles?\n\nThis cannot be undone.'): return
            if self.commit({}):
                self.profiles = {}; populate(); self.notify('All profiles cleared.', level='success')

        populate()
        buttons = ttk.Frame(container, style='Card.TFrame', padding=15); buttons.grid(row=2, column=0, sticky=(tk.W, tk.E))
        group = ttk.Frame(buttons); group.pack(expand=True)
        ttk.Button(group, text='🚀 Launch Game', command=launch_selected, style='TButton').pack(side=tk.LEFT, padx=5)
        ttk.Button(group, text='🗑️ Delete Selected', command=delete_selected, style='Secondary.TButton').pack(side=tk.LEFT, padx=5)
        ttk.Button(group, text='🗑️ Clear All', command=clear_all, style='Danger.TButton').pack(side=tk.LEFT, padx=5)
        ttk.Button(group, text='✖️ Close', command=manager.destroy, style='Secondary.TButton').pack(side=tk.LEFT, padx=5)
        manager.update_idletasks(); manager.geometry(f"+{manager.winfo_screenwidth() // 2 - manager.winfo_width() // 2}+{manager.winfo_screenheight() // 2 - manager.winfo_height() // 2}")
