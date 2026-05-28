#!/usr/bin/env python3
"""
NetConnect Node Installer GUI
A unified installer for network/compute sub-nodes with AI backend selection,
network configuration, and node status dashboard.
"""

import sys
import os
import socket
import json
import asyncio
import threading
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

# Allow running from nodes/common/gui/ directory
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from central.ai.model_adapter import ModelAdapter, ModelBackend
from nodes.common.network.client_node import NetworkClient
from nodes.common.compute.edge_compute import EdgeComputeNode

# ---------------------------------------------------------------------------
# Theme constants (dark, modern)
# ---------------------------------------------------------------------------
BG_COLOR = "#1e1e2e"
FG_COLOR = "#cdd6f4"
ACCENT_COLOR = "#89b4fa"
SUCCESS_COLOR = "#a6e3a1"
WARNING_COLOR = "#f9e2af"
ERROR_COLOR = "#f38ba8"
SURFACE_COLOR = "#313244"
HOVER_COLOR = "#45475a"
BORDER_COLOR = "#585b70"

FONT_FAMILY = "Segoe UI" if sys.platform == "win32" else "Helvetica"
FONT_SMALL = (FONT_FAMILY, 10)
FONT_NORMAL = (FONT_FAMILY, 11)
FONT_MEDIUM = (FONT_FAMILY, 12, "bold")
FONT_LARGE = (FONT_FAMILY, 16, "bold")

BACKEND_PORTS = {
    "Ollama": 11434,
    "vLLM": 8000,
    "LM Studio": 1234,
    "OpenAI": 443,
}

BACKEND_ENUM_MAP = {
    "Ollama": ModelBackend.OLLAMA,
    "vLLM": ModelBackend.VLLM,
    "LM Studio": ModelBackend.LM_STUDIO,
    "OpenAI": ModelBackend.OPENAI,
}


def _tk_color(hex_color: str, alpha: float = 1.0) -> str:
    """Return hex color as-is (tkinter doesn't support alpha)."""
    return hex_color


# ---------------------------------------------------------------------------
# Async helper for tkinter
# ---------------------------------------------------------------------------
class AsyncTkRunner:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._start_loop()

    def _start_loop(self):
        def run_loop():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_forever()

        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()
        # wait briefly until loop is ready
        while self.loop is None:
            time.sleep(0.01)

    def run(self, coro):
        """Schedule coroutine on the event loop and return a Future."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self):
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)


# ---------------------------------------------------------------------------
# Style setup
# ---------------------------------------------------------------------------
def setup_styles(root: tk.Tk):
    style = ttk.Style(root)
    # Try clam theme first, fallback to default if unavailable
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    # Only configure styles supported by the current ttk version
    try:
        style.configure("TFrame", background=BG_COLOR)
        style.configure("TLabel", background=BG_COLOR, foreground=FG_COLOR, font=FONT_NORMAL)
        style.configure("TButton", background=SURFACE_COLOR, foreground=FG_COLOR, font=FONT_NORMAL)
        style.map("TButton", background=[("active", HOVER_COLOR)])

        style.configure("Accent.TButton", background=ACCENT_COLOR, foreground=BG_COLOR, font=FONT_NORMAL)

        style.configure("TEntry", fieldbackground=SURFACE_COLOR, foreground=FG_COLOR)
        style.configure("TCombobox", fieldbackground=SURFACE_COLOR, foreground=FG_COLOR, background=SURFACE_COLOR)

        style.configure("Horizontal.TProgressbar", background=ACCENT_COLOR, troughcolor=SURFACE_COLOR)
    except tk.TclError:
        pass

    root.configure(bg=BG_COLOR)


# ---------------------------------------------------------------------------
# Custom widgets
# ---------------------------------------------------------------------------
class StatusBadge(tk.Frame):
    def __init__(self, parent, text: str = "Unknown", status: str = "neutral", **kwargs):
        super().__init__(parent, bg=BG_COLOR, **kwargs)
        self._status = status
        self._text = text
        self.label = tk.Label(self, text=text, font=FONT_SMALL,
                              bg=self._bg_for_status(status),
                              fg=BG_COLOR,
                              padx=8, pady=2, relief="flat", bd=0)
        self.label.pack()

    def _bg_for_status(self, status: str) -> str:
        return {
            "success": SUCCESS_COLOR,
            "warning": WARNING_COLOR,
            "error": ERROR_COLOR,
            "info": ACCENT_COLOR,
        }.get(status, BORDER_COLOR)

    def set(self, text: str, status: str = "neutral"):
        self._text = text
        self._status = status
        self.label.config(text=text, bg=self._bg_for_status(status))


class LogPanel(scrolledtext.ScrolledText):
    def __init__(self, parent, height: int = 8, **kwargs):
        super().__init__(parent, height=height,
                         bg=SURFACE_COLOR, fg=FG_COLOR,
                         insertbackground=FG_COLOR,
                         font=("Consolas", 10) if sys.platform == "win32" else ("Menlo", 10),
                         relief="flat", state="disabled", wrap="word", **kwargs)

    def append(self, message: str, tag: str = ""):
        self.configure(state="normal")
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        self.insert("end", line)
        self.configure(state="disabled")
        self.see("end")


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class NodeInstallerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("NetConnect Node Installer")
        self.root.geometry("960x720")
        self.root.minsize(880, 640)
        self.root.configure(bg=BG_COLOR)

        setup_styles(root)

        self.async_runner = AsyncTkRunner(root)

        # State
        self.current_step = tk.IntVar(value=1)
        self.selected_backend = tk.StringVar(value="Ollama")
        self.backend_url = tk.StringVar(value="http://localhost")
        self.backend_port = tk.StringVar(value="11434")
        self.backend_model = tk.StringVar(value="")
        self.multicast_group = tk.StringVar(value="224.0.0.1")
        self.multicast_port = tk.StringVar(value="5000")
        self.node_name = tk.StringVar(value=f"node-{uuid.uuid4().hex[:6]}")

        self.ai_adapter: Optional[ModelAdapter] = None
        self.network_client: Optional[NetworkClient] = None
        self.edge_node: Optional[EdgeComputeNode] = None
        self._node_task: Optional[Any] = None
        self._chat_history: List[Dict[str, str]] = []
        self._connected_nodes: List[Dict] = []
        self._logs_lock = threading.Lock()

        self._build_ui()
        self._apply_dark_to_tk_widgets(root)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        # Header
        header = tk.Frame(self.root, bg=SURFACE_COLOR, height=60)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)

        tk.Label(header, text="NetConnect Node Installer",
                 bg=SURFACE_COLOR, fg=FG_COLOR, font=FONT_LARGE).pack(side="left", padx=20, pady=10)

        self.step_label = tk.Label(header, text="Step 1 of 3: AI Backend",
                                   bg=SURFACE_COLOR, fg=ACCENT_COLOR, font=FONT_MEDIUM)
        self.step_label.pack(side="right", padx=20, pady=10)

        # Content area
        self.content = tk.Frame(self.root, bg=BG_COLOR)
        self.content.pack(fill="both", expand=True, padx=20, pady=15)

        # Wizard frames
        self.step_frames: Dict[int, tk.Frame] = {}
        for i in range(1, 4):
            frame = tk.Frame(self.content, bg=BG_COLOR)
            self.step_frames[i] = frame

        self._build_step1(self.step_frames[1])
        self._build_step2(self.step_frames[2])
        self._build_step3(self.step_frames[3])

        # Navigation bar
        nav = tk.Frame(self.root, bg=SURFACE_COLOR, height=50)
        nav.pack(side="bottom", fill="x")
        nav.pack_propagate(False)

        self.back_btn = ttk.Button(nav, text="Back", command=self._prev_step)
        self.back_btn.pack(side="left", padx=15, pady=8)

        self.next_btn = ttk.Button(nav, text="Next", style="Accent.TButton", command=self._next_step)
        self.next_btn.pack(side="right", padx=15, pady=8)

        self._show_step(1)

    def _build_step1(self, parent: tk.Frame):
        # Title
        tk.Label(parent, text="Select AI Backend", bg=BG_COLOR, fg=FG_COLOR,
                 font=FONT_LARGE).pack(anchor="w", pady=(0, 15))

        # Backend selection card
        card = tk.Frame(parent, bg=SURFACE_COLOR, padx=15, pady=15)
        card.pack(fill="x", pady=5)
        card.configure(highlightbackground=BORDER_COLOR, highlightthickness=1)

        row = 0
        tk.Label(card, text="Backend:", bg=SURFACE_COLOR, fg=FG_COLOR,
                 font=FONT_NORMAL).grid(row=row, column=0, sticky="w", padx=5, pady=8)

        backends = list(BACKEND_PORTS.keys())
        self.backend_combo = ttk.Combobox(card, values=backends,
                                          textvariable=self.selected_backend,
                                          state="readonly", width=20)
        self.backend_combo.grid(row=row, column=1, sticky="w", padx=5, pady=8)
        self.backend_combo.bind("<<ComboboxSelected>>", self._on_backend_changed)

        self.auto_scan_btn = ttk.Button(card, text="Auto-Scan", command=self._auto_scan_backends)
        self.auto_scan_btn.grid(row=row, column=2, sticky="w", padx=10, pady=8)

        row += 1
        tk.Label(card, text="Base URL:", bg=SURFACE_COLOR, fg=FG_COLOR,
                 font=FONT_NORMAL).grid(row=row, column=0, sticky="w", padx=5, pady=8)
        self.url_entry = ttk.Entry(card, textvariable=self.backend_url, width=30)
        self.url_entry.grid(row=row, column=1, sticky="w", padx=5, pady=8)

        row += 1
        tk.Label(card, text="Port:", bg=SURFACE_COLOR, fg=FG_COLOR,
                 font=FONT_NORMAL).grid(row=row, column=0, sticky="w", padx=5, pady=8)
        self.port_entry = ttk.Entry(card, textvariable=self.backend_port, width=12)
        self.port_entry.grid(row=row, column=1, sticky="w", padx=5, pady=8)

        row += 1
        tk.Label(card, text="Model:", bg=SURFACE_COLOR, fg=FG_COLOR,
                 font=FONT_NORMAL).grid(row=row, column=0, sticky="w", padx=5, pady=8)
        self.model_entry = ttk.Entry(card, textvariable=self.backend_model, width=30)
        self.model_entry.grid(row=row, column=1, sticky="w", padx=5, pady=8)

        row += 1
        self.ai_status_badge = StatusBadge(card, text="Not tested", status="warning")
        self.ai_status_badge.grid(row=row, column=0, columnspan=3, sticky="w", padx=5, pady=10)

        # Auto-scan results
        row += 1
        self.scan_result_label = tk.Label(card, text="", bg=SURFACE_COLOR, fg=FG_COLOR,
                                          font=FONT_SMALL, justify="left", wraplength=700)
        self.scan_result_label.grid(row=row, column=0, columnspan=3, sticky="w", padx=5, pady=5)

        # Test connection button
        test_btn = ttk.Button(parent, text="Test AI Connection", command=self._test_ai_connection)
        test_btn.pack(anchor="w", pady=15)

    def _build_step2(self, parent: tk.Frame):
        tk.Label(parent, text="Network Configuration", bg=BG_COLOR, fg=FG_COLOR,
                 font=FONT_LARGE).pack(anchor="w", pady=(0, 15))

        card = tk.Frame(parent, bg=SURFACE_COLOR, padx=15, pady=15)
        card.pack(fill="x", pady=5)
        card.configure(highlightbackground=BORDER_COLOR, highlightthickness=1)

        row = 0
        tk.Label(card, text="Node Name:", bg=SURFACE_COLOR, fg=FG_COLOR,
                 font=FONT_NORMAL).grid(row=row, column=0, sticky="w", padx=5, pady=8)
        ttk.Entry(card, textvariable=self.node_name, width=30).grid(row=row, column=1, sticky="w", padx=5, pady=8)

        row += 1
        tk.Label(card, text="Multicast Group:", bg=SURFACE_COLOR, fg=FG_COLOR,
                 font=FONT_NORMAL).grid(row=row, column=0, sticky="w", padx=5, pady=8)
        ttk.Entry(card, textvariable=self.multicast_group, width=20).grid(row=row, column=1, sticky="w", padx=5, pady=8)

        row += 1
        tk.Label(card, text="Multicast Port:", bg=SURFACE_COLOR, fg=FG_COLOR,
                 font=FONT_NORMAL).grid(row=row, column=0, sticky="w", padx=5, pady=8)
        ttk.Entry(card, textvariable=self.multicast_port, width=12).grid(row=row, column=1, sticky="w", padx=5, pady=8)

        row += 1
        self.net_status_badge = StatusBadge(card, text="Not configured", status="warning")
        self.net_status_badge.grid(row=row, column=0, columnspan=2, sticky="w", padx=5, pady=10)

        info = tk.Label(parent,
                        text="The node will use multicast to discover the central router. "
                             "Ensure your network allows UDP multicast traffic.",
                        bg=BG_COLOR, fg=BORDER_COLOR, font=FONT_SMALL, wraplength=700, justify="left")
        info.pack(anchor="w", pady=15)

    def _build_step3(self, parent: tk.Frame):
        tk.Label(parent, text="Start Node", bg=BG_COLOR, fg=FG_COLOR,
                 font=FONT_LARGE).pack(anchor="w", pady=(0, 10))

        # Top control bar
        ctrl = tk.Frame(parent, bg=BG_COLOR)
        ctrl.pack(fill="x", pady=5)

        self.start_btn = ttk.Button(ctrl, text="Start Node", style="Accent.TButton", command=self._start_node)
        self.start_btn.pack(side="left", padx=(0, 10))

        self.stop_btn = ttk.Button(ctrl, text="Stop Node", command=self._stop_node, state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 10))

        self.node_status_badge = StatusBadge(ctrl, text="Stopped", status="error")
        self.node_status_badge.pack(side="left", padx=10)

        # Dashboard notebook
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill="both", expand=True, pady=10)

        # -- Dashboard tab
        dash = tk.Frame(self.notebook, bg=BG_COLOR)
        self.notebook.add(dash, text="Dashboard")
        self._build_dashboard(dash)

        # -- Chat tab
        chat = tk.Frame(self.notebook, bg=BG_COLOR)
        self.notebook.add(chat, text="Chat")
        self._build_chat(chat)

        # -- Logs tab
        logs = tk.Frame(self.notebook, bg=BG_COLOR)
        self.notebook.add(logs, text="Logs")
        self._build_logs(logs)

    def _build_dashboard(self, parent: tk.Frame):
        # Cards grid
        cards = tk.Frame(parent, bg=BG_COLOR)
        cards.pack(fill="both", expand=True)

        # Connection card
        conn_card = tk.LabelFrame(cards, text=" Connection ", bg=SURFACE_COLOR, fg=FG_COLOR,
                                  font=FONT_MEDIUM, padx=10, pady=10)
        conn_card.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        tk.Label(conn_card, text="Router:", bg=SURFACE_COLOR, fg=BORDER_COLOR, font=FONT_SMALL).pack(anchor="w")
        self.dash_router = tk.Label(conn_card, text="Not discovered", bg=SURFACE_COLOR, fg=FG_COLOR, font=FONT_NORMAL)
        self.dash_router.pack(anchor="w", pady=2)
        tk.Label(conn_card, text="Connected Nodes:", bg=SURFACE_COLOR, fg=BORDER_COLOR, font=FONT_SMALL).pack(anchor="w", pady=(8, 0))
        self.dash_nodes = tk.Label(conn_card, text="0", bg=SURFACE_COLOR, fg=FG_COLOR, font=FONT_LARGE)
        self.dash_nodes.pack(anchor="w", pady=2)

        # AI card
        ai_card = tk.LabelFrame(cards, text=" AI Backend ", bg=SURFACE_COLOR, fg=FG_COLOR,
                                font=FONT_MEDIUM, padx=10, pady=10)
        ai_card.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        tk.Label(ai_card, text="Backend:", bg=SURFACE_COLOR, fg=BORDER_COLOR, font=FONT_SMALL).pack(anchor="w")
        self.dash_backend = tk.Label(ai_card, text="-", bg=SURFACE_COLOR, fg=FG_COLOR, font=FONT_NORMAL)
        self.dash_backend.pack(anchor="w", pady=2)
        tk.Label(ai_card, text="Model:", bg=SURFACE_COLOR, fg=BORDER_COLOR, font=FONT_SMALL).pack(anchor="w", pady=(8, 0))
        self.dash_model = tk.Label(ai_card, text="-", bg=SURFACE_COLOR, fg=FG_COLOR, font=FONT_NORMAL)
        self.dash_model.pack(anchor="w", pady=2)
        tk.Label(ai_card, text="Status:", bg=SURFACE_COLOR, fg=BORDER_COLOR, font=FONT_SMALL).pack(anchor="w", pady=(8, 0))
        self.dash_ai_status = StatusBadge(ai_card, text="Unknown", status="neutral")
        self.dash_ai_status.pack(anchor="w", pady=2)

        # Tasks card
        task_card = tk.LabelFrame(cards, text=" Tasks ", bg=SURFACE_COLOR, fg=FG_COLOR,
                                  font=FONT_MEDIUM, padx=10, pady=10)
        task_card.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        tk.Label(task_card, text="Current Status:", bg=SURFACE_COLOR, fg=BORDER_COLOR, font=FONT_SMALL).pack(anchor="w")
        self.dash_task_status = tk.Label(task_card, text="Idle", bg=SURFACE_COLOR, fg=FG_COLOR, font=FONT_NORMAL)
        self.dash_task_status.pack(anchor="w", pady=2)
        tk.Label(task_card, text="Completed:", bg=SURFACE_COLOR, fg=BORDER_COLOR, font=FONT_SMALL).pack(anchor="w", pady=(8, 0))
        self.dash_completed = tk.Label(task_card, text="0", bg=SURFACE_COLOR, fg=FG_COLOR, font=FONT_LARGE)
        self.dash_completed.pack(anchor="w", pady=2)

        # Node info card
        info_card = tk.LabelFrame(cards, text=" Node Info ", bg=SURFACE_COLOR, fg=FG_COLOR,
                                  font=FONT_MEDIUM, padx=10, pady=10)
        info_card.grid(row=1, column=1, sticky="nsew", padx=8, pady=8)
        tk.Label(info_card, text="Node ID:", bg=SURFACE_COLOR, fg=BORDER_COLOR, font=FONT_SMALL).pack(anchor="w")
        self.dash_node_id = tk.Label(info_card, text="-", bg=SURFACE_COLOR, fg=FG_COLOR, font=FONT_SMALL)
        self.dash_node_id.pack(anchor="w", pady=2)
        tk.Label(info_card, text="Name:", bg=SURFACE_COLOR, fg=BORDER_COLOR, font=FONT_SMALL).pack(anchor="w", pady=(8, 0))
        self.dash_node_name = tk.Label(info_card, text="-", bg=SURFACE_COLOR, fg=FG_COLOR, font=FONT_NORMAL)
        self.dash_node_name.pack(anchor="w", pady=2)

        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)
        cards.rowconfigure(0, weight=1)
        cards.rowconfigure(1, weight=1)

    def _build_chat(self, parent: tk.Frame):
        # Chat history
        self.chat_display = scrolledtext.ScrolledText(parent, state="disabled", wrap="word",
                                                       bg=SURFACE_COLOR, fg=FG_COLOR,
                                                       insertbackground=FG_COLOR,
                                                       font=("Consolas", 10) if sys.platform == "win32" else ("Menlo", 10),
                                                       relief="flat")
        self.chat_display.pack(fill="both", expand=True, pady=(0, 10))
        self.chat_display.tag_config("user", foreground=ACCENT_COLOR)
        self.chat_display.tag_config("assistant", foreground=SUCCESS_COLOR)
        self.chat_display.tag_config("system", foreground=BORDER_COLOR)

        # Input area
        input_frame = tk.Frame(parent, bg=BG_COLOR)
        input_frame.pack(fill="x")

        self.chat_input = ttk.Entry(input_frame, font=FONT_NORMAL)
        self.chat_input.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.chat_input.bind("<Return>", lambda e: self._send_chat())

        send_btn = ttk.Button(input_frame, text="Send", command=self._send_chat)
        send_btn.pack(side="right")

    def _build_logs(self, parent: tk.Frame):
        self.log_panel = LogPanel(parent, height=20)
        self.log_panel.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _apply_dark_to_tk_widgets(self, widget):
        """Recursively set bg/fg for plain tk widgets not covered by ttk styles."""
        for w in widget.winfo_children():
            try:
                if isinstance(w, (tk.Label, tk.Frame)):
                    if w.cget("bg") not in (SURFACE_COLOR, BG_COLOR, SUCCESS_COLOR, WARNING_COLOR, ERROR_COLOR, ACCENT_COLOR, BORDER_COLOR):
                        w.configure(bg=BG_COLOR)
                    if isinstance(w, tk.Label) and w.cget("fg") not in (FG_COLOR, ACCENT_COLOR, SUCCESS_COLOR, WARNING_COLOR, ERROR_COLOR, BORDER_COLOR, BG_COLOR):
                        w.configure(fg=FG_COLOR)
            except Exception:
                pass
            self._apply_dark_to_tk_widgets(w)

    def _show_step(self, step: int):
        for i, frame in self.step_frames.items():
            if i == step:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        self.current_step.set(step)
        self.step_label.config(text=f"Step {step} of 3: {['AI Backend', 'Network', 'Start Node'][step - 1]}")
        self.back_btn.config(state="normal" if step > 1 else "disabled")
        if step == 3:
            self.next_btn.config(text="Finish", state="disabled")
        else:
            self.next_btn.config(text="Next", state="normal")

    def _next_step(self):
        step = self.current_step.get()
        if step < 3:
            self._show_step(step + 1)

    def _prev_step(self):
        step = self.current_step.get()
        if step > 1:
            self._show_step(step - 1)

    def _on_backend_changed(self, event=None):
        name = self.selected_backend.get()
        port = BACKEND_PORTS.get(name, 11434)
        self.backend_port.set(str(port))

    def _log(self, message: str):
        with self._logs_lock:
            self.root.after(0, lambda: self.log_panel.append(message))

    # ------------------------------------------------------------------
    # Auto-scan
    # ------------------------------------------------------------------
    def _auto_scan_backends(self):
        self.scan_result_label.config(text="Scanning...", fg=ACCENT_COLOR)
        self.async_runner.run(self._do_auto_scan())

    async def _do_auto_scan(self):
        results = []
        for name, port in BACKEND_PORTS.items():
            url = f"http://localhost:{port}"
            try:
                if name == "OpenAI":
                    # OpenAI usually requires auth; just check if port 443 is reachable
                    sock = socket.create_connection(("api.openai.com", 443), timeout=3)
                    sock.close()
                    results.append((name, port, True, "Port reachable"))
                else:
                    backend = BACKEND_ENUM_MAP[name]
                    adapter = ModelAdapter(backend, "http://localhost", port)
                    ok = await adapter.health_check()
                    if ok:
                        models = await adapter.list_models()
                        model_info = f"{len(models)} models" if models else "healthy"
                        results.append((name, port, True, model_info))
                    else:
                        results.append((name, port, False, "No response"))
            except Exception as e:
                results.append((name, port, False, str(e)))

        self.root.after(0, lambda: self._show_scan_results(results))

    def _show_scan_results(self, results: List[tuple]):
        lines = []
        found = []
        for name, port, ok, info in results:
            status = "✅" if ok else "❌"
            lines.append(f"{status} {name} (port {port}): {info}")
            if ok:
                found.append(name)
        self.scan_result_label.config(text="\n".join(lines), fg=FG_COLOR)
        if found:
            self.selected_backend.set(found[0])
            self._on_backend_changed()
            self.ai_status_badge.set(f"Auto-selected {found[0]}", "success")
        else:
            self.ai_status_badge.set("No backend found", "error")

    # ------------------------------------------------------------------
    # AI connection test
    # ------------------------------------------------------------------
    def _test_ai_connection(self):
        self.ai_status_badge.set("Testing...", "info")
        self.async_runner.run(self._do_test_ai())

    async def _do_test_ai(self):
        try:
            name = self.selected_backend.get()
            port = int(self.backend_port.get())
            url = self.backend_url.get()
            backend = BACKEND_ENUM_MAP[name]
            adapter = ModelAdapter(backend, url, port)
            ok = await adapter.health_check()
            if ok:
                models = await adapter.list_models()
                model_str = f" | Models: {len(models)}"
                if models and not self.backend_model.get():
                    self.root.after(0, lambda: self.backend_model.set(models[0]))
                self.root.after(0, lambda: self.ai_status_badge.set(f"Connected{model_str}", "success"))
                self.ai_adapter = adapter
            else:
                self.root.after(0, lambda: self.ai_status_badge.set("Connection failed", "error"))
        except Exception as e:
            self.root.after(0, lambda: self.ai_status_badge.set(f"Error: {e}", "error"))

    # ------------------------------------------------------------------
    # Start / Stop node
    # ------------------------------------------------------------------
    def _start_node(self):
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.node_status_badge.set("Starting...", "info")
        self._log("Starting node...")
        self.async_runner.run(self._do_start_node())

    async def _do_start_node(self):
        try:
            name = self.selected_backend.get()
            port = int(self.backend_port.get())
            url = self.backend_url.get()
            backend = BACKEND_ENUM_MAP[name]

            self.edge_node = EdgeComputeNode(
                node_name=self.node_name.get(),
                ai_backend=backend,
                ai_port=port,
                capabilities=["inference", "embedding"]
            )
            # Override adapter URL if needed
            self.edge_node.ai_adapter = ModelAdapter(backend, url, port)
            if self.backend_model.get():
                self.edge_node.ai_adapter.set_default_model(self.backend_model.get())

            self.network_client = self.edge_node.network_client
            self.network_client.set_connection_callbacks(
                on_connected=self._on_net_connected,
                on_disconnected=self._on_net_disconnected,
                on_message=self._on_net_message
            )

            self._running = True
            self._update_dashboard_loop()

            self.root.after(0, lambda: self.node_status_badge.set("Running", "success"))
            self.root.after(0, lambda: self._log("Node started successfully"))

            await self.edge_node.start()
        except Exception as e:
            self.root.after(0, lambda: self.node_status_badge.set(f"Error: {e}", "error"))
            self.root.after(0, lambda: self._log(f"Failed to start node: {e}"))
            self.root.after(0, lambda: self.start_btn.config(state="normal"))
            self.root.after(0, lambda: self.stop_btn.config(state="disabled"))

    def _stop_node(self):
        self._log("Stopping node...")
        self.async_runner.run(self._do_stop_node())

    async def _do_stop_node(self):
        try:
            self._running = False
            if self.edge_node:
                await self.edge_node.stop()
                self.edge_node = None
            self.network_client = None
            self.root.after(0, lambda: self.node_status_badge.set("Stopped", "error"))
            self.root.after(0, lambda: self.start_btn.config(state="normal"))
            self.root.after(0, lambda: self.stop_btn.config(state="disabled"))
            self.root.after(0, lambda: self._log("Node stopped"))
        except Exception as e:
            self.root.after(0, lambda: self._log(f"Error stopping node: {e}"))

    def _on_net_connected(self, host, port):
        self.root.after(0, lambda: self._log(f"Connected to router at {host}:{port}"))
        self.root.after(0, lambda: self.dash_router.config(text=f"{host}:{port}"))

    def _on_net_disconnected(self):
        self.root.after(0, lambda: self._log("Disconnected from router"))
        self.root.after(0, lambda: self.dash_router.config(text="Not discovered"))

    def _on_net_message(self, msg: Dict):
        self.root.after(0, lambda: self._log(f"Message: {msg.get('type', 'unknown')}"))

    # ------------------------------------------------------------------
    # Dashboard updater
    # ------------------------------------------------------------------
    def _update_dashboard_loop(self):
        if not self._running:
            return
        self.async_runner.run(self._do_dashboard_update())
        self.root.after(3000, self._update_dashboard_loop)

    async def _do_dashboard_update(self):
        try:
            if self.edge_node:
                status = await self.edge_node.get_status()
                self.root.after(0, lambda s=status: self._apply_dashboard_status(s))
            if self.network_client:
                info = self.network_client.get_info()
                self.root.after(0, lambda i=info: self._apply_network_info(i))
        except Exception:
            pass

    def _apply_dashboard_status(self, status: Dict):
        self.dash_backend.config(text=self.selected_backend.get())
        self.dash_model.config(text=self.backend_model.get() or "-")
        ai_ok = status.get("ai_available", False)
        self.dash_ai_status.set("Available" if ai_ok else "Unavailable",
                                "success" if ai_ok else "error")
        self.dash_task_status.config(text=status.get("task_status", "Idle").capitalize())
        self.dash_completed.config(text=str(status.get("tasks_completed", 0)))
        self.dash_node_id.config(text=status.get("node_id", "-")[:16] + "...")
        self.dash_node_name.config(text=status.get("node_name", "-"))

    def _apply_network_info(self, info: Dict):
        connected = info.get("connected", False)
        self.dash_nodes.config(text=str(len(info.get("capabilities", []))))
        if connected:
            self.net_status_badge.set("Connected", "success")
        else:
            self.net_status_badge.set("Disconnected", "warning")

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    def _send_chat(self):
        text = self.chat_input.get().strip()
        if not text:
            return
        self._append_chat("user", text)
        self.chat_input.delete(0, "end")
        self.async_runner.run(self._do_chat(text))

    async def _do_chat(self, text: str):
        try:
            adapter = None
            if self.edge_node:
                adapter = self.edge_node.ai_adapter
            elif self.ai_adapter:
                adapter = self.ai_adapter
            else:
                self.root.after(0, lambda: self._append_chat("system", "No AI backend configured. Please test connection first."))
                return

            self.root.after(0, lambda: self._append_chat("system", "Thinking..."))
            result = await adapter.generate(text)
            response = result.get("response", "")
            if not response and "error" in result:
                response = f"[Error: {result['error']}]"
            self.root.after(0, lambda: self._replace_thinking(response))
        except Exception as e:
            self.root.after(0, lambda: self._replace_thinking(f"[Error: {e}]"))

    def _append_chat(self, role: str, text: str):
        self.chat_display.configure(state="normal")
        prefix = {"user": "You: ", "assistant": "AI: ", "system": "System: "}.get(role, "")
        self.chat_display.insert("end", f"{prefix}{text}\n\n", role)
        self.chat_display.configure(state="disabled")
        self.chat_display.see("end")

    def _replace_thinking(self, text: str):
        self.chat_display.configure(state="normal")
        # Remove last "Thinking..." line
        content = self.chat_display.get("1.0", "end-1c")
        idx = content.rfind("System: Thinking...")
        if idx != -1:
            # tk text index calculation is tricky; simpler to clear and rewrite or just append correction
            # Here we just append the real response for simplicity
            pass
        self.chat_display.insert("end", f"AI: {text}\n\n", "assistant")
        self.chat_display.configure(state="disabled")
        self.chat_display.see("end")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def on_close(self):
        if self.edge_node:
            self._stop_node()
        self.async_runner.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = NodeInstallerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
