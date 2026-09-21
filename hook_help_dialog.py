"""Read-only hook-code syntax help view."""

import tkinter as tk
from tkinter import scrolledtext, ttk


HOOK_HELP_TEXT = """
HOOK CODE SYNTAX GUIDE

═══════════════════════════════════════════════════════

H-CODES (Hook Codes)
Format: H{type}{flags}{data_offset}[*deref_offset][:split_offset]@address[:module[:function]]

TYPE CHARACTERS:
  A - ANSI text, big endian, single character
  B - ANSI text, single character
  W - Unicode text, single character
  H - Unicode text with hex dump, single character
  S - ANSI string
  Q - Unicode string
  V - UTF-8 string
  M - Unicode string with hex dump

FLAGS:
  F - Full string capture
  N - No context
  <number>< - Null length specifier
  <number># - Codepage specifier
  <hex>+ - Padding bytes

EXAMPLES:
  HB4@0                    Hook at address 0, ANSI single char, offset 4
  HS-4@12345               Hook at 0x12345, ANSI string, offset -4
  HQ@401000:user32.dll     Hook in user32.dll at offset 0x401000, Unicode string
  HSN-4*0@12345            Hook with no context, ANSI string, offset -4

═══════════════════════════════════════════════════════

R-CODES (Read Codes)
Format: R{type}[null_length<][codepage#]@address

TYPE CHARACTERS:
  S - ANSI string
  Q - Unicode string
  V - UTF-8 string
  M - Unicode string with hex dump

EXAMPLES:
  RS@401000               Read ANSI string at address 0x401000
  RQ@401000               Read Unicode string at address 0x401000
  RV@402000               Read UTF-8 string at address 0x402000

═══════════════════════════════════════════════════════

TIPS:
• Use hex addresses (e.g., 0x401000 or just 401000)
• Negative offsets are allowed (e.g., -4)
• Module names are optional but helpful for portability
• Start with simple hooks (HB4@0) and adjust as needed
• Monitor the output to see if the hook captures text correctly

For more information, refer to the Luna Hook documentation and current community hook guides.
"""


def show_hook_help(root, colors) -> None:
    window = tk.Toplevel(root)
    window.title('Hook Code Syntax Help')
    window.geometry('700x600')
    window.configure(bg=colors['bg'])
    window.transient(root)
    window.grab_set()
    frame = ttk.Frame(window, style='Card.TFrame', padding=15)
    frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
    text = scrolledtext.ScrolledText(frame, wrap=tk.WORD, bg=colors['surface'], fg=colors['fg'], font=('Consolas', 9), borderwidth=0, padx=10, pady=10)
    text.pack(fill=tk.BOTH, expand=True)
    text.insert('1.0', HOOK_HELP_TEXT)
    text.config(state='disabled')
    ttk.Button(window, text='Close', command=window.destroy, style='Secondary.TButton').pack(pady=(0, 15))
    window.update_idletasks()
    window.geometry(f"+{window.winfo_screenwidth() // 2 - window.winfo_width() // 2}+{window.winfo_screenheight() // 2 - window.winfo_height() // 2}")
