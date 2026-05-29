import sys

# Заглушка для darkdetect, чтобы не крашить сессию
class _NoopDarkdetect:
    _theme = "Dark"
    @classmethod
    def theme(cls): return cls._theme
    @classmethod
    def isDark(cls): return True
    @classmethod
    def isLight(cls): return False
    @classmethod
    def listener(cls, cb): pass

sys.modules["darkdetect"] = _NoopDarkdetect

import customtkinter as ctk
import json
import os
import re
import tkinter as tk
import webbrowser
import subprocess


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LINKS_FILE = os.path.join(SCRIPT_DIR, "links.txt")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "output.txt")
STATE_FILE = os.path.join(SCRIPT_DIR, "state.json")

SELECTORS = [
    "ytd-video-renderer",
    "ytd-rich-item-renderer",
    "ytd-compact-video-renderer",
    "ytd-channel-renderer",
    ".shortsLockupViewModelHost",
    "yt-lockup-view-model",
]


def parse_handles(text: str) -> list:
    handles = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        at_handles = re.findall(r"@([\w-]+)", line)
        if at_handles:
            handles.extend(f"@{h}" for h in at_handles)
        else:
            words = re.findall(r"[\w-]+", line)
            for w in words:
                if w:
                    handles.append(f"@{w}")
    seen = set()
    unique = []
    for h in handles:
        if h not in seen:
            seen.add(h)
            unique.append(h)
    return unique


def generate_rules(handles: list) -> str:
    parts = [f'a[href*="/{h}"]' for h in handles]
    inner = ", ".join(parts)
    return "\n".join(f"youtube.com##{s}:has({inner})" for s in SELECTORS)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("YouTube Block Manager")
        self.geometry("700x500")

        self.handles = []
        self.vars = {}
        self._after_id = None
        self._drag_active = False
        self._toggled_this_drag: set = set()
        self._filter_mode = "all"  # 'all', 'checked', 'unchecked'
        self._opening_link = False

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_change)

        self._build_ui()
        self._setup_global_events()
        self.after_idle(self.search_entry.focus_set)
        self.after(10, self.refresh)

    # ----------------------------------------------------------------------
    # \u041f\u043e\u0441\u0442\u0440\u043e\u0435\u043d\u0438\u0435 \u0438\u043d\u0442\u0435\u0440\u0444\u0435\u0439\u0441\u0430
    # ----------------------------------------------------------------------
    def _build_ui(self):
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=8, pady=(8, 4))

        ctk.CTkButton(
            toolbar, text="\u043e\u0431\u043d\u043e\u0432\u0438\u0442\u044c", command=self.refresh, width=100, corner_radius=6
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            toolbar, text="\u0441\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u043f\u0440\u0430\u0432\u0438\u043b\u0430", command=self.save_rules,
            width=140, corner_radius=6
        ).pack(side="left")

        ctk.CTkButton(
            toolbar, text="\u043e\u0442\u043a\u0440\u044b\u0442\u044c links.txt", command=self._open_links_file,
            width=130, corner_radius=6
        ).pack(side="left", padx=(4, 0))

        ctk.CTkButton(
            toolbar, text="GitHub", command=self._open_github,
            width=80, corner_radius=6
        ).pack(side="right", padx=(0, 4))

        ctk.CTkButton(
            toolbar, text="TG", command=self._open_tg,
            width=50, corner_radius=6
        ).pack(side="right", padx=(0, 4))

        # \u041f\u043e\u0438\u0441\u043a\u043e\u0432\u0430\u044f \u0441\u0442\u0440\u043e\u043a\u0430 + \u0444\u0438\u043b\u044c\u0442\u0440
        search_frame = ctk.CTkFrame(self, fg_color="transparent")
        search_frame.pack(fill="x", padx=8, pady=(4, 2))

        ctk.CTkLabel(search_frame, text="\u043f\u043e\u0438\u0441\u043a:", anchor="w").pack(side="left", padx=(0, 4))
        self.search_entry = ctk.CTkEntry(
            search_frame, textvariable=self.search_var, corner_radius=6
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # \u0424\u0438\u043b\u044c\u0442\u0440-\u043a\u043d\u043e\u043f\u043a\u0438
        self.filter_all_btn = ctk.CTkButton(
            search_frame, text="\u0432\u0441\u0435", width=50, corner_radius=6,
            command=lambda: self._set_filter("all")
        )
        self.filter_all_btn.pack(side="left", padx=(0, 4))

        self.filter_checked_btn = ctk.CTkButton(
            search_frame, text="\u2713 \u0432\u044b\u0431\u0440.", width=60, corner_radius=6,
            command=lambda: self._set_filter("checked")
        )
        self.filter_checked_btn.pack(side="left", padx=(0, 4))

        self.filter_unchecked_btn = ctk.CTkButton(
            search_frame, text="\u2717 \u043d\u0435 \u0432\u044b\u0431\u0440.", width=70, corner_radius=6,
            command=lambda: self._set_filter("unchecked")
        )
        self.filter_unchecked_btn.pack(side="left")

        # \u041a\u043d\u043e\u043f\u043a\u0430 "\u0432\u044b\u0431\u0440\u0430\u0442\u044c \u0432\u0441\u0451 / \u0441\u043d\u044f\u0442\u044c \u0432\u0441\u0451"
        self.toggle_btn = ctk.CTkButton(
            self, text="\u0432\u044b\u0431\u0440\u0430\u0442\u044c \u0432\u0441\u0451", command=self.toggle_all, width=130, corner_radius=6
        )
        self.toggle_btn.pack(anchor="w", padx=8, pady=(4, 2))

        # \u0421\u043a\u0440\u043e\u043b\u043b\u0438\u0440\u0443\u0435\u043c\u0430\u044f \u043e\u0431\u043b\u0430\u0441\u0442\u044c \u0441\u043e \u0441\u043f\u0438\u0441\u043a\u043e\u043c
        self.scrollable = ctk.CTkScrollableFrame(self, corner_radius=6)
        self.scrollable.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        self._setup_mousewheel_binding()

        # \u0421\u0442\u0440\u043e\u043a\u0430 \u0441\u0442\u0430\u0442\u0443\u0441\u0430
        self.status_var = tk.StringVar(value="\u0413\u043e\u0442\u043e\u0432\u043e")
        ctk.CTkLabel(
            self, textvariable=self.status_var, anchor="w"
        ).pack(fill="x", padx=8, pady=(0, 6))

    def _set_filter(self, mode):
        self._filter_mode = mode
        self.filter_all_btn.configure(fg_color="#3a7ebf" if mode == "all" else "#2b2b2b")
        self.filter_checked_btn.configure(fg_color="#3a7ebf" if mode == "checked" else "#2b2b2b")
        self.filter_unchecked_btn.configure(fg_color="#3a7ebf" if mode == "unchecked" else "#2b2b2b")
        self._toggled_this_drag.clear()
        self.render_list()
        self.scrollable._parent_canvas.yview_moveto(0)

    def _setup_mousewheel_binding(self):
        if sys.platform.startswith('linux'):
            self.scrollable.bind("<Button-4>", self._on_mousewheel)
            self.scrollable.bind("<Button-5>", self._on_mousewheel)
        else:
            self.scrollable.bind("<MouseWheel>", self._on_mousewheel)

    def _setup_global_events(self):
        self.scrollable.bind("<Button-1>", self._on_drag_start)
        self.bind("<B1-Motion>", self._on_drag_motion)
        self.bind("<ButtonRelease-1>", self._on_drag_release)

        # \u041a\u043e\u043d\u0442\u0435\u043a\u0441\u0442\u043d\u043e\u0435 \u043c\u0435\u043d\u044e
        self.context_menu = tk.Menu(self, tearoff=0, bg="#2b2b2b", fg="#d4d4d4")
        self.context_menu.add_command(label="\u041a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u0442\u044c handle", command=self._copy_handle)
        self.context_menu.add_command(label="\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u043a\u0430\u043d\u0430\u043b \u0432 \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0435", command=self._open_channel)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="\u0412\u044b\u0431\u0440\u0430\u0442\u044c \u044d\u0442\u043e\u0442 \u043a\u0430\u043d\u0430\u043b", command=lambda: self._set_checked(True))
        self.context_menu.add_command(label="\u0421\u043d\u044f\u0442\u044c \u0432\u044b\u0431\u043e\u0440", command=lambda: self._set_checked(False))

        self._context_handle = None

    # ----------------------------------------------------------------------
    # \u0421\u043e\u0431\u044b\u0442\u0438\u044f \u043c\u044b\u0448\u0438 \u0438 \u043f\u0440\u043e\u043a\u0440\u0443\u0442\u043a\u0430
    # ----------------------------------------------------------------------
    def _on_mousewheel(self, event):
        if sys.platform.startswith('linux'):
            if event.num == 4:
                self.scrollable._parent_canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.scrollable._parent_canvas.yview_scroll(1, "units")
        else:
            self.scrollable._parent_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_search_change(self, *args):
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(300, self.render_list)

    # ----------------------------------------------------------------------
    # Drag-to-toggle
    # ----------------------------------------------------------------------
    def _on_drag_start(self, event):
        if not self._drag_active:
            self._toggled_this_drag.clear()
        self._drag_active = True

    def _on_drag_motion(self, event):
        if not self._drag_active:
            return

        # \u0410\u0432\u0442\u043e\u0441\u043a\u0440\u043e\u043b\u043b \u043f\u0440\u0438 \u043f\u0440\u0438\u0431\u043b\u0438\u0436\u0435\u043d\u0438\u0438 \u043a \u043a\u0440\u0430\u044f\u043c
        canvas = self.scrollable._parent_canvas
        y = event.y_root - self.scrollable.winfo_rooty()
        height = self.scrollable.winfo_height()
        if y < 20:
            canvas.yview_scroll(-1, "units")
        elif y > height - 20:
            canvas.yview_scroll(1, "units")

        widget = self.winfo_containing(event.x_root, event.y_root)
        if not widget:
            return
        cur = widget
        handle = None
        while cur and cur != self.scrollable:
            if hasattr(cur, "_handle"):
                handle = cur._handle
                break
            cur = cur.master

        if handle and handle not in self._toggled_this_drag:
            self._toggled_this_drag.add(handle)
            self.vars[handle].set(not self.vars[handle].get())

    def _on_drag_release(self, event):
        if self._drag_active:
            self._drag_active = False
            self._toggled_this_drag.clear()
            self._save_state()
            self._update_status()
            self._update_toggle_button()

    # ----------------------------------------------------------------------
    # \u041a\u043e\u043d\u0442\u0435\u043a\u0441\u0442\u043d\u043e\u0435 \u043c\u0435\u043d\u044e
    # ----------------------------------------------------------------------
    def _show_context_menu(self, event, handle):
        self._context_handle = handle
        self.context_menu.post(event.x_root, event.y_root)

    def _copy_handle(self):
        if self._context_handle:
            self.clipboard_clear()
            self.clipboard_append(self._context_handle)
            self.status_var.set(f"\u0421\u043a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u043d {self._context_handle}")

    def _open_channel(self):
        if self._context_handle:
            handle = self._context_handle.lstrip('@')
            webbrowser.open(f"https://www.youtube.com/@{handle}")

    def _set_checked(self, checked: bool):
        if self._context_handle:
            self.vars[self._context_handle].set(checked)
            self._save_state()
            self._update_status()
            self._update_toggle_button()
            self.render_list()

    # ----------------------------------------------------------------------
    # \u041e\u0441\u043d\u043e\u0432\u043d\u0430\u044f \u043b\u043e\u0433\u0438\u043a\u0430
    # ----------------------------------------------------------------------
    def _load_state(self) -> dict:
        if not os.path.exists(STATE_FILE):
            return {}
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_state(self):
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({h: v.get() for h, v in self.vars.items()},
                          f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0438\u044f \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u044f: {e}")

    def refresh(self):
        if not os.path.exists(LINKS_FILE):
            self.handles = []
            self.vars = {}
            self.status_var.set("\u0424\u0430\u0439\u043b links.txt \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d")
            self.render_list()
            return

        with open(LINKS_FILE, "r", encoding="utf-8") as f:
            text = f.read()

        new_handles = parse_handles(text)
        new_handles.sort(key=lambda h: h.lower())
        saved_state = self._load_state()

        old_vars = self.vars
        self.handles = new_handles
        self.vars = {}

        for h in self.handles:
            if h in old_vars:
                self.vars[h] = old_vars[h]
            elif h in saved_state:
                self.vars[h] = tk.BooleanVar(value=saved_state[h])
            else:
                self.vars[h] = tk.BooleanVar(value=True)

        self._update_toggle_button()
        self.render_list()
        self._save_state()

    def render_list(self):
        current_checks = {h: v.get() for h, v in self.vars.items()}
        for w in self.scrollable.winfo_children():
            w.destroy()

        self.scrollable._parent_canvas.configure(
            scrollregion=self.scrollable._parent_canvas.bbox("all"))

        query = self.search_var.get().strip().lower()
        filtered = self.handles
        if query:
            filtered = [h for h in filtered if query in h.lower()]

        if self._filter_mode == "checked":
            filtered = [h for h in filtered if self.vars[h].get()]
        elif self._filter_mode == "unchecked":
            filtered = [h for h in filtered if not self.vars[h].get()]

        if not filtered:
            ctk.CTkLabel(
                self.scrollable, text="\u0442\u0443\u0442 \u043f\u0443\u0441\u0442\u043e",
                anchor="center", font=("TkDefaultFont", 14, "bold")
            ).pack(expand=True, fill="both")
            self._update_status(filtered_count=0)
            return

        for h in filtered:
            if h in current_checks:
                self.vars[h].set(current_checks[h])

            cb = ctk.CTkCheckBox(
                self.scrollable,
                text=h,
                variable=self.vars[h],
                command=lambda h=h: self._on_toggle(h),
                corner_radius=6,
            )
            cb._handle = h
            cb.pack(anchor="w", padx=4, pady=2)
            cb.bind("<Button-3>", lambda e, h=h: self._show_context_menu(e, h))
            cb.bind("<Double-Button-1>", lambda e, cb=cb, h=h: self._highlight_and_open(cb, h))

        self._update_status(filtered_count=len(filtered))

    def _on_toggle(self, handle: str):
        self._drag_active = True
        self._toggled_this_drag.add(handle)
        self._save_state()
        self._update_status()
        self._update_toggle_button()

    def _update_status(self, filtered_count=None):
        total = len(self.handles)
        checked = sum(1 for v in self.vars.values() if v.get())
        query = self.search_var.get().strip()
        if filtered_count is not None and (query or self._filter_mode != "all"):
            self.status_var.set(
                f"\u041a\u0430\u043d\u0430\u043b\u043e\u0432: {total}, \u0432\u044b\u0431\u0440\u0430\u043d\u043e: {checked}, \u043f\u043e\u043a\u0430\u0437\u0430\u043d\u043e: {filtered_count}"
            )
        else:
            self.status_var.set(f"\u041a\u0430\u043d\u0430\u043b\u043e\u0432: {total}, \u0432\u044b\u0431\u0440\u0430\u043d\u043e: {checked}")

    def _update_toggle_button(self):
        if not self.vars:
            return
        all_checked = all(v.get() for v in self.vars.values())
        self.toggle_btn.configure(text="\u0441\u043d\u044f\u0442\u044c \u0432\u0441\u0451" if all_checked else "\u0432\u044b\u0431\u0440\u0430\u0442\u044c \u0432\u0441\u0451")

    def toggle_all(self):
        if not self.vars:
            return
        any_unchecked = any(not v.get() for v in self.vars.values())
        for v in self.vars.values():
            v.set(any_unchecked)
        self._update_toggle_button()
        self._save_state()
        self._update_status()
        self.render_list()

    def _highlight_and_open(self, checkbox, handle):
        if self._opening_link:
            return
        self._opening_link = True
        original_fg = checkbox.cget("fg_color")
        checkbox.configure(fg_color="#3a7ebf")

        def open_and_restore():
            webbrowser.open(f"https://www.youtube.com/@{handle.lstrip('@')}")
            checkbox.configure(fg_color=original_fg)
            self._opening_link = False

        self.after(200, open_and_restore)

    def _open_links_file(self):
        if not os.path.exists(LINKS_FILE):
            with open(LINKS_FILE, "w", encoding="utf-8") as f:
                f.write("# \u0421\u043f\u0438\u0441\u043e\u043a \u043a\u0430\u043d\u0430\u043b\u043e\u0432 (\u043f\u043e \u043e\u0434\u043d\u043e\u043c\u0443 \u0438\u043b\u0438 \u0441 @)\n")
        if sys.platform == "win32":
            os.startfile(LINKS_FILE)
        elif sys.platform == "darwin":
            subprocess.run(["open", LINKS_FILE])
        else:
            subprocess.run(["xdg-open", LINKS_FILE])

    def _open_github(self):
        webbrowser.open("https://github.com/kiberdans/youtube-ege-blocklist")

    def _open_tg(self):
        webbrowser.open("https://t.me/+OvwRHCdVBPk2NWRi")

    def save_rules(self):
        if not self.handles:
            self.status_var.set("\u041d\u0435\u0442 \u043a\u0430\u043d\u0430\u043b\u043e\u0432 \u0434\u043b\u044f \u0433\u0435\u043d\u0435\u0440\u0430\u0446\u0438\u0438")
            return

        checked_handles = [h for h, v in self.vars.items() if v.get()]
        if not checked_handles:
            self.status_var.set("\u041d\u0435\u0442 \u0432\u044b\u0431\u0440\u0430\u043d\u043d\u044b\u0445 \u043a\u0430\u043d\u0430\u043b\u043e\u0432")
            return

        rules = generate_rules(checked_handles)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(rules + "\n")

        self.status_var.set(f"\u0421\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u043e {len(checked_handles)} \u043a\u0430\u043d\u0430\u043b\u043e\u0432 \u2192 output.txt")


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()
