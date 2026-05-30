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
    "ytd-post-renderer",
    "ytm-shorts-lockup-view-model",
    "ytm-shorts-lockup-view-model-v2",
    "grid-shelf-view-model",
]


_URL_HANDLE_RE = re.compile(
    r"youtube\.com/(?:@|c/|channel/|user/)?([\w-]+)", re.IGNORECASE
)
_SKIP_WORDS = frozenset({"www", "youtube", "com", "c", "channel", "user", "watch", "results", "https"})

def parse_handles(text: str) -> list:
    handles = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        at_handles = re.findall(r"@([\w-]+)", line)
        if at_handles:
            handles.extend(f"@{h}" for h in at_handles)
            continue

        m = _URL_HANDLE_RE.search(line)
        if m:
            h = m.group(1)
            if h.lower() not in _SKIP_WORDS:
                handles.append(f"@{h}")
                continue

        if re.fullmatch(r"[\w-]+", line):
            handles.append(f"@{line}")

    seen = set()
    unique = []
    for h in handles:
        if h not in seen:
            seen.add(h)
            unique.append(h)
    return unique


def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def generate_rules(handles: list, block_all_shorts: bool = False) -> str:
    rules = []

    for chunk in _chunks(handles, 15):
        inner = ", ".join(f'a[href*="/{h}"]' for h in chunk)
        grouped = f":is({inner})"

        for s in SELECTORS:
            rules.append(f"youtube.com##{grouped}:upward({s})")
            rules.append(f"youtube.com##ytd-search {grouped}:upward({s})")

    if block_all_shorts:
        shorts_rules = [
            'a[href^="/shorts/"]:upward(grid-shelf-view-model)',
            'a[href^="/shorts/"]:upward(ytd-rich-item-renderer)',
            'a[href^="/shorts/"]:upward(ytd-reel-shelf-renderer)',
            'a[href^="/shorts/"]:upward(ytd-video-renderer)',
            'yt-section-header-view-model:has-text(/(^| )Shorts( |$)/i):upward(grid-shelf-view-model)',
            'grid-shelf-view-model:has(ytm-shorts-lockup-view-model)',
            'grid-shelf-view-model:has(ytm-shorts-lockup-view-model-v2)',
            'ytm-shorts-lockup-view-model',
            'ytm-shorts-lockup-view-model-v2',
            '.shortsLockupViewModelHost',
            '[overlay-style="SHORTS"]:upward(ytd-video-renderer)',
            '[overlay-style="SHORTS"]:upward(ytd-rich-item-renderer)',
            '[overlay-style="SHORTS"]:upward(ytd-compact-video-renderer)',
            'ytd-rich-shelf-renderer[is-shorts]',
            'ytd-rich-section-renderer:has(ytd-rich-shelf-renderer[is-shorts])',
            'ytd-reel-shelf-renderer',
            'ytd-guide-entry-renderer:has(a[title="Shorts"])',
            'ytd-mini-guide-entry-renderer[aria-label="Shorts"]',
            'yt-tab-shape[tab-title="Shorts"]',
        ]
        for s in shorts_rules:
            rules.append(f"youtube.com##{s}")

    return "\n".join(rules)
    return "\n".join(rules)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("YouTube Block Manager")
        self.geometry("700x500")
        self.withdraw()

        self.handles = []
        self.vars = {}
        self._after_id = None
        self._drag_active = False
        self._toggled_this_drag: set = set()
        self._filter_mode = "all"  # 'all', 'checked', 'unchecked'
        self._opening_link = False
        self._block_all_shorts = tk.BooleanVar(value=False)

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_change)

        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        self._build_ui()
        self._setup_global_events()
        self.refresh()
        self.update_idletasks()
        self.deiconify()
        self.after_idle(self.search_entry.focus_set)

    # ----------------------------------------------------------------------
    # Построение интерфейса
    # ----------------------------------------------------------------------
    def _build_ui(self):
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=8, pady=(8, 4))

        ctk.CTkButton(
            toolbar, text="обновить", command=self.refresh, width=100, corner_radius=6
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            toolbar, text="сохранить правила", command=self.save_rules,
            width=140, corner_radius=6
        ).pack(side="left")

        ctk.CTkButton(
            toolbar, text="открыть links.txt", command=self._open_links_file,
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

        # Поисковая строка + фильтр
        search_frame = ctk.CTkFrame(self, fg_color="transparent")
        search_frame.pack(fill="x", padx=8, pady=(4, 2))

        ctk.CTkLabel(search_frame, text="поиск:", anchor="w").pack(side="left", padx=(0, 4))
        self.search_entry = ctk.CTkEntry(
            search_frame, textvariable=self.search_var, corner_radius=6
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Фильтр-кнопки
        self.filter_all_btn = ctk.CTkButton(
            search_frame, text="все", width=50, corner_radius=6,
            command=lambda: self._set_filter("all")
        )
        self.filter_all_btn.pack(side="left", padx=(0, 4))

        self.filter_checked_btn = ctk.CTkButton(
            search_frame, text="✓ выбр.", width=60, corner_radius=6,
            command=lambda: self._set_filter("checked")
        )
        self.filter_checked_btn.pack(side="left", padx=(0, 4))

        self.filter_unchecked_btn = ctk.CTkButton(
            search_frame, text="✗ не выбр.", width=70, corner_radius=6,
            command=lambda: self._set_filter("unchecked")
        )
        self.filter_unchecked_btn.pack(side="left")

        # Кнопка "выбрать всё / снять всё" и блокировка шортсов
        control_frame = ctk.CTkFrame(self, fg_color="transparent")
        control_frame.pack(fill="x", padx=8, pady=(4, 2))

        self.toggle_btn = ctk.CTkButton(
            control_frame, text="выбрать всё", command=self.toggle_all, width=130, corner_radius=6
        )
        self.toggle_btn.pack(side="left")

        self.block_shorts_cb = ctk.CTkCheckBox(
            control_frame, text="блокировать все Shorts (целиком блок)",
            variable=self._block_all_shorts,
            command=self._on_block_shorts_toggle,
            corner_radius=6
        )
        self.block_shorts_cb.pack(side="left", padx=(12, 0))

        # Скроллируемая область со списком
        self.scrollable = ctk.CTkScrollableFrame(self, corner_radius=6)
        self.scrollable.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        self._setup_mousewheel_binding()

        # Строка статуса
        self.status_var = tk.StringVar(value="Готово")
        ctk.CTkLabel(
            self, textvariable=self.status_var, anchor="w"
        ).pack(fill="x", padx=8, pady=(0, 6))

    def _set_filter(self, mode):
        self._filter_mode = mode
        self.filter_all_btn.configure(fg_color="#3a7ebf" if mode == "all" else "#2b2b2b")
        self.filter_checked_btn.configure(fg_color="#3a7ebf" if mode == "checked" else "#2b2b2b")
        self.filter_unchecked_btn.configure(fg_color="#3a7ebf" if mode == "unchecked" else "#2b2b2b")
        self._toggled_this_drag.clear()
        self._save_state()
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

        # Контекстное меню
        self.context_menu = tk.Menu(self, tearoff=0, bg="#2b2b2b", fg="#d4d4d4")
        self.context_menu.add_command(label="Копировать handle", command=self._copy_handle)
        self.context_menu.add_command(label="Открыть канал в браузере", command=self._open_channel)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Выбрать этот канал", command=lambda: self._set_checked(True))
        self.context_menu.add_command(label="Снять выбор", command=lambda: self._set_checked(False))

        self._context_handle = None

    # ----------------------------------------------------------------------
    # События мыши и прокрутка
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

        # Автоскролл при приближении к краям
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
    # Контекстное меню
    # ----------------------------------------------------------------------
    def _show_context_menu(self, event, handle):
        self._context_handle = handle
        self.context_menu.post(event.x_root, event.y_root)

    def _copy_handle(self):
        if self._context_handle:
            self.clipboard_clear()
            self.clipboard_append(self._context_handle)
            self.status_var.set(f"Скопирован {self._context_handle}")

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
    # Основная логика
    # ----------------------------------------------------------------------
    def _load_state(self) -> dict:
        if not os.path.exists(STATE_FILE):
            return {}
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data
        except Exception:
            return {}

    def _save_state(self):
        try:
            data = {
                "handles": {h: v.get() for h, v in self.vars.items()},
                "ui": {
                    "block_all_shorts": self._block_all_shorts.get(),
                    "filter_mode": self._filter_mode,
                },
            }
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения состояния: {e}")

    def refresh(self):
        if not os.path.exists(LINKS_FILE):
            self.handles = []
            self.vars = {}
            self.status_var.set("Файл links.txt не найден")
            self.render_list()
            return

        with open(LINKS_FILE, "r", encoding="utf-8") as f:
            text = f.read()

        new_handles = parse_handles(text)
        new_handles.sort(key=lambda h: h.lower())
        saved_state = self._load_state()

        if isinstance(saved_state, dict) and "handles" in saved_state:
            handles_state = saved_state["handles"]
            ui_state = saved_state.get("ui", {})
        else:
            handles_state = saved_state if isinstance(saved_state, dict) else {}
            ui_state = {}

        old_vars = self.vars
        self.handles = new_handles
        self.vars = {}

        for h in self.handles:
            if h in old_vars:
                self.vars[h] = old_vars[h]
            elif h in handles_state:
                self.vars[h] = tk.BooleanVar(value=handles_state[h])
            else:
                self.vars[h] = tk.BooleanVar(value=True)

        if "block_all_shorts" in ui_state:
            self._block_all_shorts.set(ui_state["block_all_shorts"])
        if "filter_mode" in ui_state:
            self._set_filter(ui_state["filter_mode"])

        self._update_toggle_button()
        self.render_list()
        self._save_state()

    def render_list(self):
        self.scrollable._parent_canvas.itemconfigure("all", state="hidden")

        current_checks = {h: v.get() for h, v in self.vars.items()}
        for w in self.scrollable.winfo_children():
            if isinstance(w, ctk.CTkCheckBox):
                w.configure(variable=None)
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
                self.scrollable, text="тут пусто",
                anchor="center", font=("TkDefaultFont", 14, "bold")
            ).pack(expand=True, fill="both")
            self._update_status(filtered_count=0)
            self.scrollable._parent_canvas.itemconfigure("all", state="normal")
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

        self.scrollable._parent_canvas.itemconfigure("all", state="normal")
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
                f"Каналов: {total}, выбрано: {checked}, показано: {filtered_count}"
            )
        else:
            self.status_var.set(f"Каналов: {total}, выбрано: {checked}")

    def _update_toggle_button(self):
        if not self.vars:
            return
        all_checked = all(v.get() for v in self.vars.values())
        self.toggle_btn.configure(text="снять всё" if all_checked else "выбрать всё")

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
        if original_fg is None:
            original_fg = checkbox.cget("border_color")
        checkbox.configure(fg_color="#3a7ebf")

        def open_and_restore():
            webbrowser.open(f"https://www.youtube.com/@{handle.lstrip('@')}")
            try:
                checkbox.configure(fg_color=original_fg)
            except Exception:
                checkbox.configure(fg_color="default")
            self._opening_link = False

        self.after(200, open_and_restore)

    def _open_links_file(self):
        if not os.path.exists(LINKS_FILE):
            with open(LINKS_FILE, "w", encoding="utf-8") as f:
                f.write("# Список каналов (по одному или с @)\n")
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
            self.status_var.set("Нет каналов для генерации")
            return

        checked_handles = [h for h, v in self.vars.items() if v.get()]
        if not checked_handles:
            self.status_var.set("Нет выбранных каналов")
            return

        rules = generate_rules(checked_handles, self._block_all_shorts.get())
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(rules + "\n")

        self.status_var.set(f"Сохранено {len(checked_handles)} каналов → output.txt")

    def _on_block_shorts_toggle(self):
        self._save_state()
        self.save_rules()

    def _on_closing(self):
        self._save_state()
        self.destroy()

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()
