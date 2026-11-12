"""Copy a table to the Windows clipboard in two formats at once, so it pastes as a real table:
- "HTML Format" (CF_HTML): Excel, OneNote, Word and Outlook paste it as a table (bold, bullets and line breaks kept);
- CF_UNICODETEXT: tab-separated text (Excel splits it into cells; any text editor).
No third-party package (ctypes). Falls back to the Tk clipboard (text only) outside Windows or on error."""
import ctypes
import html
import sys

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def tsv(rows):
    """Tab-separated text; cells with tabs, line breaks or quotes are quoted the Excel way."""
    def cell(v):
        v = '' if v is None else str(v)
        if any(c in v for c in '\t\n"'):
            v = '"' + v.replace('"', '""') + '"'
        return v
    return '\r\n'.join('\t'.join(cell(c) for c in r) for r in rows)


def html_table(rows, header=True, title=''):
    """rows: list of lists of cell text; a cell may be a pre-built html fragment given as ('html', '...')."""
    css = ('border-collapse:collapse;font-family:Calibri,Segoe UI,sans-serif;font-size:10pt')
    td = 'border:1px solid #8C9BA5;padding:3px 6px;vertical-align:top'
    out = [f'<table style="{css}">']                     # no title line: the table pastes from the first cell
    for i, r in enumerate(rows):
        out.append('<tr>')
        for c in r:
            if isinstance(c, tuple) and c and c[0] == 'html':
                body = c[1]
            else:
                body = html.escape('' if c is None else str(c)).replace('\n', '<br>')
            if header and i == 0:
                out.append(f'<th style="{td};background:#0B5563;color:white;text-align:left">{body}</th>')
            else:
                out.append(f'<td style="{td}">{body}</td>')
        out.append('</tr>')
    out.append('</table>')
    return ''.join(out)


def _cf_html(fragment):
    """Wrap an html fragment in the CF_HTML header (byte offsets in utf-8)."""
    pre = '<html><body>\r\n<!--StartFragment-->'
    post = '<!--EndFragment-->\r\n</body></html>'
    hdr = 'Version:0.9\r\nStartHTML:{:010d}\r\nEndHTML:{:010d}\r\nStartFragment:{:010d}\r\nEndFragment:{:010d}\r\n'
    dummy = hdr.format(0, 0, 0, 0)
    start_html = len(dummy.encode('utf-8'))
    start_frag = start_html + len(pre.encode('utf-8'))
    end_frag = start_frag + len(fragment.encode('utf-8'))
    end_html = end_frag + len(post.encode('utf-8'))
    return (hdr.format(start_html, end_html, start_frag, end_frag) + pre + fragment + post).encode('utf-8')


def _set(fmt, data):
    k32 = ctypes.windll.kernel32
    u32 = ctypes.windll.user32
    k32.GlobalAlloc.restype = ctypes.c_void_p
    k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u32.SetClipboardData.restype = ctypes.c_void_p
    u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    p = k32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    k32.GlobalUnlock(h)
    if not u32.SetClipboardData(fmt, h):
        raise OSError('SetClipboardData failed')


def copy(widget, text, html_fragment=None):
    """Put text (+ html table) on the clipboard. widget = any Tk widget (fallback)."""
    try:
        _copy_win(text, html_fragment)
        return
    except Exception:                   # not Windows or clipboard busy: plain text through Tk
        pass
    widget.clipboard_clear()
    widget.clipboard_append(text)


def _copy_win(text, html_fragment):
    if sys.platform == 'win32':
        u32 = ctypes.windll.user32
        u32.OpenClipboard.argtypes = [ctypes.c_void_p]
        for _ in range(10):
            if u32.OpenClipboard(None):
                break
        else:
            raise OSError('clipboard busy')
        try:
            u32.EmptyClipboard()
            _set(CF_UNICODETEXT, (text + '\0').encode('utf-16-le'))
            if html_fragment:
                _set(u32.RegisterClipboardFormatW('HTML Format'), _cf_html(html_fragment) + b'\0')
            return
        finally:
            u32.CloseClipboard()
    raise OSError('not Windows')


def tree_rows(tree, only_selected=False):
    """Header + rows of a ttk.Treeview as shown (the '#0' tree column first when it is displayed)."""
    cols = list(tree['columns'])
    shown = str(tree['show'])
    with_tree = 'tree' in shown
    head = ([tree.heading('#0', 'text')] if with_tree else []) + [tree.heading(c, 'text') for c in cols]

    def walk(parent=''):
        for i in tree.get_children(parent):
            yield i
            yield from walk(i)
    items = list(tree.selection()) if only_selected else list(walk())
    rows = []
    for i in items:
        vals = list(tree.item(i, 'values'))
        rows.append(([tree.item(i, 'text')] if with_tree else []) + vals + [''] * (len(cols) - len(vals)))
    return [head] + rows


def bind_tree_copy(tree, title=''):
    """Right-click menu on a Treeview: copy the selected rows or the whole table as a table (Excel / OneNote)."""
    import tkinter as tk

    def do(only_selected):
        rows = tree_rows(tree, only_selected)
        t = title() if callable(title) else title
        copy(tree, tsv(rows), html_table(rows, title=t))

    def menu(e):
        row = tree.identify_row(e.y)
        if row and row not in tree.selection():
            tree.selection_set(row)
        m = tk.Menu(tree, tearoff=0)
        m.add_command(label='Copy selected rows (table for Excel / OneNote)', command=lambda: do(True),
                      state='normal' if tree.selection() else 'disabled')
        m.add_command(label='Copy whole table (table for Excel / OneNote)', command=lambda: do(False))
        m.tk_popup(e.x_root, e.y_root)
    tree.bind('<Button-3>', menu)
