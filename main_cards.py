"""Main window section/card construction.

Builders own Tk widget layout only. All widgets remain assigned to the host
coordinator so existing attribute references keep working, and every action
still routes back through coordinator methods.
"""

import tkinter as tk
from tkinter import scrolledtext, ttk


def create_section_header(host, parent, section_key, title_text, title_style="Title.TLabel"):
    """Create a reusable section header with a left-side collapse toggle."""
    header_frame = ttk.Frame(parent)
    header_frame.columnconfigure(1, weight=1)

    toggle_btn = ttk.Button(
        header_frame,
        text="▾",
        style="Disclosure.TButton",
        command=lambda key=section_key: host.toggle_section(key)
    )
    toggle_btn.grid(row=0, column=0, sticky=tk.W, padx=(2, 2))
    setattr(host, f"{section_key}_toggle_btn", toggle_btn)

    ttk.Label(header_frame, text=title_text, style=title_style).grid(row=0, column=1, sticky=tk.W)
    return header_frame


def build_process_card(host, parent):
    """Create the process selection card"""
    card = ttk.Frame(parent, style="Card.TFrame", padding=12)
    host.process_card = card
    card.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 12), padx=(0, 6))
    card.columnconfigure(0, weight=1)

    # Card header
    header = create_section_header(host, card, 'process', "🎮 1. Select Process")
    header.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
    header.columnconfigure(2, weight=0)

    host.process_header_spacer = ttk.Button(
        header,
        text="",
        style="TButton",
        state='disabled'
    )
    host.process_header_spacer.grid(row=0, column=2, sticky=tk.E)

    host.process_body_frame = ttk.Frame(card)
    host.process_body_frame.grid(row=1, column=0, sticky=(tk.W, tk.E))
    host.process_body_frame.columnconfigure(0, weight=1)

    # Toolbar row
    toolbar_frame = ttk.Frame(host.process_body_frame)
    toolbar_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 4))

    ttk.Button(toolbar_frame, text="🔄 Refresh", command=host.refresh_processes,
              style="Secondary.TButton").pack(side=tk.LEFT, padx=(0, 5))

    ttk.Button(toolbar_frame, text="📂 Browse for EXE",
              command=host.browse_and_attach_exe,
              style="Secondary.TButton").pack(side=tk.LEFT, padx=(0, 5))

    ttk.Button(toolbar_frame, text="💾 Game Profiles",
              command=host.open_profile_manager,
              style="Secondary.TButton").pack(side=tk.LEFT)

    # Search row
    search_frame = ttk.Frame(host.process_body_frame)
    search_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
    search_frame.columnconfigure(0, weight=1)

    host.search_var = tk.StringVar()
    search_entry = ttk.Entry(search_frame, textvariable=host.search_var)
    search_entry.grid(row=0, column=0, sticky=(tk.W, tk.E))
    search_entry.insert(0, "🔍 Search processes...")
    search_entry.bind('<FocusIn>', lambda e: search_entry.delete(0, tk.END) if search_entry.get() == "🔍 Search processes..." else None)

    # Process list
    list_frame = ttk.Frame(host.process_body_frame)
    list_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    list_frame.columnconfigure(0, weight=1)
    list_frame.rowconfigure(0, weight=1)

    columns = ('pid', 'arch', 'name')
    host.process_tree = ttk.Treeview(list_frame, columns=columns, show='tree headings', height=3)
    host.process_tree_default_height = 3
    host.process_tree.heading('#0', text='')
    host.process_tree.heading('pid', text='PID')
    host.process_tree.heading('arch', text='Arch')
    host.process_tree.heading('name', text='Process Name')

    host.process_tree.column('#0', width=host.scale(28), anchor='center', stretch=False)
    host.process_tree.column('pid', width=host.scale(58), minwidth=host.scale(52), anchor='center', stretch=False)
    host.process_tree.column('arch', width=host.scale(52), minwidth=host.scale(48), anchor='center', stretch=False)
    host.process_tree.column('name', width=host.scale(320), minwidth=host.scale(180), anchor='w', stretch=True)

    scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=host.process_tree.yview)
    host.process_tree.configure(yscrollcommand=scrollbar.set)

    host.process_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

    # Now set up the search trace after process_tree is created
    host.search_var.trace('w', lambda *args: host.filter_processes())

    # Enable double-click to attach
    host.process_tree.bind('<Double-Button-1>', lambda e: host.attach_process())
    host.bind_vertical_mousewheel(host.process_tree)

    # Action buttons
    action_frame = ttk.Frame(card)
    action_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(10, 0))
    action_frame.columnconfigure(0, weight=1)

    host.status_label = ttk.Label(action_frame, text="● Not attached",
                                  style="Status.TLabel",
                                  foreground=host.colors['text_dim'])
    host.status_label.grid(row=0, column=0, sticky=tk.W)

    host.detach_btn = ttk.Button(
        action_frame,
        text="⏹️ Detach",
        command=host.detach_process,
        style="Danger.TButton",
        state='disabled'
    )
    host.detach_btn.grid(row=0, column=1, sticky=tk.E, padx=(0, 8))

    host.attach_btn = ttk.Button(
        action_frame,
        text="➡️ Attach Selected",
        command=host.attach_process,
        style="TButton"
    )
    host.attach_btn.grid(row=0, column=2, sticky=tk.E)


def build_hook_card(host, parent):
    """Create the hook selection card"""
    card = ttk.Frame(parent, style="Card.TFrame", padding=12)
    host.hook_card = card
    card.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 12), padx=(6, 0))
    card.columnconfigure(0, weight=1)

    # Card header
    header_frame = create_section_header(host, card, 'hook', "🎯 2. Select Hook")
    header_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
    header_frame.columnconfigure(2, weight=0)

    host.select_hook_btn = ttk.Button(
        header_frame,
        text="✅ Use Selected Hook",
        command=host.select_hook,
        style="TButton",
        state='disabled'
    )
    host.select_hook_btn.grid(row=0, column=2, sticky=tk.E)

    status_frame = ttk.Frame(card)
    status_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 6))
    status_frame.columnconfigure(0, weight=1)

    host.hook_status_summary = ttk.Label(
        status_frame,
        text="Not attached | Engine: Luna",
        style="Status.TLabel",
        foreground=host.colors['text_dim']
    )
    host.hook_status_summary.grid(row=0, column=0, sticky=tk.W)

    host.hook_active_label = ttk.Label(
        status_frame,
        text="Current hook: none selected",
        style="Status.TLabel",
        foreground=host.colors['text_dim']
    )
    host.hook_active_label.grid(row=1, column=0, sticky=tk.W)

    host.hook_concat_label = ttk.Label(
        status_frame,
        text="Concatenation: inactive",
        style="Status.TLabel",
        foreground=host.colors['text_dim']
    )
    host.hook_concat_label.grid(row=2, column=0, sticky=tk.W)

    host.hook_profile_label = ttk.Label(
        status_frame,
        text="Saved profile: none",
        style="Status.TLabel",
        foreground=host.colors['text_dim']
    )
    host.hook_profile_label.grid(row=3, column=0, sticky=tk.W)

    host.hook_last_action_label = ttk.Label(
        status_frame,
        text="Last action: waiting for attachment",
        style="Status.TLabel",
        foreground=host.colors['text_dim']
    )
    host.hook_last_action_label.grid(row=4, column=0, sticky=tk.W)

    host.hook_body_frame = ttk.Frame(card)
    host.hook_body_frame.grid(row=2, column=0, sticky=(tk.W, tk.E))
    host.hook_body_frame.columnconfigure(0, weight=1)

    # Hook list
    list_frame = ttk.Frame(host.hook_body_frame)
    list_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    list_frame.columnconfigure(0, weight=1)
    list_frame.rowconfigure(0, weight=1)

    columns = ('id', 'function', 'preview')
    host.hook_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=3)
    host.hook_tree_default_height = 3
    host.hook_tree.heading('id', text='ID')
    host.hook_tree.heading('function', text='Function')
    host.hook_tree.heading('preview', text='Text Preview')

    host.hook_tree.column('id', width=host.scale(44), minwidth=host.scale(40), anchor='center', stretch=False)
    host.hook_tree.column('function', width=host.scale(210), minwidth=host.scale(140), anchor='w', stretch=False)
    host.hook_tree.column('preview', width=host.scale(520), minwidth=host.scale(260), anchor='w', stretch=True)

    scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=host.hook_tree.yview)
    h_scrollbar = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=host.hook_tree.xview)
    host.hook_tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=h_scrollbar.set)

    host.hook_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
    h_scrollbar.grid(row=1, column=0, sticky=(tk.W, tk.E))

    # Enable double-click to select hook
    host.hook_tree.bind('<Double-Button-1>', lambda e: host.select_hook())
    host.hook_tree.bind('<Button-3>', host.show_hook_context_menu)
    host.bind_vertical_mousewheel(host.hook_tree)

    # Manual hook input section
    manual_hook_frame = ttk.Frame(host.hook_body_frame)
    manual_hook_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(8, 0))
    manual_hook_frame.columnconfigure(1, weight=1)

    ttk.Label(manual_hook_frame, text="Manual Hook:",
             font=('Segoe UI', 9, 'bold'),
             foreground=host.colors['accent']).grid(row=0, column=0, sticky=tk.W, padx=(0, 10))

    host.manual_hook_entry = ttk.Entry(manual_hook_frame)
    host.manual_hook_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
    host.manual_hook_entry.insert(0, "e.g., HB4@0 or HS-4@12345")
    host.manual_hook_entry.bind('<FocusIn>', lambda e: host.manual_hook_entry.delete(0, tk.END)
                                if host.manual_hook_entry.get().startswith("e.g.,") else None)
    host.manual_hook_entry.bind('<Return>', lambda e: host.attach_manual_hook())

    host.attach_manual_hook_btn = ttk.Button(manual_hook_frame, text="🔗 Attach Hook",
                                             command=host.attach_manual_hook,
                                             style="Secondary.TButton",
                                             state='disabled')
    host.attach_manual_hook_btn.grid(row=0, column=2)

    # Help button for hook syntax
    help_btn = ttk.Button(manual_hook_frame, text="❓",
                         command=host.show_hook_help,
                         style="Secondary.TButton",
                         width=3)
    help_btn.grid(row=0, column=3, padx=(5, 0))

    host.hook_tree.bind('<<TreeviewSelect>>', lambda e: host.update_hook_action_state())
    host.update_hook_status_panel()
    host.update_hook_action_state()


def build_plugins_card(host, parent):
    """Create the plugins management card"""
    card = ttk.Frame(parent, style="Card.TFrame", padding=12)
    card.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 15))
    card.columnconfigure(0, weight=1)

    # Card header
    header_frame = create_section_header(host, card, 'plugins', "🔌 Plugins")
    header_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 4))

    # Plugin action buttons
    btn_frame = ttk.Frame(header_frame)
    btn_frame.grid(row=0, column=2, sticky=tk.E)

    # Show active plugins count
    host.plugins_count_label = ttk.Label(btn_frame,
                                         text=f"Active: {len(host.active_plugins)} plugins",
                                         style="Status.TLabel",
                                         foreground=host.colors['text_dim'])
    host.plugins_count_label.pack(side=tk.LEFT, padx=(0, 10))


    ttk.Button(btn_frame, text="📂 Open Folder",
              command=host.open_plugins_folder,
              style="Secondary.TButton").pack(side=tk.LEFT, padx=(0, 5))

    ttk.Button(btn_frame, text="🔄 Refresh",
              command=host.reload_plugins,
              style="Secondary.TButton").pack(side=tk.LEFT)

    host.plugins_body_frame = ttk.Frame(card)
    host.plugins_body_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    host.plugins_body_frame.columnconfigure(0, weight=1)

    controls_frame = ttk.Frame(host.plugins_body_frame)
    controls_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 8))

    host.plugin_toggle_btn = ttk.Button(controls_frame, text="Toggle Active", command=host.toggle_selected_plugin, style="Secondary.TButton")
    host.plugin_toggle_btn.pack(side=tk.LEFT, padx=(0, 5))

    host.plugin_configure_btn = ttk.Button(controls_frame, text="Configure", command=host.configure_selected_plugin, style="Secondary.TButton")
    host.plugin_configure_btn.pack(side=tk.LEFT, padx=(0, 5))

    host.plugin_move_up_btn = ttk.Button(controls_frame, text="Move Up", command=lambda: host.move_selected_plugin(-1), style="Secondary.TButton")
    host.plugin_move_up_btn.pack(side=tk.LEFT, padx=(0, 5))

    host.plugin_move_down_btn = ttk.Button(controls_frame, text="Move Down", command=lambda: host.move_selected_plugin(1), style="Secondary.TButton")
    host.plugin_move_down_btn.pack(side=tk.LEFT, padx=(0, 5))

    host.plugin_controls_hint = ttk.Label(controls_frame, text="Tip: Use buttons for precise ordering. Drag still works.", style="Status.TLabel", foreground=host.colors['text_dim'])
    host.plugin_controls_hint.pack(side=tk.RIGHT)

    # Plugins list
    list_frame = ttk.Frame(host.plugins_body_frame)
    list_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    list_frame.columnconfigure(0, weight=1)
    list_frame.rowconfigure(0, weight=1)

    columns = ('status', 'name', 'version', 'description', 'actions')
    host.plugins_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=7)
    host.plugins_tree.heading('status', text='Status')
    host.plugins_tree.heading('name', text='Plugin Name')
    host.plugins_tree.heading('version', text='Version')
    host.plugins_tree.heading('description', text='Description')
    host.plugins_tree.heading('actions', text='Actions')

    host.plugins_tree.column('status', width=host.scale(80), minwidth=host.scale(80), anchor='center', stretch=False)
    host.plugins_tree.column('name', width=host.scale(150), minwidth=host.scale(120), anchor='center', stretch=False)
    host.plugins_tree.column('version', width=host.scale(60), minwidth=host.scale(50), anchor='center', stretch=False)
    host.plugins_tree.column('description', width=host.scale(350), minwidth=host.scale(180), anchor='center', stretch=True)
    host.plugins_tree.column('actions', width=host.scale(100), minwidth=host.scale(100), anchor='center', stretch=False)

    scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=host.plugins_tree.yview)
    host.plugins_tree.configure(yscrollcommand=scrollbar.set)

    host.plugins_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

    # Enable double-click to toggle plugin
    host.plugins_tree.bind('<Double-Button-1>', lambda e: host.toggle_selected_plugin())

    # Enable single-click on Actions column for configure button
    host.plugins_tree.bind('<Button-1>', host.on_plugin_click)

    # Enable right-click context menu
    host.plugins_tree.bind('<Button-3>', host.show_plugin_context_menu)

    # Enable Drag and Drop for reordering
    host.plugins_tree.bind('<B1-Motion>', host.on_plugin_drag_motion)
    host.plugins_tree.bind('<ButtonRelease-1>', host.on_plugin_drag_release)

    host.plugins_tree.bind('<<TreeviewSelect>>', lambda e: host.update_plugin_action_buttons())
    host.bind_vertical_mousewheel(host.plugins_tree)

    # Populate the plugins list
    host.refresh_plugins_list()
    host.toggle_section('plugins', host.plugins_section_collapsed)
    host.update_plugin_action_buttons()


def build_output_card(host, parent):
    """Create the text output card"""
    card = ttk.Frame(parent, style="Card.TFrame", padding=12)
    card.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 15))
    card.columnconfigure(0, weight=1)
    card.rowconfigure(1, weight=1)

    # Card header
    header_frame = create_section_header(host, card, 'output', "📝 Session Output")
    header_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))

    # Action buttons
    action_frame = ttk.Frame(header_frame)
    action_frame.grid(row=0, column=2, sticky=tk.E)

    ttk.Button(action_frame, text="💾 Save to File",
              command=host.save_to_file,
              style="Secondary.TButton").pack(side=tk.LEFT, padx=(0, 5))
    ttk.Button(action_frame, text="🗑️ Clear",
              command=host.clear_output,
              style="Secondary.TButton").pack(side=tk.LEFT)

    host.output_body_frame = ttk.Frame(card)
    host.output_body_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    host.output_body_frame.columnconfigure(0, weight=1)
    host.output_body_frame.rowconfigure(1, weight=1)
    host.output_body_frame.rowconfigure(3, weight=1)

    events_header = create_section_header(host, host.output_body_frame, 'events', "Session Events", title_style="Status.TLabel")
    events_header.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 4))

    host.events_body_frame = ttk.Frame(host.output_body_frame)
    host.events_body_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
    host.events_body_frame.columnconfigure(0, weight=1)
    host.events_body_frame.rowconfigure(0, weight=1)

    host.event_text = tk.Text(
        host.events_body_frame,
        wrap=tk.WORD,
        bg=host.colors['bg'],
        fg=host.colors['text_dim'],
        insertbackground=host.colors['primary'],
        selectbackground=host.colors['primary'],
        selectforeground=host.colors['bg'],
        font=('Consolas', 9),
        borderwidth=0,
        padx=10,
        pady=8,
        state='disabled',
        height=1
    )
    host.event_scrollbar = ttk.Scrollbar(host.events_body_frame, orient=tk.VERTICAL, command=host.event_text.yview)
    host.event_text.configure(yscrollcommand=host.event_scrollbar.set)
    host.event_text.grid(row=0, column=0, sticky=(tk.W, tk.E))
    host.event_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
    host.event_scrollbar.grid_remove()
    host.event_text_default_height = 1
    host.bind_vertical_mousewheel(host.event_text)

    extracted_header = create_section_header(host, host.output_body_frame, 'extracted', "Extracted Text", title_style="Status.TLabel")
    extracted_header.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 4))

    host.extracted_body_frame = ttk.Frame(host.output_body_frame)
    host.extracted_body_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    host.extracted_body_frame.columnconfigure(0, weight=1)
    host.extracted_body_frame.rowconfigure(0, weight=1)

    host.output_text = scrolledtext.ScrolledText(
        host.extracted_body_frame, wrap=tk.WORD,
        bg=host.colors['bg'],
        fg=host.colors['fg'],
        insertbackground=host.colors['primary'],
        selectbackground=host.colors['primary'],
        selectforeground=host.colors['bg'],
        font=('Consolas', 10),
        borderwidth=0,
        padx=10, pady=10,
        state='disabled',
        height=8
    )
    host.output_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    host.output_text_default_height = 8
    host.bind_vertical_mousewheel(host.output_text)


def build_status_bar(host, tray_available):
    """Create status bar with statistics and transient notices."""
    status_frame = ttk.Frame(host.root, style="Card.TFrame", padding=(10, 5))
    status_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=15, pady=(5, 10))

    host.status_conn_label = ttk.Label(status_frame, text="● Disconnected",
                                       style="Status.TLabel",
                                       foreground=host.colors['text_dim'])
    host.status_conn_label.pack(side=tk.LEFT, padx=(0, 20))

    host.status_lines_label = ttk.Label(status_frame, text="Lines: 0", style="Status.TLabel")
    host.status_lines_label.pack(side=tk.LEFT, padx=(0, 15))

    host.status_words_label = ttk.Label(status_frame, text="Words: 0", style="Status.TLabel")
    host.status_words_label.pack(side=tk.LEFT, padx=(0, 15))

    host.status_chars_label = ttk.Label(status_frame, text="Characters: 0", style="Status.TLabel")
    host.status_chars_label.pack(side=tk.LEFT, padx=(0, 15))

    host.status_rate_label = ttk.Label(status_frame, text="Rate: 0 c/s", style="Status.TLabel")
    host.status_rate_label.pack(side=tk.LEFT)

    if tray_available:
        ttk.Button(
            status_frame,
            text="🔽 Minimize to Tray",
            command=host.hide_to_tray,
            style="Secondary.TButton"
        ).pack(side=tk.RIGHT)

    host.status_notice_label = ttk.Label(
        status_frame,
        text="Ready",
        style="Status.TLabel",
        foreground=host.colors['text_dim']
    )
    host.status_notice_label.pack(side=tk.RIGHT, padx=(15, 10))
