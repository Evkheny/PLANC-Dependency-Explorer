"""help_layout and tree copied from SimStatsPlotter viewutil.py (the rest needs numpy); keep in sync."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def help_layout(frm, top, text):
    """A horizontal pane under *top*: the returned body frame on the left, the 'How to read' *text* on the
    right. The help starts hidden; a button in *top* shows / hides it."""
    pane = ttk.PanedWindow(frm, orient="horizontal")
    pane.pack(fill="both", expand=True)
    body = ttk.Frame(pane)
    pane.add(body, weight=1)
    hf = ttk.Frame(pane, padding=(4, 0, 0, 0))
    txt = tk.Text(hf, wrap="word", width=46, relief="flat", font=("Segoe UI", 9), padx=6, pady=4,
                  background="#f6f8fa")
    sb = ttk.Scrollbar(hf, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    txt.pack(side="left", fill="both", expand=True)
    txt.insert("1.0", text)
    txt.configure(state="disabled")

    def toggle():
        if str(hf) in pane.panes():
            pane.forget(hf)
            btn.config(text="ℹ How to read")
        else:
            pane.add(hf, weight=0)
            btn.config(text="ℹ Hide help")
    btn = ttk.Button(top, text="ℹ How to read", command=toggle)
    btn.pack(side="right", padx=(4, 0))
    return body


def tree(parent, pack=True, **kw):
    """A Treeview with both scrollbars inside its own frame (``tree.master``)."""
    box = ttk.Frame(parent)
    if pack:
        box.pack(fill="both", expand=True)
    t = ttk.Treeview(box, show="headings", **kw)
    vsb = ttk.Scrollbar(box, orient="vertical", command=t.yview)
    hsb = ttk.Scrollbar(box, orient="horizontal", command=t.xview)
    t.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    t.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    box.rowconfigure(0, weight=1)
    box.columnconfigure(0, weight=1)
    t.master = box
    return t
