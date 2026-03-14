"""
ui_system.py
------------
Auto-loader for main_tools/ directory.
Now supports both Toplevel panels and Embedded (in-window) panels.
"""

from __future__ import annotations

import importlib.util
import inspect
import platform
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional

# ════════════════════════════════════════════════════════════════════
#                        PATHS
# ════════════════════════════════════════════════════════════════════

MAIN_TOOLS_DIR = Path(__file__).parent / "main_tools"

# ════════════════════════════════════════════════════════════════════
#                     @tool DECORATOR
# ════════════════════════════════════════════════════════════════════

def tool(
    name: str = None,
    description: str = "",
    icon: str = "🔧",
    category: str = "General",
):
    def decorator(func: Callable) -> Callable:
        func._tool_info = {
            "name":        name or func.__name__.replace("_", " ").title(),
            "description": description or (func.__doc__ or "No description").strip(),
            "icon":        icon,
            "category":    category,
            "function":    func,
            "parameters":  _extract_parameters(func),
        }
        return func
    return decorator


def _extract_parameters(func: Callable) -> List[Dict]:
    params = []
    sig    = inspect.signature(func)
    hints  = getattr(func, "__annotations__", {})

    for pname, param in sig.parameters.items():
        if pname in ("self", "app"):
            continue
        params.append({
            "name":     pname,
            "type":     hints.get(pname, str),
            "default":  (
                None
                if param.default is inspect.Parameter.empty
                else param.default
            ),
            "required": param.default is inspect.Parameter.empty,
        })
    return params


# ════════════════════════════════════════════════════════════════════
#                     TOOL LOADER
# ════════════════════════════════════════════════════════════════════

_TOOL_META: Dict[str, Dict] = {
    "ktex":       {"icon": "🖼",  "category": "Assets",    "desc": "KTEX texture converter"},
    "luaQ":       {"icon": "📜",  "category": "Scripts",   "desc": "Lua bytecode tools"},
    "chui":       {"icon": "🎨",  "category": "UI",        "desc": "Character HUD editor"},
    "canim":      {"icon": "🎬",  "category": "Animation", "desc": "Character animation tool"},
    "canim-meta": {"icon": "📋",  "category": "Animation", "desc": "Animation metadata editor"},
}


def _load_module(path: Path):
    stem = path.stem
    spec = importlib.util.spec_from_file_location(stem, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        print(f"[ui_system] Error loading '{path.name}': {exc}")
        return None
    return mod


def discover_tools() -> List[Dict]:
    if not MAIN_TOOLS_DIR.exists():
        MAIN_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"[ui_system] Created directory: {MAIN_TOOLS_DIR}")
        return []

    results: List[Dict] = []

    for py_file in sorted(MAIN_TOOLS_DIR.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        mod = _load_module(py_file)
        if mod is None:
            continue

        stem = py_file.stem
        meta = _TOOL_META.get(stem, {})

        decorated = []
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name, None)
            if callable(obj) and hasattr(obj, "_tool_info"):
                decorated.append(obj._tool_info)

        if decorated:
            results.extend(decorated)
        else:
            results.append({
                "name":        stem.replace("-", " ").title(),
                "description": meta.get("desc", f"Tool from {py_file.name}"),
                "icon":        meta.get("icon", "🔧"),
                "category":    meta.get("category", "General"),
                "function":    None,
                "parameters":  [],
                "module":      mod,
                "source_file": py_file,
            })

    return results


# ════════════════════════════════════════════════════════════════════
#              CROSS-PLATFORM SCROLL HELPER
# ════════════════════════════════════════════════════════════════════

def _bind_panel_mousewheel(canvas: tk.Canvas):
    system = platform.system()

    def _on_mousewheel(event):
        if system == "Darwin":
            canvas.yview_scroll(-event.delta, "units")
        else:
            canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def _on_linux_up(event):
        canvas.yview_scroll(-1, "units")

    def _on_linux_down(event):
        canvas.yview_scroll(1, "units")

    def _on_enter(event):
        if system == "Linux":
            canvas.bind("<Button-4>", _on_linux_up)
            canvas.bind("<Button-5>", _on_linux_down)
        else:
            canvas.bind("<MouseWheel>", _on_mousewheel)

    def _on_leave(event):
        if system == "Linux":
            canvas.unbind("<Button-4>")
            canvas.unbind("<Button-5>")
        else:
            canvas.unbind("<MouseWheel>")

    canvas.bind("<Enter>", _on_enter)
    canvas.bind("<Leave>", _on_leave)


# ════════════════════════════════════════════════════════════════════
#               PARAMETER WIDGET BUILDER
# ════════════════════════════════════════════════════════════════════

class _ParamBuilder:
    def __init__(self, parent: tk.Widget, params: List[Dict], theme: Dict):
        self.parent     = parent
        self.params     = params
        self.theme      = theme
        self.input_vars: Dict[str, tk.Variable] = {}
        self._build()

    @property
    def _bg(self):   return self.theme["bg_panel"]
    @property
    def _fg(self):   return self.theme["text"]
    @property
    def _ebg(self):  return self.theme["entry_bg"]
    @property
    def _efg(self):  return self.theme["entry_fg"]
    @property
    def _bbg(self):  return self.theme["btn_bg"]
    @property
    def _bfg(self):  return self.theme["btn_fg"]

    def _build(self):
        for param in self.params:
            self._make_row(param)

    def _make_row(self, param: Dict):
        row = tk.Frame(self.parent, bg=self._bg)
        row.pack(fill="x", pady=6, padx=8)

        label_text = param["name"].replace("_", " ").title()
        if param["required"]:
            label_text += "  *"

        tk.Label(
            row, text=label_text,
            bg=self._bg, fg=self._fg,
            font=("Segoe UI", 10),
            width=18, anchor="w",
        ).pack(side="left")

        ptype   = param["type"]
        default = param.get("default")

        if ptype is bool:
            var = tk.BooleanVar(value=bool(default) if default is not None else False)
            tk.Checkbutton(
                row, variable=var, text="Enabled",
                bg=self._bg, fg=self._fg,
                selectcolor=self._bbg,
                activebackground=self._bg,
                activeforeground=self._fg,
            ).pack(side="left")

        elif ptype is int:
            var = tk.IntVar(value=int(default) if default is not None else 0)
            tk.Spinbox(
                row, from_=-99999, to=99999,
                textvariable=var, width=14,
                bg=self._ebg, fg=self._efg,
                buttonbackground=self._bbg,
                relief="flat",
            ).pack(side="left")

        elif ptype is float:
            var = tk.DoubleVar(
                value=float(default) if default is not None else 0.0
            )
            tk.Spinbox(
                row, from_=-99999, to=99999, increment=0.1,
                textvariable=var, width=14,
                bg=self._ebg, fg=self._efg,
                buttonbackground=self._bbg,
                relief="flat",
            ).pack(side="left")

        else:
            var = tk.StringVar(
                value=str(default) if default is not None else ""
            )
            is_path = any(
                x in param["name"].lower()
                for x in ("file", "path", "input", "output", "folder", "dir")
            )

            entry = tk.Entry(
                row, textvariable=var,
                width=28 if is_path else 35,
                bg=self._ebg, fg=self._efg,
                insertbackground=self._efg,
                relief="flat",
            )
            entry.pack(side="left", ipady=3)

            if is_path:
                tk.Button(
                    row, text="📁",
                    bg=self._bbg, fg=self._bfg,
                    relief="flat", cursor="hand2",
                    font=("Segoe UI", 9),
                    command=lambda v=var, n=param["name"]: self._browse(v, n),
                ).pack(side="left", padx=(5, 0))

        self.input_vars[param["name"]] = var

    @staticmethod
    def _browse(var: tk.StringVar, param_name: str):
        name_l = param_name.lower()
        if "folder" in name_l or "dir" in name_l:
            path = filedialog.askdirectory()
        elif "output" in name_l:
            path = filedialog.asksaveasfilename()
        else:
            path = filedialog.askopenfilename()
        if path:
            var.set(path)

    def collect(self) -> Optional[Dict[str, Any]]:
        values = {}
        for param in self.params:
            var = self.input_vars.get(param["name"])
            if var is None:
                continue
            val = var.get()
            if param["required"] and (val is None or val == ""):
                messagebox.showerror(
                    "Missing input",
                    f"'{param['name']}' is required.",
                )
                return None
            values[param["name"]] = val
        return values

    def reset(self):
        for param in self.params:
            var = self.input_vars.get(param["name"])
            if var is None:
                continue
            ptype   = param["type"]
            default = param.get("default")
            if ptype is bool:
                var.set(bool(default) if default is not None else False)
            elif ptype is int:
                var.set(int(default) if default is not None else 0)
            elif ptype is float:
                var.set(float(default) if default is not None else 0.0)
            else:
                var.set(str(default) if default is not None else "")


# ════════════════════════════════════════════════════════════════════
#          ★ EMBEDDED TOOL PANEL (داخل النافذة الرئيسية)
# ════════════════════════════════════════════════════════════════════

class EmbeddedToolPanel:
    """
    لوحة أداة مدمجة داخل الـ workspace بدلاً من نافذة منفصلة.
    تتضمن زر رجوع ⬅ للعودة لعرض البطاقات.
    """

    def __init__(
        self,
        parent:    tk.Widget,
        tool_info: Dict,
        theme:     Dict,
        status_cb: Callable[[str], None] = None,
        back_cb:   Callable[[], None] = None,
    ):
        self.parent    = parent
        self.tool_info = tool_info
        self.theme     = theme
        self.status_cb = status_cb
        self.back_cb   = back_cb
        self._builder: Optional[_ParamBuilder] = None

        self._build_ui()

    def _build_ui(self):
        t  = self.theme
        ti = self.tool_info

        # ── Header مع زر الرجوع ──────────────────────────────
        hdr = tk.Frame(self.parent, bg=t["header_bg"], height=56)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        # زر الرجوع ⬅
        back_btn = tk.Button(
            hdr, text="⬅  Back",
            bg=t["header_bg"], fg=t["text"],
            activebackground=t["bg_secondary"],
            activeforeground=t["text"],
            relief="flat", cursor="hand2",
            font=("Segoe UI", 10, "bold"),
            padx=10, pady=4,
            command=self.back_cb,
        )
        back_btn.pack(side="left", padx=(10, 5), pady=10)
        back_btn.bind("<Enter>", lambda e: back_btn.config(bg=t["bg_secondary"]))
        back_btn.bind("<Leave>", lambda e: back_btn.config(bg=t["header_bg"]))

        # فاصل عمودي
        tk.Frame(hdr, bg=t["border"], width=1).pack(
            side="left", fill="y", padx=5, pady=10
        )

        tk.Label(
            hdr, text=f"{ti['icon']}  {ti['name']}",
            bg=t["header_bg"], fg=t["accent"],
            font=("Segoe UI", 15, "bold"),
        ).pack(side="left", padx=12, pady=10)

        category = ti.get("category", "")
        if category:
            tk.Label(
                hdr, text=category,
                bg=t["header_bg"], fg=t["text_secondary"],
                font=("Segoe UI", 9),
            ).pack(side="right", padx=18)

        # ── Description ──────────────────────────────────────
        desc = ti.get("description", "")
        if desc and desc != "No description":
            tk.Label(
                self.parent, text=desc,
                bg=t["bg"], fg=t["text_secondary"],
                font=("Segoe UI", 9, "italic"),
                wraplength=600, justify="left",
            ).pack(anchor="w", padx=18, pady=(10, 0))

        # ── Separator ────────────────────────────────────────
        tk.Frame(self.parent, bg=t["border"], height=1).pack(
            fill="x", padx=18, pady=8
        )

        # ── Parameters panel (scrollable) ────────────────────
        params_outer = tk.Frame(self.parent, bg=t["bg_panel"], bd=0)
        params_outer.pack(fill="both", expand=True, padx=18, pady=4)

        canvas = tk.Canvas(
            params_outer, bg=t["bg_panel"], highlightthickness=0
        )
        vsb = ttk.Scrollbar(
            params_outer, orient="vertical", command=canvas.yview
        )
        canvas.configure(yscrollcommand=vsb.set)

        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        params_inner = tk.Frame(canvas, bg=t["bg_panel"])
        cwin = canvas.create_window(
            (0, 0), window=params_inner, anchor="nw"
        )

        params_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(cwin, width=e.width),
        )

        _bind_panel_mousewheel(canvas)

        params = ti.get("parameters", [])

        if params:
            self._builder = _ParamBuilder(params_inner, params, t)
        else:
            tk.Label(
                params_inner,
                text="This tool has no configurable parameters.",
                bg=t["bg_panel"], fg=t["text_secondary"],
                font=("Segoe UI", 10, "italic"),
            ).pack(pady=30)

        # ── Separator ────────────────────────────────────────
        tk.Frame(self.parent, bg=t["border"], height=1).pack(
            fill="x", padx=18, pady=6
        )

        # ── Button row ───────────────────────────────────────
        btn_row = tk.Frame(self.parent, bg=t["bg"])
        btn_row.pack(fill="x", padx=18, pady=(0, 8))

        self._status_lbl = tk.Label(
            btn_row, text="Ready",
            bg=t["bg"], fg=t["text_secondary"],
            font=("Segoe UI", 9),
        )
        self._status_lbl.pack(side="right", padx=10)

        tk.Button(
            btn_row, text="🗑  Clear",
            bg=t["bg_secondary"], fg=t["text"],
            activebackground=t["bg_panel"],
            activeforeground=t["text"],
            relief="flat", cursor="hand2",
            font=("Segoe UI", 10),
            padx=10, pady=6,
            command=self._clear,
        ).pack(side="left", padx=(0, 8))

        run_btn = tk.Button(
            btn_row,
            text=f"▶  Run  {ti['name']}",
            bg=t["btn_bg"], fg=t["btn_fg"],
            activebackground=t["btn_hover"],
            activeforeground=t["btn_fg"],
            relief="flat", cursor="hand2",
            font=("Segoe UI", 11, "bold"),
            padx=14, pady=7,
            command=self._run,
        )
        run_btn.pack(side="left")

        run_btn.bind(
            "<Enter>", lambda e: run_btn.config(bg=t["btn_hover"])
        )
        run_btn.bind(
            "<Leave>", lambda e: run_btn.config(bg=t["btn_bg"])
        )

        # ── Log / output area ────────────────────────────────
        log_frame = tk.LabelFrame(
            self.parent, text=" Output ",
            bg=t["bg"], fg=t["text_secondary"],
            font=("Segoe UI", 9),
            padx=6, pady=6,
        )
        log_frame.pack(fill="both", padx=18, pady=(0, 14), expand=False)

        self._log = tk.Text(
            log_frame, height=6,
            bg=t["bg_secondary"], fg=t["text"],
            insertbackground=t["text"],
            font=("Consolas", 9),
            relief="flat", wrap="word",
            state="disabled",
        )
        self._log.pack(fill="both", expand=True)

    # ── Actions ──────────────────────────────────────────────

    def _set_status(self, msg: str, color: str = None):
        color = color or self.theme["text_secondary"]
        try:
            self._status_lbl.config(text=msg, fg=color)
        except tk.TclError:
            pass
        if self.status_cb:
            self.status_cb(msg)

    def _log_write(self, msg: str):
        try:
            self._log.config(state="normal")
            self._log.insert(tk.END, msg + "\n")
            self._log.see(tk.END)
            self._log.config(state="disabled")
        except tk.TclError:
            pass

    def _clear(self):
        if self._builder:
            self._builder.reset()
        try:
            self._log.config(state="normal")
            self._log.delete("1.0", tk.END)
            self._log.config(state="disabled")
        except tk.TclError:
            pass
        self._set_status("Cleared")

    def _run(self):
        func = self.tool_info.get("function")

        if func is None:
            self._log_write(
                "⚠  This tool has no runnable function defined."
            )
            self._set_status("No function", self.theme["text_secondary"])
            return

        kwargs = {}
        if self._builder:
            kwargs = self._builder.collect()
            if kwargs is None:
                return

        self._set_status("Running…", self.theme["accent"])
        try:
            result = func(**kwargs)
            msg    = str(result) if result is not None else "Done."
            self._log_write(f"✅  {msg}")
            self._set_status("✅  Success", "#6ABF69")
        except Exception as exc:
            self._log_write(f"❌  Error: {exc}")
            self._set_status("❌  Error", "#E05050")
            messagebox.showerror("Tool Error", str(exc))


# ════════════════════════════════════════════════════════════════════
#         ToolPanel القديم (Toplevel) — يبقى للتوافق
# ════════════════════════════════════════════════════════════════════

class ToolPanel:
    """Kept for backward compatibility — plugins can still use it."""

    def __init__(self, parent, tool_info, theme, status_cb=None):
        self.tool_info = tool_info
        self.theme     = theme
        self.status_cb = status_cb
        self._builder  = None

        self.win = tk.Toplevel(parent)
        self.win.title(f"{tool_info['icon']}  {tool_info['name']}")
        self.win.geometry("560x520")
        self.win.minsize(480, 380)
        self.win.configure(bg=theme["bg"])
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        # يستخدم نفس UI القديم — مختصر هنا
        tk.Label(
            self.win, text=f"Use EmbeddedToolPanel for in-window experience",
            bg=theme["bg"], fg=theme["text_secondary"],
        ).pack(pady=20)

    def _on_close(self):
        self.win.destroy()


# ════════════════════════════════════════════════════════════════════
#                  PUBLIC REGISTRATION
# ════════════════════════════════════════════════════════════════════

def register(app) -> None:
    """
    Called by main.py's plugin loader.
    ★ الآن يفتح الأدوات داخل النافذة الرئيسية عبر app.show_tool_panel()
    """
    tools = discover_tools()

    if not tools:
        print("[ui_system] No tools found in main_tools/")
        return

    for ti in tools:
        def make_command(tool_info=ti):
            def open_panel():
                # ★ يستخدم show_tool_panel بدل Toplevel
                if hasattr(app, "show_tool_panel"):
                    app.show_tool_panel(tool_info)
                else:
                    # fallback للتوافق القديم
                    ToolPanel(
                        parent    = app.root,
                        tool_info = tool_info,
                        theme     = app.theme,
                        status_cb = getattr(app, "_set_status", None),
                    )
            return open_panel

        app.add_tool_card(
            icon      = ti["icon"],
            title     = ti["name"],
            desc      = ti["description"],
            command   = make_command(ti),
            important = True,
        )

    if hasattr(app, "_set_status"):
        app._set_status(f"Loaded {len(tools)} tool(s) from main_tools/")
    print(f"[ui_system] Registered {len(tools)} tool(s)")