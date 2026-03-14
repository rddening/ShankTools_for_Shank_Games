import os
import json
import sys
import importlib.util
import tkinter as tk
import ui_system
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

import updater

# ============================================================
#                    CONSTANTS & CONFIG
# ============================================================

APP_NAME    = "ShankTools"
APP_VERSION = "1.0.32 alpha version"

def get_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    else:
        return Path(__file__).resolve().parent

BASE_DIR = get_base_dir()

CONFIG_DIR      = BASE_DIR / "data"
PLUGINS_DIR     = BASE_DIR / "plugins"
MAIN_TOOLS_DIR  = BASE_DIR / "main_tools"
CONFIG_FILE     = CONFIG_DIR / "config.json"
USER_DATA_FILE  = CONFIG_DIR / "userdata.sav"

THEMES = {
    "Shank 2": {
        "bg":            "#3C3C3C",
        "bg_secondary":  "#2E2E2E",
        "bg_panel":      "#353535",
        "btn_bg":        "#E07820",
        "btn_fg":        "#FFFFFF",
        "btn_hover":     "#C86010",
        "text":          "#F0F0F0",
        "text_secondary":"#AAAAAA",
        "accent":        "#E07820",
        "border":        "#555555",
        "header_bg":     "#2A2A2A",
        "sidebar_bg":    "#333333",
        "entry_bg":      "#444444",
        "entry_fg":      "#F0F0F0",
        "title":         "Shank 2 Theme",
        "card_bg":       "#404040",
        "card_hover":    "#4A4A4A",
        "card_important_bg":    "#2E2A1E",
        "card_important_hover": "#3A3420",
    },
    "Shank 1": {
        "bg":            "#E0C470",
        "bg_secondary":  "#B37D2C",
        "bg_panel":      "#A46C24",
        "btn_bg":        "#8B0000",
        "btn_fg":        "#FFFFFF",
        "btn_hover":     "#6B0000",
        "text":          "#1A1A1A",
        "text_secondary":"#3A3A3A",
        "accent":        "#8B0000",
        "border":        "#9A7228",
        "header_bg":     "#B37D2C",
        "sidebar_bg":    "#A46C24",
        "entry_bg":      "#C8913A",
        "entry_fg":      "#1A1A1A",
        "title":         "Shank 1 Theme",
        "card_bg":       "#C8A050",
        "card_hover":    "#D4AA5A",
        "card_important_bg":    "#7A0000",
        "card_important_hover": "#8B0000",
    },
    "CustomStyle": {
        "bg":            "#3C3C3C",
        "bg_secondary":  "#2E2E2E",
        "bg_panel":      "#353535",
        "btn_bg":        "#E07820",
        "btn_fg":        "#FFFFFF",
        "btn_hover":     "#C86010",
        "text":          "#F0F0F0",
        "text_secondary":"#AAAAAA",
        "accent":        "#E07820",
        "border":        "#555555",
        "header_bg":     "#2A2A2A",
        "sidebar_bg":    "#333333",
        "entry_bg":      "#444444",
        "entry_fg":      "#F0F0F0",
        "title":         "CustomStyle Theme",
        "card_bg":       "#404040",
        "card_hover":    "#4A4A4A",
        "card_important_bg":    "#2E2A1E",
        "card_important_hover": "#3A3420",
    },
}

DEFAULT_CONFIG = {
    "username":      "...",
    "language":      "en",
    "last_opened":   [],
    "window_width":  1100,
    "window_height": 700,
    "plugins_enabled": True,
    "Theme":         "Shank 2",
}

# ============================================================
#                    FOLDER SETUP
# ============================================================

def setup_directories():
    CONFIG_DIR.mkdir(exist_ok=True)
    PLUGINS_DIR.mkdir(exist_ok=True)
    MAIN_TOOLS_DIR.mkdir(exist_ok=True)

    plugins_readme = PLUGINS_DIR / "README.txt"
    if not plugins_readme.exists():
        with open(plugins_readme, "w", encoding="utf-8") as f:
            f.write("Place your Plugin files here (.py)\n")
            f.write("Each plugin must contain a function: register(app)\n")

    main_tools_readme = MAIN_TOOLS_DIR / "README.txt"
    if not main_tools_readme.exists():
        with open(main_tools_readme, "w", encoding="utf-8") as f:
            f.write("Place your main tool files here (.py)\n")
            f.write("Each tool must contain a function: register(tool)\n")
            f.write("These tools appear as IMPORTANT (highlighted) cards.\n")

    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG.copy())

    if not USER_DATA_FILE.exists():
        with open(USER_DATA_FILE, "wb") as f:
            f.write(b"SHANKDATA\x01\x00")

# ============================================================
#                    CONFIG MANAGEMENT
# ============================================================

def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = DEFAULT_CONFIG.copy()
        merged.update(data)
        return merged
    except Exception:
        return DEFAULT_CONFIG.copy()

def save_config(config: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

# ============================================================
#                    CUSTOM WIDGETS
# ============================================================

class HoverButton(tk.Button):
    def __init__(self, master, theme, **kwargs):
        super().__init__(master, **kwargs)
        self.theme = theme
        self.config(
            bg=theme["btn_bg"],
            fg=theme["btn_fg"],
            activebackground=theme["btn_hover"],
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=12,
            pady=6,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, e):
        self.config(bg=self.theme["btn_hover"])

    def _on_leave(self, e):
        self.config(bg=self.theme["btn_bg"])

    def update_theme(self, theme):
        self.theme = theme
        self.config(
            bg=theme["btn_bg"],
            fg=theme["btn_fg"],
            activebackground=theme["btn_hover"],
        )


class ToolCard(tk.Frame):
    def __init__(self, master, theme, icon="🔧", title="Tool",
                 desc="", command=None, important=False, **kwargs):
        bg = (
            theme.get("card_important_bg", "#2E2A1E")
            if important
            else theme.get("card_bg", "#404040")
        )

        super().__init__(
            master,
            bg=bg,
            relief="flat",
            bd=0,
            cursor="hand2",
            **kwargs
        )

        self.theme     = theme
        self.command   = command
        self.important = important
        self._bg       = bg

        if important:
            accent = theme.get("accent", "#E07820")
            tk.Frame(self, bg=accent, width=5).pack(side="left", fill="y")

        inner = tk.Frame(self, bg=bg, padx=10, pady=10)
        inner.pack(fill="both", expand=True)

        tk.Label(
            inner, text=icon,
            bg=bg, fg=theme["accent"],
            font=("Segoe UI", 28),
        ).pack(pady=(8, 2))

        tk.Label(
            inner, text=title,
            bg=bg, fg=theme["text"],
            font=("Segoe UI", 11, "bold"),
        ).pack()

        if desc:
            tk.Label(
                inner, text=desc,
                bg=bg, fg=theme["text_secondary"],
                font=("Segoe UI", 8),
                wraplength=160,
                justify="center",
            ).pack(pady=(2, 8))

        self._bind_all_children(self)

    def _bind_all_children(self, widget):
        widget.bind("<Enter>",    self._on_enter)
        widget.bind("<Leave>",    self._on_leave)
        widget.bind("<Button-1>", self._on_click)
        for child in widget.winfo_children():
            self._bind_all_children(child)

    def _on_enter(self, e):
        hover = (
            self.theme.get("card_important_hover", "#3A3420")
            if self.important
            else self.theme.get("card_hover", "#4A4A4A")
        )
        self._set_bg(hover)

    def _on_leave(self, e):
        self._set_bg(self._bg)

    def _on_click(self, e):
        if self.command:
            self.command()

    def _set_bg(self, color):
        self.config(bg=color)
        for child in self.winfo_children():
            try:
                child.config(bg=color)
                for sub in child.winfo_children():
                    try:
                        sub.config(bg=color)
                    except Exception:
                        pass
            except Exception:
                pass

    def update_theme(self, theme):
        self.theme = theme
        self._bg = (
            theme.get("card_important_bg", "#2E2A1E")
            if self.important
            else theme.get("card_bg", "#404040")
        )
        self._set_bg(self._bg)
        for child in self.winfo_children():
            try:
                child.config(fg=theme["text"])
            except Exception:
                pass


# ============================================================
#                    MAIN APPLICATION
# ============================================================

class ShankToolsApp:
    def __init__(self, root: tk.Tk):
        self.root    = root
        self.config  = load_config()
        self.theme   = THEMES.get(self.config.get("Theme", "Shank 2"), THEMES["Shank 2"])
        self.plugins = []

        self._tool_cards: list[dict] = []

        self._current_tool_panel = None

        self._setup_window()
        self._build_ui()
        self._load_plugins()
        self._check_updates_on_start()

    # ----------------------------------------------------------
    #  Auto-Update Check
    # ----------------------------------------------------------

    def _check_updates_on_start(self):
        import threading

        def check():
            info = updater.check_for_updates(silent=True)
            if info:
                self.root.after(0, lambda: self._show_update_window(info))

        threading.Thread(target=check, daemon=True).start()

    def _show_update_window(self, update_info):
        from update_window import UpdateWindow
        UpdateWindow(self.root, update_info, self.theme, updater)

    def _manual_check_update(self):
        info = updater.check_for_updates(silent=False)
        if info:
            self._show_update_window(info)

    # ----------------------------------------------------------
    #  Window Setup
    # ----------------------------------------------------------

    def _setup_window(self):
        w = self.config.get("window_width",  1100)
        h = self.config.get("window_height", 700)
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(800, 550)
        self.root.configure(bg=self.theme["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        try:
            icon_path = BASE_DIR / "icon.ico"
            if icon_path.exists():
                self.root.iconbitmap(str(icon_path))
        except Exception:
            pass

    # ----------------------------------------------------------
    #  UI Builder
    # ----------------------------------------------------------

    def _build_ui(self):
        self._build_header()
        self._build_statusbar()
        self._build_body()

    def _build_header(self):
        self.header = tk.Frame(self.root, bg=self.theme["header_bg"], height=60)
        self.header.pack(fill="x", side="top")
        self.header.pack_propagate(False)

        tk.Label(
            self.header, text=f"⚙ {APP_NAME}",
            bg=self.theme["header_bg"], fg=self.theme["accent"],
            font=("Segoe UI", 16, "bold"),
        ).pack(side="left", padx=20, pady=10)

        tk.Label(
            self.header, text=f"v{APP_VERSION}",
            bg=self.theme["header_bg"], fg=self.theme["text_secondary"],
            font=("Segoe UI", 9),
        ).pack(side="left", pady=10)

        btn_frame = tk.Frame(self.header, bg=self.theme["header_bg"])
        btn_frame.pack(side="right", padx=15)

        HoverButton(
            btn_frame, self.theme,
            text="🔄 Check for Updates",
            command=self._manual_check_update,
        ).pack(side="right", padx=5)

        HoverButton(
            btn_frame, self.theme,
            text="🎨 Change Theme",
            command=self._toggle_theme,
        ).pack(side="right", padx=5)

    def _build_body(self):
        self.body = tk.Frame(self.root, bg=self.theme["bg"])
        self.body.pack(fill="both", expand=True)
        self._build_sidebar()
        self._build_workspace()

    def _build_sidebar(self):
        self.sidebar = tk.Frame(self.body, bg=self.theme["sidebar_bg"], width=200)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        tk.Label(
            self.sidebar, text="Plugins",
            bg=self.theme["sidebar_bg"], fg=self.theme["text"],
            font=("Segoe UI", 11, "bold"),
        ).pack(pady=(15, 5), padx=10, anchor="w")

        tk.Frame(self.sidebar, bg=self.theme["border"], height=1).pack(
            fill="x", padx=10, pady=2
        )

        self.plugins_label = tk.Label(
            self.sidebar, text="No plugins loaded",
            bg=self.theme["sidebar_bg"], fg=self.theme["text_secondary"],
            font=("Segoe UI", 8), wraplength=180, justify="left",
        )
        self.plugins_label.pack(padx=10, pady=5, anchor="w")

        self.plugins_area = tk.Frame(self.sidebar, bg=self.theme["sidebar_bg"])
        self.plugins_area.pack(fill="x", padx=5, expand=True)

        tk.Frame(self.sidebar, bg=self.theme["border"], height=1).pack(
            fill="x", padx=10, pady=8
        )

        HoverButton(
            self.sidebar, self.theme,
            text="📁 Open Plugins Folder",
            command=self._open_plugins_folder,
        ).pack(pady=5, padx=10, fill="x", side="bottom")

    # ── Workspace ─────────────────────────────────────────────

    def _build_workspace(self):
        self.workspace = tk.Frame(self.body, bg=self.theme["bg"])
        self.workspace.pack(side="left", fill="both", expand=True)

        self._build_tools_view()

    def _build_tools_view(self):
        self.tools_view = tk.Frame(self.workspace, bg=self.theme["bg"])
        self.tools_view.pack(fill="both", expand=True)

        top_bar = tk.Frame(self.tools_view, bg=self.theme["bg_secondary"], height=50)
        top_bar.pack(fill="x")
        top_bar.pack_propagate(False)

        tk.Label(
            top_bar, text="🛠  Tools",
            bg=self.theme["bg_secondary"], fg=self.theme["text"],
            font=("Segoe UI", 13, "bold"),
        ).pack(side="left", padx=20, pady=10)

        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search)

        search_frame = tk.Frame(top_bar, bg=self.theme["bg_secondary"])
        search_frame.pack(side="right", padx=20, pady=8)

        tk.Label(
            search_frame, text="🔍",
            bg=self.theme["bg_secondary"], fg=self.theme["text_secondary"],
            font=("Segoe UI", 10),
        ).pack(side="left")

        self._search_entry = tk.Entry(
            search_frame,
            textvariable=self._search_var,
            bg=self.theme["entry_bg"],
            fg=self.theme["entry_fg"],
            insertbackground=self.theme["text"],
            relief="flat",
            font=("Segoe UI", 10),
            width=20,
        )
        self._search_entry.pack(side="left", padx=5, ipady=4)

        canvas_frame = tk.Frame(self.tools_view, bg=self.theme["bg"])
        canvas_frame.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(
            canvas_frame, bg=self.theme["bg"], highlightthickness=0
        )
        scrollbar = ttk.Scrollbar(
            canvas_frame, orient="vertical", command=self._canvas.yview
        )
        self._canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self.tools_grid = tk.Frame(self._canvas, bg=self.theme["bg"])
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self.tools_grid, anchor="nw"
        )

        self.tools_grid.bind("<Configure>", self._on_grid_configure)
        self._canvas.bind("<Configure>",    self._on_canvas_configure)
        self._canvas.bind_all(
            "<MouseWheel>",
            lambda e: self._canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )

        self._empty_label = tk.Label(
            self.tools_grid,
            text="🔌  No tools available\nAdd plugins to the plugins folder to get started.",
            bg=self.theme["bg"],
            fg=self.theme["text_secondary"],
            font=("Segoe UI", 12),
            justify="center",
        )
        self._empty_label.grid(row=0, column=0, columnspan=4, pady=60)

        self._cards_per_row = 4

    def _on_grid_configure(self, e):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, e):
        self._canvas.itemconfig(self._canvas_window, width=e.width)
        new_cols = max(1, e.width // 200)
        if new_cols != self._cards_per_row:
            self._cards_per_row = new_cols
            self._redraw_cards()

    def _on_search(self, *_):
        self._redraw_cards()

    def _redraw_cards(self):
        for widget in self.tools_grid.winfo_children():
            widget.grid_forget()

        query = self._search_var.get().lower().strip()
        visible = (
            [c for c in self._tool_cards
             if query in c["title"].lower() or query in c["desc"].lower()]
            if query else self._tool_cards
        )

        if not visible:
            self._empty_label = tk.Label(
                self.tools_grid,
                text=(
                    f'🔍  No results for "{query}"'
                    if query
                    else "🔌  No tools available\nAdd plugins to get started."
                ),
                bg=self.theme["bg"],
                fg=self.theme["text_secondary"],
                font=("Segoe UI", 12),
                justify="center",
            )
            self._empty_label.grid(
                row=0, column=0, columnspan=self._cards_per_row, pady=60
            )
            return

        cols = self._cards_per_row
        for i, card_data in enumerate(visible):
            row, col = divmod(i, cols)
            card_data["widget"].grid(
                row=row, column=col,
                padx=12, pady=12,
                sticky="nsew",
            )

        for c in range(cols):
            self.tools_grid.columnconfigure(c, weight=1)

    # ----------------------------------------------------------
    #  Open a tool inside the workspace
    # ----------------------------------------------------------

    def show_tool_panel(self, tool_info):
        self.tools_view.pack_forget()

        self._tool_panel_frame = tk.Frame(self.workspace, bg=self.theme["bg"])
        self._tool_panel_frame.pack(fill="both", expand=True)

        if tool_info.get("custom_ui") and "builder" in tool_info:
            tool_info["builder"](
                parent=self._tool_panel_frame,
                theme=self.theme,
                status_cb=self._set_status,
                back_cb=self._back_to_tools,
            )
        else:
            from ui_system import EmbeddedToolPanel
            self._current_tool_panel = EmbeddedToolPanel(
                parent=self._tool_panel_frame,
                tool_info=tool_info,
                theme=self.theme,
                status_cb=self._set_status,
                back_cb=self._back_to_tools,
            )

    def _back_to_tools(self):
        if hasattr(self, "_tool_panel_frame") and self._tool_panel_frame.winfo_exists():
            self._tool_panel_frame.destroy()
        self._current_tool_panel = None
        self.tools_view.pack(fill="both", expand=True)
        self._set_status("Ready")

    # ----------------------------------------------------------
    #  Public API for Plugins
    # ----------------------------------------------------------

    def add_tool_card(self, icon="🔧", title="Tool",
                      desc="", command=None, important=False):
        if hasattr(self, "_empty_label") and self._empty_label.winfo_exists():
            self._empty_label.grid_forget()

        card = ToolCard(
            master    = self.tools_grid,
            theme     = self.theme,
            icon      = icon,
            title     = title,
            desc      = desc,
            command   = command,
            important = important,
        )

        self._tool_cards.append({
            "icon":      icon,
            "title":     title,
            "desc":      desc,
            "command":   command,
            "important": important,
            "widget":    card,
        })

        self._redraw_cards()

    # ----------------------------------------------------------
    #  Status Bar
    # ----------------------------------------------------------

    def _build_statusbar(self):
        self.statusbar = tk.Frame(
            self.root, bg=self.theme["header_bg"], height=28
        )
        self.statusbar.pack(fill="x", side="bottom")
        self.statusbar.pack_propagate(False)

        self.status_label = tk.Label(
            self.statusbar, text="Ready",
            bg=self.theme["header_bg"], fg=self.theme["text_secondary"],
            font=("Segoe UI", 9), anchor="w",
        )
        self.status_label.pack(side="left", padx=15, pady=4)

        tk.Label(
            self.statusbar, text=f"{APP_NAME} © 2024",
            bg=self.theme["header_bg"], fg=self.theme["text_secondary"],
            font=("Segoe UI", 8),
        ).pack(side="right", padx=15)

    # ----------------------------------------------------------
    #  Theme
    # ----------------------------------------------------------

    def _toggle_theme(self):
        current   = self.config.get("Theme", "Shank 2")
        new_theme = "Shank 2" if current == "Shank 1" else "Shank 1"
        self.config["Theme"] = new_theme
        self.theme = THEMES[new_theme]
        save_config(self.config)
        self._apply_theme()
        self._set_status(f"Theme switched to: {self.theme['title']}")

    def _apply_theme(self):
        self._tool_cards.clear()

        self.root.configure(bg=self.theme["bg"])
        for widget in self.root.winfo_children():
            widget.destroy()

        self._build_ui()
        self._load_plugins()

    # ----------------------------------------------------------
    #  Plugins Loader
    # ----------------------------------------------------------

    def _open_plugins_folder(self):
        import subprocess
        try:
            if sys.platform == "win32":
                subprocess.Popen(f'explorer "{PLUGINS_DIR.resolve()}"')
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(PLUGINS_DIR.resolve())])
            else:
                subprocess.Popen(["xdg-open", str(PLUGINS_DIR.resolve())])
        except Exception as e:
            messagebox.showerror("Error", str(e))

    @staticmethod
    def _load_module(path: Path):
        module_name = f"dynamic_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod

    def _make_tool_registrar(self):
        def tool(icon="🔧", title="Tool", desc="", command=None, tool_info=None):
            _command = command
            if tool_info is not None and _command is None:
                def _command(_ti=tool_info):
                    self.show_tool_panel(_ti)

            self.add_tool_card(
                icon      = icon,
                title     = title,
                desc      = desc,
                command   = _command,
                important = True,
            )

        return tool

    def _load_plugins(self) -> None:
        loaded = []

        if PLUGINS_DIR.exists():
            for py_file in sorted(PLUGINS_DIR.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                try:
                    mod = self._load_module(py_file)
                    if hasattr(mod, "register"):
                        mod.register(self)
                        loaded.append(py_file.stem)
                        print(f"[Plugin]    Loaded: {py_file.name}")
                except Exception as e:
                    print(f"[Plugin Error] {py_file.name}: {e}")

        if MAIN_TOOLS_DIR.exists():
            for py_file in sorted(MAIN_TOOLS_DIR.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                try:
                    mod = self._load_module(py_file)
                    if hasattr(mod, "register"):
                        mod.register(self._make_tool_registrar())
                        loaded.append(f"★ {py_file.stem}")
                        print(f"[MainTool]  Loaded: {py_file.name}")
                except Exception as e:
                    print(f"[MainTool Error] {py_file.name}: {e}")

        self.plugins = loaded
        self._update_plugins_label()

    def _update_plugins_label(self):
        if hasattr(self, "plugins_label"):
            if self.plugins:
                self.plugins_label.config(
                    text="\n".join(f"✅ {p}" for p in self.plugins)
                )
            else:
                self.plugins_label.config(text="No plugins loaded")

    # ----------------------------------------------------------
    #  Helpers
    # ----------------------------------------------------------

    def _set_status(self, msg: str):
        if hasattr(self, "status_label"):
            self.status_label.config(text=msg)

    def _on_close(self):
        self.config["window_width"]  = self.root.winfo_width()
        self.config["window_height"] = self.root.winfo_height()
        save_config(self.config)
        self.root.destroy()


# ============================================================
#                    ENTRY POINT
# ============================================================

if __name__ == "__main__":
    setup_directories()
    root = tk.Tk()
    app  = ShankToolsApp(root)
    root.mainloop()