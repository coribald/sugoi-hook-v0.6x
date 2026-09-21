"""Tk view for editing one plugin's settings."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable


def resolve_setting_value(widget: Any, options: dict[str, str] | None, value_type: str) -> Any:
    """Convert a settings widget value to the plugin-facing representation."""
    if value_type in ('choice', 'color') and options:
        display_value = widget.get()
        if value_type == 'color' and ' - ' in display_value:
            return display_value.split(' - ')[0]
        return next((key for key, display in options.items() if display == display_value or key == display_value), display_value)
    if value_type == 'multiline_str':
        return widget.get('1.0', tk.END).rstrip('\n')
    return widget.get()


def preview_font(font_name: str, size: int, *, bold: bool = False, italic: bool = False) -> tuple[Any, ...]:
    styles = tuple(style for enabled, style in ((bold, 'bold'), (italic, 'italic')) if enabled)
    return (font_name, size, ' '.join(styles)) if styles else (font_name, size)


class PluginSettingsDialog:
    """Own dialog widgets; the coordinator supplies plugin and save callbacks."""

    def __init__(self, root, colors, *, notify: Callable[..., None], save: Callable[..., tuple[bool, dict]], on_saved: Callable[[], None]):
        self.root, self.colors = root, colors
        self.notify, self.save, self.on_saved = notify, save, on_saved

    def open(self, plugin_filename: str, plugin: Any) -> None:
        plugin_name = plugin.name
        draft_values: dict[str, Any] = {}
        dynamic_settings = getattr(plugin, 'get_settings_for_values', None)

        def settings():
            return dynamic_settings(draft_values) if callable(dynamic_settings) else plugin.get_settings()

        if not settings():
            self.notify(f"Plugin '{plugin_name}' has no configurable settings.", level='info')
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Configure {plugin_name}")
        dialog.geometry('800x900')
        dialog.configure(bg=self.colors['bg'])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.rowconfigure(0, weight=1)
        dialog.columnconfigure(0, weight=1)
        container = ttk.Frame(dialog, style='TFrame')
        container.grid(row=0, column=0, sticky='nsew', padx=15, pady=15)
        container.rowconfigure(1, weight=1)
        container.columnconfigure(0, weight=1)
        title_card = ttk.Frame(container, style='Card.TFrame', padding=15)
        title_card.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        ttk.Label(title_card, text=f'⚙️ {plugin_name} Settings', font=('Segoe UI', 14, 'bold'), foreground=self.colors['primary']).pack()
        settings_card = ttk.Frame(container, style='Card.TFrame', padding=15)
        settings_card.grid(row=1, column=0, sticky='nsew', pady=(0, 10))
        settings_card.rowconfigure(0, weight=1)
        settings_card.columnconfigure(0, weight=1)
        canvas = tk.Canvas(settings_card, bg=self.colors['surface'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(settings_card, orient='vertical', command=canvas.yview)
        form = ttk.Frame(canvas, style='Card.TFrame')
        form.bind('<Configure>', lambda _event: canvas.configure(scrollregion=canvas.bbox('all')))
        form_window = canvas.create_window((0, 0), window=form, anchor='nw', width=canvas.winfo_width())
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind('<Configure>', lambda event: canvas.itemconfig(form_window, width=event.width))
        canvas.grid(row=0, column=0, sticky='nsew')
        scrollbar.grid(row=0, column=1, sticky='ns')

        def is_descendant(child, ancestor):
            while child is not None:
                if child == ancestor:
                    return True
                try:
                    child = child._nametowidget(child.winfo_parent())
                except Exception:
                    return False
            return False

        def wheel(event):
            try:
                hovered = dialog.winfo_containing(event.x_root, event.y_root)
            except Exception:
                hovered = event.widget
            if hovered is None or not is_descendant(hovered, canvas):
                return
            try:
                if hovered.winfo_class().lower() in {'tcombobox', 'combobox', 'listbox', 'text', 'entry', 'spinbox'}:
                    return
            except Exception:
                return
            canvas.yview_scroll(int(-event.delta / 120), 'units')
            return 'break'
        canvas.bind_all('<MouseWheel>', wheel)

        widgets: dict[str, tuple[Any, dict[str, str] | None, str]] = {}
        preview: dict[str, Any] = {}

        def values():
            return {name: resolve_setting_value(widget, options, kind) for name, (widget, options, kind) in widgets.items()}

        def refresh_preview(*_args):
            if plugin_filename != 'overlay_window.py' or not preview:
                return
            try:
                current = values()
                background = current.get('bg_color', '#1e1e2e')
                preview['frame'].configure(bg=background, highlightbackground=current.get('border_color', self.colors['border']), highlightcolor=current.get('border_color', self.colors['border']))
                for key, label, default_color, default_font, default_size, bold, italic in (
                    ('translation', preview['translation'], '#89b4fa', 'Segoe UI', 14, True, False),
                    ('original', preview['original'], '#a6adc8', 'Segoe UI', 10, False, False),
                    ('warning', preview['warning'], '#f9e2af', 'Segoe UI', 12, False, True),
                ):
                    label.configure(bg=background, fg=current.get(f'{key}_color', default_color), font=preview_font(current.get(f'{key}_font', default_font), int(current.get(f'{key}_font_size', default_size)), bold=bool(current.get(f'{key}_bold', bold)), italic=bool(current.get(f'{key}_italic', italic))))
            except Exception:
                pass

        def remember():
            draft_values.update(values())

        def render():
            nonlocal widgets
            remember()
            widgets = {}
            for child in form.winfo_children():
                child.destroy()
            for name, specification in settings().items():
                current, kind, description, *option_values = specification
                options = option_values[0] if option_values else None
                current = draft_values.get(name, current)
                row = ttk.Frame(form)
                row.pack(fill=tk.X, pady=8, padx=5)
                ttk.Label(row, text=description + ':', font=('Segoe UI', 10, 'bold'), foreground=self.colors['fg']).pack(anchor=tk.W, pady=(0, 5))
                if kind == 'color' and options:
                    color_row = ttk.Frame(row); color_row.pack(fill=tk.X)
                    variable = tk.StringVar(value=current)
                    combo = ttk.Combobox(color_row, textvariable=variable, width=35)
                    combo['values'] = [f'{key} - {value}' for key, value in options.items()]
                    if current in options: combo.set(f'{current} - {options[current]}')
                    combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
                    swatch = tk.Canvas(color_row, width=40, height=25, bg=current, highlightthickness=1, highlightbackground=self.colors['border'])
                    swatch.pack(side=tk.LEFT)
                    def update_swatch(_event=None, combo=combo, swatch=swatch):
                        try: swatch.config(bg=combo.get().split(' - ')[0])
                        except Exception: pass
                        refresh_preview()
                    combo.bind('<<ComboboxSelected>>', update_swatch); combo.bind('<KeyRelease>', update_swatch)
                    widgets[name] = (variable, options, kind)
                elif kind == 'int_slider' and options:
                    slider_row = ttk.Frame(row); slider_row.pack(fill=tk.X)
                    variable = tk.IntVar(value=current)
                    value_label = ttk.Label(slider_row, text=str(current), font=('Segoe UI', 10, 'bold'), foreground=self.colors['primary']); value_label.pack(side=tk.RIGHT, padx=(10, 0))
                    slider = tk.Scale(slider_row, from_=options['min'], to=options['max'], orient=tk.HORIZONTAL, variable=variable, bg=self.colors['surface'], fg=self.colors['fg'], highlightthickness=0, troughcolor=self.colors['surface_light'], activebackground=self.colors['primary'], command=lambda value: value_label.config(text=str(int(float(value)))))
                    slider.pack(side=tk.LEFT, fill=tk.X, expand=True); variable.trace_add('write', refresh_preview); widgets[name] = (variable, options, kind)
                elif kind == 'choice' and options:
                    variable = tk.StringVar(value=current); combo = ttk.Combobox(row, textvariable=variable); combo['values'] = [options.get(key, key) for key in options]
                    if current in options: combo.set(options[current])
                    combo.pack(fill=tk.X)
                    def choice(_event=None, name=name, variable=variable, options=options):
                        draft_values[name] = resolve_setting_value(variable, options, 'choice'); refresh_preview()
                        if name == 'provider' and callable(dynamic_settings): render()
                    combo.bind('<<ComboboxSelected>>', choice); combo.bind('<KeyRelease>', refresh_preview); widgets[name] = (variable, options, kind)
                elif kind == 'bool':
                    variable = tk.BooleanVar(value=current); ttk.Checkbutton(row, text='Enabled', variable=variable).pack(anchor=tk.W); variable.trace_add('write', refresh_preview); widgets[name] = (variable, None, kind)
                elif kind == 'multiline_str':
                    text = tk.Text(row, height=10, wrap=tk.WORD, bg=self.colors['surface'], fg=self.colors['fg'], insertbackground=self.colors['fg'], relief=tk.FLAT, borderwidth=1)
                    text.pack(fill=tk.BOTH, expand=True)
                    if current: text.insert('1.0', current)
                    widgets[name] = (text, None, kind)
                else:
                    variable = tk.IntVar(value=current) if kind == 'int' else tk.StringVar(value=current)
                    ttk.Entry(row, textvariable=variable, show='*' if kind == 'secret' else '').pack(fill=tk.X)
                    if kind == 'int': variable.trace_add('write', refresh_preview)
                    widgets[name] = (variable, None, kind)
            refresh_preview()

        render()
        if plugin_filename == 'overlay_window.py':
            card = ttk.Frame(container, style='Card.TFrame', padding=15); card.grid(row=2, column=0, sticky='ew', pady=(0, 10))
            ttk.Label(card, text='Live Preview', font=('Segoe UI', 11, 'bold'), foreground=self.colors['primary']).pack(anchor=tk.W, pady=(0, 8))
            frame = tk.Frame(card, bg='#1e1e2e', highlightthickness=1, highlightbackground=self.colors['border'], padx=14, pady=12); frame.pack(fill=tk.X)
            preview.update(frame=frame, translation=tk.Label(frame, text='Girl: "Do I look a little tired?"', anchor='w', justify='left'), original=tk.Label(frame, text='少女「少し疲れた感じ、出てるかな」', anchor='w', justify='left'), warning=tk.Label(frame, text='Please enable the translation plugin', anchor='w', justify='left'))
            preview['translation'].pack(fill=tk.X); preview['original'].pack(fill=tk.X, pady=4); preview['warning'].pack(fill=tk.X, pady=(6, 0)); refresh_preview()
        buttons = ttk.Frame(container, style='Card.TFrame', padding=15); buttons.grid(row=3, column=0, sticky='ew')
        def close(): canvas.unbind_all('<MouseWheel>'); dialog.destroy()
        def commit():
            remember(); saved, accepted = self.save(plugin_filename, plugin, draft_values)
            if not saved: return
            self.on_saved(); rejected = len(draft_values) - len(accepted)
            self.notify(f"Saved accepted settings for {plugin_name}; {rejected} invalid setting(s) were not saved." if rejected else f"Saved settings for {plugin_name}.", level='warning' if rejected else 'success')
            close()
        group = ttk.Frame(buttons); group.pack(expand=True)
        ttk.Button(group, text='💾 Save Settings', command=commit, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(group, text='✖️ Cancel', command=close, style='Disclosure.TButton').pack(side=tk.LEFT)
        dialog.update_idletasks(); dialog.geometry(f"+{dialog.winfo_screenwidth() // 2 - dialog.winfo_width() // 2}+{dialog.winfo_screenheight() // 2 - dialog.winfo_height() // 2}")
        dialog.protocol('WM_DELETE_WINDOW', close)
