"""
EventsTab and SummaryTab — reusable tkinter frames embedded in the main app.
"""

import sqlite3
import tkinter as tk
from tkinter import ttk
from typing import Callable

from tracker.db import (
    get_all_events,
    get_known_categories,
    get_known_sub_categories,
    get_summary,
    update_event_category,
)


# ---------------------------------------------------------------------------
# Filterable combobox
# ---------------------------------------------------------------------------

class FilterableCombobox(tk.Frame):
    """
    Entry + popup Listbox that filters as the user types.
    Selecting an option that doesn't exist in the list adds it as a new entry.
    The optional `on_change` callback fires with the new value whenever it is
    committed (Return / focus-out / list selection).
    """

    def __init__(
        self,
        parent: tk.Widget,
        options: list[str],
        on_change: Callable[[str], None] | None = None,
        placeholder: str = "",
        **kwargs,
    ):
        super().__init__(parent, **kwargs)
        self._all_options = list(options)
        self._on_change = on_change
        self._placeholder = placeholder

        self._var = tk.StringVar()
        self._var.trace_add("write", self._on_type)

        self._entry = tk.Entry(self, textvariable=self._var)
        self._entry.pack(fill="x")
        self._entry.bind("<FocusIn>", self._show_popup)
        self._entry.bind("<FocusOut>", self._on_focus_out)
        self._entry.bind("<Return>", self._commit)
        self._entry.bind("<Escape>", lambda _: self._hide_popup())
        self._entry.bind("<Down>", self._focus_list)

        self._popup: tk.Toplevel | None = None
        self._listbox: tk.Listbox | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self) -> str:
        return self._var.get().strip()

    def set(self, value: str) -> None:
        self._var.set(value or "")

    def set_options(self, options: list[str]) -> None:
        self._all_options = list(options)
        if self._listbox:
            self._populate(self._var.get())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_type(self, *_) -> None:
        self._show_popup()

    def _show_popup(self, event=None) -> None:
        text = self._var.get()
        filtered = self._filtered(text)

        if self._popup is None:
            self._popup = tk.Toplevel(self)
            self._popup.wm_overrideredirect(True)
            self._popup.wm_attributes("-topmost", True)

            frame = tk.Frame(self._popup, bd=1, relief="solid")
            frame.pack(fill="both", expand=True)

            scrollbar = tk.Scrollbar(frame, orient="vertical")
            self._listbox = tk.Listbox(
                frame,
                yscrollcommand=scrollbar.set,
                selectmode="single",
                activestyle="dotbox",
                height=8,
            )
            scrollbar.config(command=self._listbox.yview)
            self._listbox.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")

            self._listbox.bind("<ButtonRelease-1>", self._on_select)
            self._listbox.bind("<Return>", self._on_select)
            self._listbox.bind("<Escape>", lambda _: self._hide_popup())

        self._populate(text)
        self._reposition()

        if not filtered:
            self._hide_popup()

    def _reposition(self) -> None:
        if self._popup is None:
            return
        self.update_idletasks()
        x = self._entry.winfo_rootx()
        y = self._entry.winfo_rooty() + self._entry.winfo_height()
        w = self._entry.winfo_width()
        self._popup.wm_geometry(f"{w}x160+{x}+{y}")

    def _populate(self, text: str) -> None:
        if self._listbox is None:
            return
        self._listbox.delete(0, "end")
        for opt in self._filtered(text):
            self._listbox.insert("end", opt)
        # Offer "Add: <text>" if it's new and non-empty
        stripped = text.strip()
        if stripped and stripped.lower() not in [o.lower() for o in self._all_options]:
            self._listbox.insert("end", f'Add: "{stripped}"')

    def _filtered(self, text: str) -> list[str]:
        t = text.strip().lower()
        if not t:
            return list(self._all_options)
        return [o for o in self._all_options if t in o.lower()]

    def _focus_list(self, event=None) -> None:
        if self._listbox and self._listbox.size() > 0:
            self._listbox.focus_set()
            self._listbox.selection_set(0)

    def _on_select(self, event=None) -> None:
        if self._listbox is None:
            return
        sel = self._listbox.curselection()
        if not sel:
            return
        value = self._listbox.get(sel[0])
        # Strip the "Add: " prefix for new entries
        if value.startswith('Add: "') and value.endswith('"'):
            value = value[6:-1]
            if value not in self._all_options:
                self._all_options.append(value)
                self._all_options.sort()
        self._var.set(value)
        self._hide_popup()
        self._commit()

    def _on_focus_out(self, event=None) -> None:
        # Small delay so a listbox click registers before the popup closes
        self.after(150, self._check_focus_out)

    def _check_focus_out(self) -> None:
        focused = self.focus_get()
        if self._listbox and focused == self._listbox:
            return
        self._hide_popup()
        self._commit()

    def _commit(self, event=None) -> None:
        if self._on_change:
            self._on_change(self.get())

    def _hide_popup(self) -> None:
        if self._popup:
            self._popup.destroy()
            self._popup = None
            self._listbox = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


# ---------------------------------------------------------------------------
# Events tab
# ---------------------------------------------------------------------------

class EventsTab(tk.Frame):
    _COLS = ("started_at", "app_name", "window_title", "duration", "category", "sub_category")
    _HEADERS = ("Date / Time", "App", "Window Title", "Duration", "Category", "Sub-category")

    def __init__(self, parent: tk.Widget, conn: sqlite3.Connection):
        super().__init__(parent)
        self._conn = conn
        self._events: list[dict] = []
        self._selected_id: int | None = None

        self._build()
        self.refresh()

    def _build(self) -> None:
        # --- Toolbar ---
        toolbar = tk.Frame(self, pady=4)
        toolbar.pack(fill="x", padx=8)

        tk.Label(toolbar, text="Filter:").pack(side="left")
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        tk.Entry(toolbar, textvariable=self._filter_var, width=24).pack(side="left", padx=4)

        tk.Button(toolbar, text="Refresh", command=self.refresh).pack(side="right")

        # --- Treeview ---
        tree_frame = tk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=8)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=self._COLS,
            show="headings",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
            selectmode="browse",
        )
        vsb.config(command=self._tree.yview)
        hsb.config(command=self._tree.xview)

        widths = (140, 120, 280, 80, 130, 130)
        for col, header, width in zip(self._COLS, self._HEADERS, widths):
            self._tree.heading(col, text=header, command=lambda c=col: self._sort(c))
            self._tree.column(col, width=width, minwidth=60)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self._tree.tag_configure("uncategorized", foreground="#999999")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # --- Detail / edit panel ---
        detail = tk.LabelFrame(self, text="Assign Category", padx=8, pady=6)
        detail.pack(fill="x", padx=8, pady=(0, 8))

        tk.Label(detail, text="Category:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self._cat_box = FilterableCombobox(
            detail, options=[], on_change=self._on_category_change, width=28
        )
        self._cat_box.grid(row=0, column=1, sticky="ew", padx=(0, 16))

        tk.Label(detail, text="Sub-category:").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self._sub_box = FilterableCombobox(
            detail, options=[], on_change=self._on_sub_change, width=28
        )
        self._sub_box.grid(row=0, column=3, sticky="ew")

        tk.Button(detail, text="Save", command=self._save).grid(row=0, column=4, padx=(12, 0))
        tk.Button(detail, text="Clear", command=self._clear_category).grid(row=0, column=5, padx=(4, 0))

        detail.columnconfigure(1, weight=1)
        detail.columnconfigure(3, weight=1)

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._events = get_all_events(self._conn)
        cats = get_known_categories(self._conn)
        subs = get_known_sub_categories(self._conn)
        self._cat_box.set_options(cats)
        self._sub_box.set_options(subs)
        self._apply_filter()

    def _apply_filter(self) -> None:
        q = self._filter_var.get().lower()
        self._tree.delete(*self._tree.get_children())
        for ev in self._events:
            if q and q not in (ev["app_name"] or "").lower() and q not in (ev["window_title"] or "").lower():
                continue
            tag = "" if ev["category"] else "uncategorized"
            self._tree.insert(
                "",
                "end",
                iid=str(ev["id"]),
                values=(
                    ev["started_at"][:19].replace("T", " "),
                    ev["app_name"],
                    ev["window_title"],
                    _fmt_duration(ev["duration_seconds"]),
                    ev["category"] or "",
                    ev["sub_category"] or "",
                ),
                tags=(tag,),
            )

    def _sort(self, col: str) -> None:
        reverse = getattr(self, "_sort_reverse", False)
        self._sort_reverse = not reverse
        self._events.sort(
            key=lambda e: (e.get(col) or ""),
            reverse=reverse,
        )
        self._apply_filter()

    def _on_select(self, event=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        iid = int(sel[0])
        self._selected_id = iid
        ev = next((e for e in self._events if e["id"] == iid), None)
        if ev is None:
            return
        self._cat_box.set(ev["category"] or "")
        self._sub_box.set(ev["sub_category"] or "")

    def _on_category_change(self, value: str) -> None:
        subs = get_known_sub_categories(self._conn, value or None)
        self._sub_box.set_options(subs)

    def _on_sub_change(self, value: str) -> None:
        pass

    def _save(self) -> None:
        if self._selected_id is None:
            return
        cat = self._cat_box.get() or None
        sub = self._sub_box.get() or None
        update_event_category(self._conn, self._selected_id, cat, sub)
        # Patch local cache so refresh is instant
        for ev in self._events:
            if ev["id"] == self._selected_id:
                ev["category"] = cat
                ev["sub_category"] = sub
        self._apply_filter()
        # Refresh combobox option lists
        self._cat_box.set_options(get_known_categories(self._conn))
        self._sub_box.set_options(get_known_sub_categories(self._conn, cat))

    def _clear_category(self) -> None:
        if self._selected_id is None:
            return
        self._cat_box.set("")
        self._sub_box.set("")
        self._save()


# ---------------------------------------------------------------------------
# Summary tab
# ---------------------------------------------------------------------------

class SummaryTab(tk.Frame):
    _COLS = ("category", "sub_category", "total_time", "event_count")
    _HEADERS = ("Category", "Sub-category", "Total Time", "Events")

    def __init__(self, parent: tk.Widget, conn: sqlite3.Connection):
        super().__init__(parent)
        self._conn = conn
        self._build()
        self.refresh()

    def _build(self) -> None:
        toolbar = tk.Frame(self, pady=4)
        toolbar.pack(fill="x", padx=8)
        tk.Button(toolbar, text="Refresh", command=self.refresh).pack(side="right")

        tree_frame = tk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=self._COLS,
            show="headings",
            yscrollcommand=vsb.set,
            selectmode="none",
        )
        vsb.config(command=self._tree.yview)

        widths = (180, 180, 120, 80)
        for col, header, width in zip(self._COLS, self._HEADERS, widths):
            self._tree.heading(col, text=header)
            self._tree.column(col, width=width, minwidth=60)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self._tree.tag_configure("category_row", font=("TkDefaultFont", 10, "bold"))
        self._tree.tag_configure("uncategorized", foreground="#999999")

    def refresh(self) -> None:
        self._tree.delete(*self._tree.get_children())
        rows = get_summary(self._conn)

        # Group by category
        from itertools import groupby
        for cat, group in groupby(rows, key=lambda r: r["category"]):
            items = list(group)
            cat_total = sum(i["total_seconds"] for i in items)
            cat_count = sum(i["event_count"] for i in items)
            tag = "uncategorized" if cat == "(Uncategorized)" else "category_row"

            parent = self._tree.insert(
                "",
                "end",
                values=(cat, "", _fmt_duration(cat_total), cat_count),
                tags=(tag,),
                open=True,
            )
            for item in items:
                if item["sub_category"]:
                    self._tree.insert(
                        parent,
                        "end",
                        values=("", item["sub_category"], _fmt_duration(item["total_seconds"]), item["event_count"]),
                    )


