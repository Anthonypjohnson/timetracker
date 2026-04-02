"""
EventsTab, SummaryTab, RulesTab, and CategoriesTab — reusable tkinter frames embedded in the main app.
"""

import csv
import json
import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from tracker.db import (
    apply_rules_to_uncategorized,
    auto_categorize_event,
    bulk_update_categories,
    create_category,
    create_sub_category,
    delete_category,
    delete_sub_category,
    ensure_category_exists,
    export_data,
    get_all_events,
    get_event_dates,
    get_known_categories,
    get_known_sub_categories,
    get_rules,
    get_summary,
    import_data,
    insert_event,
    insert_rule,
    delete_rule,
    update_rule,
    get_category_excluded,
    get_sub_category_excluded,
    set_category_excluded,
    set_sub_category_excluded,
    rename_category,
    rename_sub_category,
    update_event_category,
)
from tracker.models import WindowEvent

_SUBTEXT = "#6b7280"
_DANGER = "#dc2626"


# ---------------------------------------------------------------------------
# Filterable combobox
# ---------------------------------------------------------------------------

class FilterableCombobox(ttk.Frame):
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

        self._suppress = False
        self._var = tk.StringVar()
        self._var.trace_add("write", self._on_type)

        self._entry = ttk.Entry(self, textvariable=self._var)
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
        self._suppress = True
        self._var.set(value or "")
        self._suppress = False

    def set_options(self, options: list[str]) -> None:
        self._all_options = list(options)
        if self._listbox:
            self._populate(self._var.get())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_type(self, *_) -> None:
        if not self._suppress:
            self._show_popup()

    def _show_popup(self, event=None) -> None:
        text = self._var.get()
        filtered = self._filtered(text)

        if self._popup is None:
            self._popup = tk.Toplevel(self)
            self._popup.wm_overrideredirect(True)
            self._popup.wm_attributes("-topmost", True)

            frame = tk.Frame(self._popup, bd=1, relief="solid", bg="#d1d5db")
            frame.pack(fill="both", expand=True)

            scrollbar = ttk.Scrollbar(frame, orient="vertical")
            self._listbox = tk.Listbox(
                frame,
                yscrollcommand=scrollbar.set,
                selectmode="single",
                activestyle="none",
                height=8,
                font=("Segoe UI", 9),
                bg="#ffffff",
                fg="#1a1a1a",
                selectbackground="#dbeafe",
                selectforeground="#1a1a1a",
                borderwidth=0,
                relief="flat",
                highlightthickness=0,
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
        self._suppress = True
        self._var.set(value)
        self._suppress = False
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

class EventsTab(ttk.Frame):
    _COLS = ("started_at", "app_name", "window_title", "duration", "category", "sub_category")
    _HEADERS = ("Date / Time", "App", "Window Title", "Duration", "Category", "Sub-category")

    def __init__(
        self,
        parent: tk.Widget,
        conn: sqlite3.Connection,
        on_event_added: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self._conn = conn
        self._on_event_added = on_event_added
        self._events: list[dict] = []
        self._selected_ids: list[int] = []
        self._pending: dict[int, tuple[str | None, str | None]] = {}

        self._build()
        self.refresh()

    def _build(self) -> None:
        # --- Toolbar ---
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=8, pady=6)

        ttk.Label(toolbar, text="Day:").pack(side="left")
        self._date_var = tk.StringVar(value="All")
        self._date_cb = ttk.Combobox(
            toolbar, textvariable=self._date_var, state="readonly", width=12
        )
        self._date_cb.pack(side="left", padx=(4, 10))
        self._date_cb.bind("<<ComboboxSelected>>", lambda *_: self.refresh())

        ttk.Label(toolbar, text="Filter:").pack(side="left")
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(toolbar, textvariable=self._filter_var, width=24).pack(side="left", padx=(4, 0))

        self._uncat_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            toolbar, text="Uncategorized only",
            variable=self._uncat_only_var,
            command=self._apply_filter,
        ).pack(side="left", padx=(10, 0))

        ttk.Button(toolbar, text="Refresh", command=self.refresh).pack(side="right")
        ttk.Button(toolbar, text="Add Event…", command=self._open_add_event_dialog).pack(
            side="right", padx=(0, 4)
        )
        ttk.Button(toolbar, text="Export CSV…", command=self._export_csv).pack(
            side="right", padx=(0, 4)
        )
        self._commit_btn = ttk.Button(
            toolbar, text="Commit", state="disabled", command=self._commit,
            style="Accent.TButton",
        )
        self._commit_btn.pack(side="right", padx=(0, 4))

        # --- Treeview ---
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=8)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=self._COLS,
            show="headings",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
            selectmode="extended",
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

        self._tree.tag_configure("uncategorized", foreground="#9ca3af")
        self._tree.tag_configure("pending", foreground="#0078d4")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # --- Detail / edit panel ---
        detail = ttk.LabelFrame(self, text="Assign Category", padding=(8, 6))
        detail.pack(fill="x", padx=8, pady=(6, 8))

        ttk.Label(detail, text="Category:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self._cat_box = FilterableCombobox(
            detail, options=[], on_change=self._on_category_change, width=28
        )
        self._cat_box.grid(row=0, column=1, sticky="ew", padx=(0, 16))

        ttk.Label(detail, text="Sub-category:").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self._sub_box = FilterableCombobox(
            detail, options=[], on_change=self._on_sub_change, width=28
        )
        self._sub_box.grid(row=0, column=3, sticky="ew")

        ttk.Button(detail, text="Apply", command=self._apply,
                   style="Accent.TButton").grid(row=0, column=4, padx=(12, 0))
        ttk.Button(detail, text="Clear", command=self._clear_category).grid(
            row=0, column=5, padx=(4, 0)
        )
        self._create_rule_btn = ttk.Button(
            detail, text="Create Rule…", command=self._open_create_rule_dialog, state="disabled"
        )
        self._create_rule_btn.grid(row=0, column=6, padx=(12, 0))

        detail.columnconfigure(1, weight=1)
        detail.columnconfigure(3, weight=1)

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        # Update date picker options
        dates = get_event_dates(self._conn)
        self._date_cb["values"] = ["All"] + dates
        selected = self._date_var.get()
        if selected not in ("All",) + tuple(dates):
            self._date_var.set("All")

        date_filter = self._date_var.get()
        self._events = get_all_events(self._conn, date_filter if date_filter != "All" else None)
        # Re-overlay any pending (unsaved) changes onto the local cache
        for ev in self._events:
            if ev["id"] in self._pending:
                cat, sub = self._pending[ev["id"]]
                ev["category"] = cat
                ev["sub_category"] = sub
        cats = get_known_categories(self._conn)
        subs = get_known_sub_categories(self._conn)
        self._cat_box.set_options(cats)
        self._sub_box.set_options(subs)
        self._apply_filter()

    def _apply_filter(self) -> None:
        q = self._filter_var.get().lower()
        uncat_only = self._uncat_only_var.get()
        self._tree.delete(*self._tree.get_children())
        for ev in self._events:
            if q and q not in (ev["app_name"] or "").lower() and q not in (ev["window_title"] or "").lower():
                continue
            if uncat_only and (ev["category"] or ev["id"] in self._pending):
                continue
            if ev["id"] in self._pending:
                tag = "pending"
            elif not ev["category"]:
                tag = "uncategorized"
            else:
                tag = ""
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
        self._events.sort(key=lambda e: (e.get(col) or ""), reverse=reverse)
        self._apply_filter()

    def _on_select(self, event=None) -> None:
        sel = self._tree.selection()
        if not sel:
            self._selected_ids = []
            self._create_rule_btn.config(state="disabled")
            return
        self._selected_ids = [int(iid) for iid in sel]
        if len(sel) == 1:
            ev = next((e for e in self._events if e["id"] == self._selected_ids[0]), None)
            if ev:
                self._cat_box.set(ev["category"] or "")
                self._sub_box.set(ev["sub_category"] or "")
            self._create_rule_btn.config(state="normal")
        else:
            self._cat_box.set("")
            self._sub_box.set("")
            self._create_rule_btn.config(state="disabled")

    def _on_category_change(self, value: str) -> None:
        subs = get_known_sub_categories(self._conn, value or None)
        self._sub_box.set_options(subs)

    def _on_sub_change(self, value: str) -> None:
        pass

    def _apply(self) -> None:
        """Stage category changes for selected events (not yet written to DB)."""
        if not self._selected_ids:
            return
        cat = self._cat_box.get() or None
        sub = self._sub_box.get() or None
        for eid in self._selected_ids:
            self._pending[eid] = (cat, sub)
            for ev in self._events:
                if ev["id"] == eid:
                    ev["category"] = cat
                    ev["sub_category"] = sub
        self._apply_filter()
        self._update_commit_btn()

    def _clear_category(self) -> None:
        if not self._selected_ids:
            return
        self._cat_box.set("")
        self._sub_box.set("")
        self._apply()

    def _commit(self) -> None:
        """Write all staged changes to the database."""
        if not self._pending:
            return
        bulk_update_categories(self._conn, self._pending)
        self._pending.clear()
        self.refresh()
        self._update_commit_btn()

    def _update_commit_btn(self) -> None:
        n = len(self._pending)
        self._commit_btn.config(
            text=f"Commit ({n})" if n else "Commit",
            state="normal" if n else "disabled",
            style="Accent.TButton" if n else "TButton",
        )

    def _open_create_rule_dialog(self) -> None:
        if len(self._selected_ids) != 1:
            return
        ev = next((e for e in self._events if e["id"] == self._selected_ids[0]), None)
        if ev is None:
            return

        dlg = tk.Toplevel(self)
        dlg.title("Create Rule")
        dlg.resizable(False, False)
        dlg.grab_set()

        form = ttk.Frame(dlg, padding=12)
        form.pack(fill="both", expand=True)

        ttk.Label(form, text="App Pattern:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        app_var = tk.StringVar(value=ev["app_name"] or "")
        ttk.Entry(form, textvariable=app_var, width=36).grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Title Pattern:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=4)
        title_var = tk.StringVar(value=ev["window_title"] or "")
        ttk.Entry(form, textvariable=title_var, width=36).grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Category:").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=4)
        cats = get_known_categories(self._conn)
        cat_box = FilterableCombobox(form, options=cats, width=34)
        cat_box.set(ev["category"] or "")
        cat_box.grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Sub-category:").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=4)
        subs = get_known_sub_categories(self._conn)
        sub_box = FilterableCombobox(form, options=subs, width=34)
        sub_box.set(ev["sub_category"] or "")
        sub_box.grid(row=3, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Priority:").grid(row=4, column=0, sticky="w", padx=(0, 6), pady=4)
        priority_var = tk.IntVar(value=0)
        ttk.Spinbox(form, textvariable=priority_var, from_=0, to=9999, width=8).grid(
            row=4, column=1, sticky="w", pady=4
        )

        ttk.Label(
            form,
            text="Leave a pattern blank to match any value.",
            foreground=_SUBTEXT,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 8))

        status_var = tk.StringVar()
        ttk.Label(form, textvariable=status_var, foreground=_DANGER).grid(
            row=6, column=0, columnspan=2, sticky="w"
        )

        def _save() -> None:
            app_pat = app_var.get().strip() or None
            title_pat = title_var.get().strip() or None
            cat = cat_box.get()
            sub = sub_box.get() or None
            try:
                priority = int(priority_var.get())
            except (ValueError, tk.TclError):
                priority = 0
            if not app_pat and not title_pat:
                status_var.set("At least one pattern is required.")
                return
            if not cat:
                status_var.set("Category is required.")
                return
            insert_rule(self._conn, app_pat, title_pat, cat, sub, priority)
            dlg.destroy()

        btn_frame = ttk.Frame(form)
        btn_frame.grid(row=7, column=0, columnspan=2, sticky="e", pady=(4, 0))
        ttk.Button(btn_frame, text="Save Rule", command=_save, style="Accent.TButton").pack(side="left")
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side="left", padx=(6, 0))

        form.columnconfigure(1, weight=1)
        dlg.update_idletasks()
        dlg.geometry(f"+{self.winfo_rootx() + 80}+{self.winfo_rooty() + 80}")

    def _open_add_event_dialog(self) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("Add Event")
        dlg.resizable(False, False)
        dlg.grab_set()

        form = ttk.Frame(dlg, padding=12)
        form.pack(fill="both", expand=True)

        now = datetime.now()
        default_dt = now.strftime("%Y-%m-%d %H:%M")

        ttk.Label(form, text="App Name:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        app_var = tk.StringVar()
        ttk.Entry(form, textvariable=app_var, width=36).grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Window Title:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=4)
        title_var = tk.StringVar()
        ttk.Entry(form, textvariable=title_var, width=36).grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Start (YYYY-MM-DD HH:MM):").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=4)
        start_var = tk.StringVar(value=default_dt)
        ttk.Entry(form, textvariable=start_var, width=20).grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(form, text="Duration (minutes):").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=4)
        dur_var = tk.IntVar(value=5)
        ttk.Spinbox(form, textvariable=dur_var, from_=1, to=9999, width=8).grid(
            row=3, column=1, sticky="w", pady=4
        )

        ttk.Label(form, text="Category:").grid(row=4, column=0, sticky="w", padx=(0, 6), pady=4)
        cats = get_known_categories(self._conn)
        cat_box = FilterableCombobox(form, options=cats, width=34)
        cat_box.grid(row=4, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Sub-category:").grid(row=5, column=0, sticky="w", padx=(0, 6), pady=4)
        subs = get_known_sub_categories(self._conn)
        sub_box = FilterableCombobox(form, options=subs, width=34)
        sub_box.grid(row=5, column=1, sticky="ew", pady=4)

        status_var = tk.StringVar()
        ttk.Label(form, textvariable=status_var, foreground=_DANGER).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )

        def _save() -> None:
            app = app_var.get().strip()
            title = title_var.get().strip()
            start_str = start_var.get().strip()
            if not app:
                status_var.set("App Name is required.")
                return
            try:
                started_at = datetime.strptime(start_str, "%Y-%m-%d %H:%M")
            except ValueError:
                status_var.set("Invalid date/time. Use YYYY-MM-DD HH:MM.")
                return
            try:
                duration = max(1, int(dur_var.get())) * 60
            except (ValueError, tk.TclError):
                status_var.set("Duration must be a number.")
                return
            cat = cat_box.get() or None
            sub = sub_box.get() or None
            event = WindowEvent(
                app_name=app,
                window_title=title,
                started_at=started_at,
                duration_seconds=duration,
            )
            event_id = insert_event(self._conn, event)
            if cat:
                ensure_category_exists(self._conn, cat, sub)
                from tracker.db import update_event_category as _uec
                _uec(self._conn, event_id, cat, sub)
            else:
                auto_categorize_event(self._conn, event_id, app, title)
            dlg.destroy()
            self.refresh()
            if self._on_event_added:
                self._on_event_added()

        btn_frame = ttk.Frame(form)
        btn_frame.grid(row=7, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(btn_frame, text="Add Event", command=_save, style="Accent.TButton").pack(side="left")
        ttk.Button(btn_frame, text="Cancel", command=dlg.destroy).pack(side="left", padx=(6, 0))

        form.columnconfigure(1, weight=1)
        dlg.update_idletasks()
        dlg.geometry(f"+{self.winfo_rootx() + 80}+{self.winfo_rooty() + 80}")

    def _export_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Export events as CSV",
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "id", "app_name", "window_title", "started_at",
                    "duration_seconds", "category", "sub_category",
                ],
            )
            writer.writeheader()
            writer.writerows(self._events)


# ---------------------------------------------------------------------------
# Summary tab
# ---------------------------------------------------------------------------

class SummaryTab(ttk.Frame):
    _COLS = ("category", "sub_category", "total_time", "event_count")
    _HEADERS = ("Category", "Sub-category", "Total Time", "Events")

    def __init__(self, parent: tk.Widget, conn: sqlite3.Connection):
        super().__init__(parent)
        self._conn = conn
        self._rows: list[dict] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=8, pady=6)

        ttk.Label(toolbar, text="Day:").pack(side="left")
        self._date_var = tk.StringVar(value="All")
        self._date_cb = ttk.Combobox(
            toolbar, textvariable=self._date_var, state="readonly", width=12
        )
        self._date_cb.pack(side="left", padx=(4, 10))
        self._date_cb.bind("<<ComboboxSelected>>", lambda *_: self.refresh())

        ttk.Button(toolbar, text="Refresh", command=self.refresh).pack(side="right")
        ttk.Button(toolbar, text="Export CSV…", command=self._export_csv).pack(side="right", padx=(0, 4))

        tree_frame = ttk.Frame(self)
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

        self._tree.tag_configure("category_row", font=("Segoe UI", 9, "bold"))
        self._tree.tag_configure("uncategorized", foreground="#9ca3af")

        footer = ttk.Frame(self)
        footer.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(footer, text="Total:").pack(side="left")
        self._total_var = tk.StringVar(value="")
        ttk.Label(footer, textvariable=self._total_var, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(4, 0))

    def refresh(self) -> None:
        self._tree.delete(*self._tree.get_children())
        dates = get_event_dates(self._conn)
        self._date_cb["values"] = ["All"] + dates
        selected = self._date_var.get()
        if selected not in ("All",) + tuple(dates):
            self._date_var.set("All")
        date_filter = self._date_var.get()
        rows = get_summary(self._conn, date_filter if date_filter != "All" else None)
        self._rows = rows

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

        grand_total = sum(r["total_seconds"] for r in rows)
        self._total_var.set(_fmt_duration(grand_total))

    def _export_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Export summary as CSV",
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Category", "Sub-category", "Total Time", "Total Seconds", "Events"])
            for row in self._rows:
                writer.writerow([
                    row["category"],
                    row["sub_category"] or "",
                    _fmt_duration(row["total_seconds"]),
                    row["total_seconds"],
                    row["event_count"],
                ])


# ---------------------------------------------------------------------------
# Rules tab
# ---------------------------------------------------------------------------

class RulesTab(ttk.Frame):
    """Manage auto-categorization rules and apply them to existing events."""

    _COLS = ("app_name_pattern", "window_title_pattern", "category", "sub_category", "priority")
    _HEADERS = ("App Pattern", "Title Pattern", "Category", "Sub-category", "Priority")

    def __init__(
        self,
        parent: tk.Widget,
        conn: sqlite3.Connection,
        on_data_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._on_data_changed = on_data_changed
        self._editing_id: int | None = None
        self._rules: list[dict] = []
        self._sort_col: str | None = None
        self._sort_reverse: bool = False
        self._build()
        self.refresh()

    def _build(self) -> None:
        # --- Add/Edit-rule form ---
        self._form_frame = ttk.LabelFrame(self, text="Add Rule", padding=(8, 6))
        form = self._form_frame
        form.pack(fill="x", padx=8, pady=(8, 4))

        # Row 0: App Pattern + Title Pattern
        ttk.Label(form, text="App Pattern:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self._app_pattern_var = tk.StringVar()
        ttk.Entry(form, textvariable=self._app_pattern_var, width=22).grid(
            row=0, column=1, sticky="ew", padx=(0, 12)
        )

        ttk.Label(form, text="Title Pattern:").grid(row=0, column=2, sticky="w", padx=(0, 4))
        self._title_pattern_var = tk.StringVar()
        ttk.Entry(form, textvariable=self._title_pattern_var, width=22).grid(
            row=0, column=3, sticky="ew", padx=(0, 12)
        )

        ttk.Label(form, text="Category:").grid(row=0, column=4, sticky="w", padx=(0, 4))
        self._cat_box = FilterableCombobox(form, options=[], width=18)
        self._cat_box.grid(row=0, column=5, sticky="ew", padx=(0, 12))

        ttk.Label(form, text="Sub-category:").grid(row=0, column=6, sticky="w", padx=(0, 4))
        self._sub_box = FilterableCombobox(form, options=[], width=18)
        self._sub_box.grid(row=0, column=7, sticky="ew", padx=(0, 12))

        ttk.Label(form, text="Priority:").grid(row=0, column=8, sticky="w", padx=(0, 4))
        self._priority_var = tk.IntVar(value=0)
        ttk.Spinbox(
            form, textvariable=self._priority_var, from_=0, to=9999, width=6
        ).grid(row=0, column=9, sticky="ew", padx=(0, 12))

        self._submit_btn = ttk.Button(form, text="Add Rule", command=self._submit_rule,
                                      style="Accent.TButton")
        self._submit_btn.grid(row=0, column=10)
        self._cancel_btn = ttk.Button(form, text="Cancel", command=self._cancel_edit)
        self._cancel_btn.grid(row=0, column=11, padx=(4, 0))
        self._cancel_btn.grid_remove()

        ttk.Label(
            form, text="Leave a pattern blank to match any value for that field.",
            foreground=_SUBTEXT,
        ).grid(row=1, column=0, columnspan=11, sticky="w", pady=(4, 0))

        for col in (1, 3, 5, 7):
            form.columnconfigure(col, weight=1)

        # --- Toolbar ---
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=8, pady=4)

        ttk.Button(toolbar, text="Edit Selected", command=self._load_rule_for_edit).pack(side="left")
        ttk.Button(toolbar, text="Delete Selected", command=self._delete_rule).pack(side="left", padx=(6, 0))
        ttk.Button(
            toolbar, text="Apply to all uncategorized", command=self._apply_all
        ).pack(side="left", padx=(6, 0))
        self._status_var = tk.StringVar()
        ttk.Label(toolbar, textvariable=self._status_var, foreground=_SUBTEXT).pack(
            side="left", padx=(12, 0)
        )
        ttk.Button(toolbar, text="Refresh", command=self.refresh).pack(side="right")
        ttk.Button(toolbar, text="Import…", command=self._import_json).pack(side="right", padx=(0, 4))
        ttk.Button(toolbar, text="Export…", command=self._export_json).pack(side="right", padx=(0, 4))
        ttk.Label(toolbar, text="Filter:").pack(side="right", padx=(8, 2))
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(toolbar, textvariable=self._filter_var, width=20).pack(side="right")

        # --- Treeview ---
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=self._COLS,
            show="headings",
            yscrollcommand=vsb.set,
            selectmode="extended",
        )
        vsb.config(command=self._tree.yview)

        widths = (160, 200, 140, 140, 70)
        for col, header, width in zip(self._COLS, self._HEADERS, widths):
            self._tree.heading(col, text=header, command=lambda c=col: self._sort(c))
            self._tree.column(col, width=width, minwidth=50)
        self._tree.column("priority", anchor="center")

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self._tree.bind("<Double-1>", self._on_double_click)

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        cats = get_known_categories(self._conn)
        subs = get_known_sub_categories(self._conn)
        self._cat_box.set_options(cats)
        self._sub_box.set_options(subs)
        self._rules = list(get_rules(self._conn))
        self._apply_filter()

    def _apply_filter(self) -> None:
        q = self._filter_var.get().lower()
        self._tree.delete(*self._tree.get_children())
        rules = self._rules
        if self._sort_col is not None:
            key = self._sort_col

            def _sort_key(r: dict):
                v = r.get(key) or ""
                if key == "priority":
                    try:
                        return int(v)
                    except (ValueError, TypeError):
                        return 0
                return str(v).lower()

            rules = sorted(rules, key=_sort_key, reverse=self._sort_reverse)
        for rule in rules:
            app_pat = rule["app_name_pattern"] or ""
            title_pat = rule["window_title_pattern"] or ""
            cat = rule["category"]
            sub = rule["sub_category"] or ""
            if q and not any(q in v.lower() for v in (app_pat, title_pat, cat, sub)):
                continue
            self._tree.insert(
                "", "end",
                iid=str(rule["id"]),
                values=(app_pat, title_pat, cat, sub, rule["priority"]),
            )

    def _sort(self, col: str) -> None:
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = col
            self._sort_reverse = False
        # Update heading arrows
        for c, h in zip(self._COLS, self._HEADERS):
            arrow = (" ▲" if not self._sort_reverse else " ▼") if c == col else ""
            self._tree.heading(c, text=h + arrow)
        self._apply_filter()

    def _export_json(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Export categories and rules",
        )
        if not path:
            return
        data = export_data(self._conn)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        messagebox.showinfo(
            "Export complete",
            f"Exported {len(data['categories'])} categories and {len(data['rules'])} rules.",
        )

    def _import_json(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Import categories and rules",
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            messagebox.showerror("Import failed", f"Could not read file:\n{exc}")
            return
        try:
            cats_added, rules_added = import_data(self._conn, data)
        except Exception as exc:
            messagebox.showerror("Import failed", f"Error importing data:\n{exc}")
            return
        messagebox.showinfo(
            "Import complete",
            f"Added {cats_added} categories/sub-categories and {rules_added} rules.",
        )
        self.refresh()
        if self._on_data_changed:
            self._on_data_changed()

    def _submit_rule(self) -> None:
        app_pat = self._app_pattern_var.get().strip() or None
        title_pat = self._title_pattern_var.get().strip() or None
        cat = self._cat_box.get()
        sub = self._sub_box.get() or None
        try:
            priority = int(self._priority_var.get())
        except (ValueError, tk.TclError):
            priority = 0
        if not app_pat and not title_pat:
            self._status_var.set("At least one pattern (App or Title) is required.")
            return
        if not cat:
            self._status_var.set("Category is required.")
            return
        if self._editing_id is not None:
            update_rule(self._conn, self._editing_id, app_pat, title_pat, cat, sub, priority)
        else:
            insert_rule(self._conn, app_pat, title_pat, cat, sub, priority)
        self._clear_form()
        self.refresh()

    def _load_rule_for_edit(self) -> None:
        sel = self._tree.selection()
        if not sel or len(sel) != 1:
            return
        rule_id = int(sel[0])
        values = self._tree.item(sel[0], "values")
        # values order: app_pattern, title_pattern, category, sub_category, priority
        self._app_pattern_var.set(values[0])
        self._title_pattern_var.set(values[1])
        self._cat_box.set(values[2])
        self._sub_box.set(values[3])
        try:
            self._priority_var.set(int(values[4]))
        except (ValueError, tk.TclError):
            self._priority_var.set(0)
        self._editing_id = rule_id
        self._form_frame.config(text="Edit Rule")
        self._submit_btn.config(text="Save Changes")
        self._cancel_btn.grid()
        self._status_var.set("")

    def _cancel_edit(self) -> None:
        self._clear_form()

    def _clear_form(self) -> None:
        self._editing_id = None
        self._app_pattern_var.set("")
        self._title_pattern_var.set("")
        self._cat_box.set("")
        self._sub_box.set("")
        self._priority_var.set(0)
        self._status_var.set("")
        self._form_frame.config(text="Add Rule")
        self._submit_btn.config(text="Add Rule")
        self._cancel_btn.grid_remove()

    def _on_double_click(self, _event: tk.Event) -> None:
        if len(self._tree.selection()) == 1:
            self._load_rule_for_edit()

    def _delete_rule(self) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        if len(sel) > 1:
            if not messagebox.askyesno("Delete Rules", f"Delete {len(sel)} selected rules?"):
                return
        for iid in sel:
            delete_rule(self._conn, int(iid))
        self._clear_form()
        self._status_var.set("")
        self.refresh()

    def _apply_all(self) -> None:
        count = apply_rules_to_uncategorized(self._conn)
        self._status_var.set(f"Categorized {count} event(s).")
        self.refresh()


# ---------------------------------------------------------------------------
# Categories tab
# ---------------------------------------------------------------------------

class CategoriesTab(ttk.Frame):
    """
    Manage categories and sub-categories.
    Tree shows categories (bold) with their sub-categories as children.
    Selecting a category or sub-category activates the rename/delete form.
    """

    # iid prefixes to distinguish rows
    _CAT = "C|||"
    _SUB = "S|||"

    def __init__(
        self,
        parent: tk.Widget,
        conn: sqlite3.Connection,
        on_data_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._on_data_changed = on_data_changed
        self._sel_category: str | None = None
        self._sel_sub: str | None = None
        self._cat_data: dict[str, tuple[int, bool, list[tuple[str, int, bool]]]] = {}
        self._build()
        self.refresh()

    def _build(self) -> None:
        # --- Top: create forms ---
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=(8, 4))

        cat_frame = ttk.LabelFrame(top, text="New Category", padding=(8, 6))
        cat_frame.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._new_cat_var = tk.StringVar()
        ttk.Entry(cat_frame, textvariable=self._new_cat_var, width=22).pack(side="left", padx=(0, 6))
        ttk.Button(cat_frame, text="Create", command=self._create_category,
                   style="Accent.TButton").pack(side="left")

        sub_frame = ttk.LabelFrame(top, text="New Sub-category  (select a category first)", padding=(8, 6))
        sub_frame.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self._new_sub_var = tk.StringVar()
        ttk.Entry(sub_frame, textvariable=self._new_sub_var, width=22).pack(side="left", padx=(0, 6))
        ttk.Button(sub_frame, text="Create", command=self._create_sub_category,
                   style="Accent.TButton").pack(side="left")

        # --- Filter / toolbar ---
        filter_frame = ttk.Frame(self)
        filter_frame.pack(fill="x", padx=8, pady=(0, 2))
        ttk.Label(filter_frame, text="Filter:").pack(side="left")
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(filter_frame, textvariable=self._filter_var, width=24).pack(side="left", padx=(4, 0))
        ttk.Button(filter_frame, text="Refresh", command=self.refresh).pack(side="right")
        ttk.Button(filter_frame, text="Import…", command=self._import_json).pack(side="right", padx=(0, 4))
        ttk.Button(filter_frame, text="Export…", command=self._export_json).pack(side="right", padx=(0, 4))

        # --- Middle: tree ---
        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=8, pady=4)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=("events",),
            show="tree headings",
            yscrollcommand=vsb.set,
            selectmode="browse",
        )
        vsb.config(command=self._tree.yview)
        self._tree.heading("#0", text="Name")
        self._tree.heading("events", text="Events")
        self._tree.column("#0", width=300, minwidth=120, stretch=True)
        self._tree.column("events", width=70, minwidth=50, anchor="center", stretch=False)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self._tree.tag_configure("category", font=("Segoe UI", 9, "bold"))
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # --- Bottom: edit panel ---
        edit = ttk.LabelFrame(self, text="Rename / Delete selected", padding=(8, 6))
        edit.pack(fill="x", padx=8, pady=(0, 8))

        ttk.Label(edit, text="New name:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self._edit_var = tk.StringVar()
        ttk.Entry(edit, textvariable=self._edit_var, width=28).grid(
            row=0, column=1, sticky="ew", padx=(0, 8)
        )
        ttk.Button(edit, text="Rename", command=self._rename).grid(row=0, column=2, padx=(0, 4))
        ttk.Button(edit, text="Delete", style="Danger.TButton", command=self._delete).grid(
            row=0, column=3
        )
        self._excluded_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            edit, text="Exclude from summary", variable=self._excluded_var,
            command=self._toggle_excluded,
        ).grid(row=0, column=4, padx=(12, 0))
        self._status_var = tk.StringVar()
        ttk.Label(edit, textvariable=self._status_var, foreground=_SUBTEXT).grid(
            row=0, column=5, padx=(12, 0), sticky="w"
        )
        edit.columnconfigure(1, weight=1)

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._cat_data = {}
        for cat in get_known_categories(self._conn):
            cat_count = self._conn.execute(
                "SELECT COUNT(*) FROM window_events WHERE category = ?", (cat,)
            ).fetchone()[0]
            cat_excluded = get_category_excluded(self._conn, cat)
            subs: list[tuple[str, int, bool]] = []
            for sub in get_known_sub_categories(self._conn, cat):
                sub_count = self._conn.execute(
                    "SELECT COUNT(*) FROM window_events WHERE category = ? AND sub_category = ?",
                    (cat, sub),
                ).fetchone()[0]
                sub_excluded = get_sub_category_excluded(self._conn, cat, sub)
                subs.append((sub, sub_count, sub_excluded))
            self._cat_data[cat] = (cat_count, cat_excluded, subs)
        self._apply_filter()

    def _apply_filter(self) -> None:
        q = self._filter_var.get().lower()
        self._tree.delete(*self._tree.get_children())
        self._tree.tag_configure("excluded", foreground="#9ca3af")
        self._tree.tag_configure("category_excluded", font=("Segoe UI", 9, "bold"), foreground="#9ca3af")
        for cat, (cat_count, cat_excluded, subs) in self._cat_data.items():
            cat_matches = not q or q in cat.lower()
            matching_subs = [(s, c, e) for s, c, e in subs if not q or q in s.lower()]
            if not cat_matches and not matching_subs:
                continue
            cat_tags = ("category_excluded",) if cat_excluded else ("category",)
            parent = self._tree.insert(
                "", "end",
                iid=f"{self._CAT}{cat}",
                text=cat,
                values=(cat_count,),
                tags=cat_tags,
                open=True,
            )
            shown_subs = subs if cat_matches else matching_subs
            for sub, sub_count, sub_excluded in shown_subs:
                sub_tags = ("excluded",) if sub_excluded else ()
                self._tree.insert(
                    parent, "end",
                    iid=f"{self._SUB}{cat}|||{sub}",
                    text=sub,
                    values=(sub_count,),
                    tags=sub_tags,
                )

    def _export_json(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Export categories and rules",
        )
        if not path:
            return
        data = export_data(self._conn)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        messagebox.showinfo(
            "Export complete",
            f"Exported {len(data['categories'])} categories and {len(data['rules'])} rules.",
        )

    def _import_json(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Import categories and rules",
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            messagebox.showerror("Import failed", f"Could not read file:\n{exc}")
            return
        try:
            cats_added, rules_added = import_data(self._conn, data)
        except Exception as exc:
            messagebox.showerror("Import failed", f"Error importing data:\n{exc}")
            return
        messagebox.showinfo(
            "Import complete",
            f"Added {cats_added} categories/sub-categories and {rules_added} rules.",
        )
        self.refresh()
        if self._on_data_changed:
            self._on_data_changed()

    def _on_select(self, event=None) -> None:
        sel = self._tree.selection()
        self._status_var.set("")
        if not sel:
            self._sel_category = None
            self._sel_sub = None
            self._excluded_var.set(False)
            return
        iid = sel[0]
        if iid.startswith(self._CAT):
            self._sel_category = iid[len(self._CAT):]
            self._sel_sub = None
            self._edit_var.set(self._sel_category)
            self._excluded_var.set(get_category_excluded(self._conn, self._sel_category))
        elif iid.startswith(self._SUB):
            rest = iid[len(self._SUB):]
            cat, sub = rest.split("|||", 1)
            self._sel_category = cat
            self._sel_sub = sub
            self._edit_var.set(sub)
            self._excluded_var.set(get_sub_category_excluded(self._conn, cat, sub))

    def _toggle_excluded(self) -> None:
        excluded = self._excluded_var.get()
        if self._sel_sub is not None:
            set_sub_category_excluded(self._conn, self._sel_category, self._sel_sub, excluded)
        elif self._sel_category is not None:
            set_category_excluded(self._conn, self._sel_category, excluded)
        else:
            return
        self._status_var.set("")
        self._apply_filter()

    def _create_category(self) -> None:
        name = self._new_cat_var.get().strip()
        if not name:
            return
        create_category(self._conn, name)
        self._new_cat_var.set("")
        self._status_var.set(f'Created "{name}".')
        self.refresh()

    def _create_sub_category(self) -> None:
        if not self._sel_category:
            self._status_var.set("Select a category from the list first.")
            return
        name = self._new_sub_var.get().strip()
        if not name:
            return
        create_sub_category(self._conn, self._sel_category, name)
        self._new_sub_var.set("")
        self._status_var.set(f'Created sub-category "{name}" under "{self._sel_category}".')
        self.refresh()

    def _rename(self) -> None:
        new_name = self._edit_var.get().strip()
        if not new_name:
            self._status_var.set("Enter a new name.")
            return
        if self._sel_sub is not None:
            if new_name == self._sel_sub:
                self._status_var.set("Name is unchanged.")
                return
            rename_sub_category(self._conn, self._sel_category, self._sel_sub, new_name)
            self._status_var.set(f'Renamed "{self._sel_sub}" → "{new_name}".')
        elif self._sel_category is not None:
            if new_name == self._sel_category:
                self._status_var.set("Name is unchanged.")
                return
            rename_category(self._conn, self._sel_category, new_name)
            self._status_var.set(f'Renamed "{self._sel_category}" → "{new_name}".')
        else:
            self._status_var.set("Select an item first.")
            return
        self._edit_var.set("")
        self._sel_category = None
        self._sel_sub = None
        self.refresh()

    def _delete(self) -> None:
        if self._sel_sub is not None:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM window_events WHERE category = ? AND sub_category = ?",
                (self._sel_category, self._sel_sub),
            ).fetchone()[0]
            msg = (
                f'Delete sub-category "{self._sel_sub}" under "{self._sel_category}"?\n\n'
                f'This will clear the sub-category from {count} event(s).'
            )
            if not messagebox.askyesno("Delete sub-category", msg, icon="warning"):
                return
            delete_sub_category(self._conn, self._sel_category, self._sel_sub)
            self._status_var.set(f'Deleted sub-category "{self._sel_sub}".')
        elif self._sel_category is not None:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM window_events WHERE category = ?", (self._sel_category,)
            ).fetchone()[0]
            msg = (
                f'Delete "{self._sel_category}"?\n\n'
                f'This will clear the category from {count} event(s) and cannot be undone.'
            )
            if not messagebox.askyesno("Delete category", msg, icon="warning"):
                return
            delete_category(self._conn, self._sel_category)
            self._status_var.set(f'Deleted "{self._sel_category}".')
        else:
            self._status_var.set("Select an item first.")
            return
        self._edit_var.set("")
        self._sel_category = None
        self._sel_sub = None
        self.refresh()
