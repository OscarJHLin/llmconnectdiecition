import sys
import os
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog
from typing import Dict, List, Optional, Any
import asyncio
import threading
import time
import random

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from central.ai.model_adapter import ModelAdapter, ModelBackend
from central.compute.central_compute import CentralComputeNode, TaskType, TaskStatus
from central.network.central_node import CentralNetworkNode, NodeStatus, NodeType


class DarkTheme:
    BG = "#1e1e2e"
    FG = "#cdd6f4"
    ACCENT = "#89b4fa"
    ACCENT_HOVER = "#b4befe"
    SIDEBAR_BG = "#181825"
    CARD_BG = "#313244"
    SUCCESS = "#a6e3a1"
    WARNING = "#f9e2af"
    ERROR = "#f38ba8"
    ONLINE = "#a6e3a1"
    OFFLINE = "#f38ba8"
    BUSY = "#f9e2af"
    IDLE = "#89b4fa"
    BORDER = "#45475a"
    INPUT_BG = "#313244"


def style_widget(widget, bg=None, fg=None, font=None):
    if bg:
        widget.configure(background=bg)
    if fg:
        widget.configure(foreground=fg)
    if font:
        widget.configure(font=font)


class SidebarButton(tk.Button):
    def __init__(self, master, text, command, icon=None, **kwargs):
        self.default_bg = DarkTheme.SIDEBAR_BG
        self.active_bg = DarkTheme.CARD_BG
        self.hover_bg = "#1e1e2e"
        super().__init__(
            master,
            text=f"  {text}",
            command=command,
            bg=self.default_bg,
            fg=DarkTheme.FG,
            activebackground=self.active_bg,
            activeforeground=DarkTheme.ACCENT,
            bd=0,
            padx=20,
            pady=12,
            anchor="w",
            font=("Segoe UI", 11),
            cursor="hand2",
            **kwargs
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._active = False

    def _on_enter(self, event):
        if not self._active:
            self.configure(bg=self.hover_bg)

    def _on_leave(self, event):
        if not self._active:
            self.configure(bg=self.default_bg)

    def set_active(self, active: bool):
        self._active = active
        if active:
            self.configure(bg=self.active_bg, fg=DarkTheme.ACCENT, font=("Segoe UI", 11, "bold"))
        else:
            self.configure(bg=self.default_bg, fg=DarkTheme.FG, font=("Segoe UI", 11))


class ScrollableFrame(tk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg=DarkTheme.BG, **kwargs)
        self.canvas = tk.Canvas(self, bg=DarkTheme.BG, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg=DarkTheme.BG)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class CenterDashboard:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Central Compute Node Dashboard")
        self.root.geometry("1200x800")
        self.root.configure(bg=DarkTheme.BG)
        self.root.minsize(900, 600)

        self.central_compute: Optional[CentralComputeNode] = None
        self.central_network: Optional[CentralNetworkNode] = None
        self.model_adapter: Optional[ModelAdapter] = None

        self.chat_history: List[Dict[str, str]] = []
        self.tasks_data: Dict[str, Any] = {}
        self.nodes_data: Dict[str, Any] = {}

        self._build_ui()
        self._init_backend()
        self._start_refresh_loop()

    def _build_ui(self):
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

        self.sidebar = tk.Frame(self.root, bg=DarkTheme.SIDEBAR_BG, width=200)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(7, weight=1)

        title = tk.Label(
            self.sidebar,
            text="Central Node",
            bg=DarkTheme.SIDEBAR_BG,
            fg=DarkTheme.ACCENT,
            font=("Segoe UI", 16, "bold"),
            pady=20
        )
        title.grid(row=0, column=0, sticky="ew")

        self.nav_buttons = {}
        nav_items = [
            ("chat", "Chat"),
            ("nodes", "Nodes"),
            ("network", "Network"),
            ("tasks", "Tasks"),
            ("settings", "Settings"),
        ]

        for idx, (key, label) in enumerate(nav_items, start=1):
            btn = SidebarButton(self.sidebar, text=label, command=lambda k=key: self._show_panel(k))
            btn.grid(row=idx, column=0, sticky="ew", padx=8, pady=2)
            self.nav_buttons[key] = btn

        status_frame = tk.Frame(self.sidebar, bg=DarkTheme.SIDEBAR_BG)
        status_frame.grid(row=8, column=0, sticky="ew", padx=10, pady=10)

        self.status_label = tk.Label(
            status_frame,
            text="Status: Initializing...",
            bg=DarkTheme.SIDEBAR_BG,
            fg=DarkTheme.WARNING,
            font=("Segoe UI", 9)
        )
        self.status_label.pack(anchor="w")

        self.content_frame = tk.Frame(self.root, bg=DarkTheme.BG)
        self.content_frame.grid(row=0, column=1, sticky="nsew")
        self.content_frame.grid_rowconfigure(0, weight=1)
        self.content_frame.grid_columnconfigure(0, weight=1)

        self.panels: Dict[str, tk.Frame] = {}
        self._build_chat_panel()
        self._build_nodes_panel()
        self._build_network_panel()
        self._build_tasks_panel()
        self._build_settings_panel()

        self._show_panel("chat")

    def _build_chat_panel(self):
        panel = tk.Frame(self.content_frame, bg=DarkTheme.BG)
        self.panels["chat"] = panel
        panel.grid_rowconfigure(0, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        chat_frame = tk.Frame(panel, bg=DarkTheme.BG)
        chat_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        chat_frame.grid_rowconfigure(0, weight=1)
        chat_frame.grid_columnconfigure(0, weight=1)

        self.chat_display = scrolledtext.ScrolledText(
            chat_frame,
            wrap=tk.WORD,
            bg=DarkTheme.CARD_BG,
            fg=DarkTheme.FG,
            font=("Consolas", 11),
            padx=15,
            pady=15,
            state="disabled",
            insertbackground=DarkTheme.FG,
            highlightthickness=1,
            highlightbackground=DarkTheme.BORDER,
            highlightcolor=DarkTheme.ACCENT
        )
        self.chat_display.grid(row=0, column=0, sticky="nsew")

        input_frame = tk.Frame(chat_frame, bg=DarkTheme.BG)
        input_frame.grid(row=1, column=0, sticky="ew", pady=(15, 0))
        input_frame.grid_columnconfigure(0, weight=1)

        self.chat_input = tk.Entry(
            input_frame,
            bg=DarkTheme.INPUT_BG,
            fg=DarkTheme.FG,
            insertbackground=DarkTheme.FG,
            font=("Segoe UI", 11),
            relief="flat",
            highlightthickness=1,
            highlightbackground=DarkTheme.BORDER,
            highlightcolor=DarkTheme.ACCENT
        )
        self.chat_input.grid(row=0, column=0, sticky="ew", ipady=8, padx=(0, 10))
        self.chat_input.bind("<Return>", lambda e: self._send_chat())

        send_btn = tk.Button(
            input_frame,
            text="Send",
            command=self._send_chat,
            bg=DarkTheme.ACCENT,
            fg=DarkTheme.BG,
            activebackground=DarkTheme.ACCENT_HOVER,
            activeforeground=DarkTheme.BG,
            bd=0,
            padx=20,
            pady=8,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2"
        )
        send_btn.grid(row=0, column=1)

    def _build_nodes_panel(self):
        panel = tk.Frame(self.content_frame, bg=DarkTheme.BG)
        self.panels["nodes"] = panel
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        header = tk.Label(
            panel,
            text="Connected Sub-Nodes",
            bg=DarkTheme.BG,
            fg=DarkTheme.FG,
            font=("Segoe UI", 18, "bold"),
            anchor="w"
        )
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))

        table_frame = tk.Frame(panel, bg=DarkTheme.CARD_BG, highlightthickness=1, highlightbackground=DarkTheme.BORDER)
        table_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)
        table_frame.grid_rowconfigure(1, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        headers = ["Status", "Name", "Type", "IP Address", "Capabilities"]
        for col, h in enumerate(headers):
            lbl = tk.Label(
                table_frame,
                text=h,
                bg=DarkTheme.CARD_BG,
                fg=DarkTheme.ACCENT,
                font=("Segoe UI", 10, "bold"),
                padx=15,
                pady=10
            )
            lbl.grid(row=0, column=col, sticky="w")

        self.nodes_table = tk.Frame(table_frame, bg=DarkTheme.CARD_BG)
        self.nodes_table.grid(row=1, column=0, columnspan=len(headers), sticky="nsew")
        self.nodes_table.grid_columnconfigure(0, weight=1)

        self.nodes_rows: List[tk.Widget] = []

    def _build_network_panel(self):
        panel = tk.Frame(self.content_frame, bg=DarkTheme.BG)
        self.panels["network"] = panel
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        header = tk.Label(
            panel,
            text="Network Topology",
            bg=DarkTheme.BG,
            fg=DarkTheme.FG,
            font=("Segoe UI", 18, "bold"),
            anchor="w"
        )
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))

        stats_frame = tk.Frame(panel, bg=DarkTheme.BG)
        stats_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))

        self.net_stats = {}
        stats = [
            ("Connected Nodes", "0", DarkTheme.ACCENT),
            ("Total Traffic", "0 MB", DarkTheme.SUCCESS),
            ("Router Status", "Online", DarkTheme.ONLINE),
        ]
        for idx, (label, value, color) in enumerate(stats):
            card = tk.Frame(stats_frame, bg=DarkTheme.CARD_BG, padx=20, pady=15)
            card.grid(row=0, column=idx, padx=(0, 15), sticky="nsew")
            lbl = tk.Label(card, text=label, bg=DarkTheme.CARD_BG, fg=DarkTheme.FG, font=("Segoe UI", 10))
            lbl.pack(anchor="w")
            val = tk.Label(card, text=value, bg=DarkTheme.CARD_BG, fg=color, font=("Segoe UI", 16, "bold"))
            val.pack(anchor="w", pady=(5, 0))
            self.net_stats[label] = val

        canvas_frame = tk.Frame(panel, bg=DarkTheme.CARD_BG, highlightthickness=1, highlightbackground=DarkTheme.BORDER)
        canvas_frame.grid(row=2, column=0, sticky="nsew", padx=20, pady=10)
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)

        self.network_canvas = tk.Canvas(canvas_frame, bg=DarkTheme.CARD_BG, highlightthickness=0)
        self.network_canvas.pack(fill="both", expand=True)

    def _build_tasks_panel(self):
        panel = tk.Frame(self.content_frame, bg=DarkTheme.BG)
        self.panels["tasks"] = panel
        panel.grid_rowconfigure(2, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        header = tk.Label(
            panel,
            text="Task Management",
            bg=DarkTheme.BG,
            fg=DarkTheme.FG,
            font=("Segoe UI", 18, "bold"),
            anchor="w"
        )
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))

        btn_frame = tk.Frame(panel, bg=DarkTheme.BG)
        btn_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))

        submit_btn = tk.Button(
            btn_frame,
            text="+ New Task",
            command=self._show_submit_task_dialog,
            bg=DarkTheme.ACCENT,
            fg=DarkTheme.BG,
            activebackground=DarkTheme.ACCENT_HOVER,
            bd=0,
            padx=20,
            pady=8,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2"
        )
        submit_btn.pack(side="left")

        self.task_filter_var = tk.StringVar(value="all")
        filter_frame = tk.Frame(btn_frame, bg=DarkTheme.BG)
        filter_frame.pack(side="right")

        for f in ["all", "pending", "completed", "failed"]:
            rb = tk.Radiobutton(
                filter_frame,
                text=f.capitalize(),
                variable=self.task_filter_var,
                value=f,
                bg=DarkTheme.BG,
                fg=DarkTheme.FG,
                selectcolor=DarkTheme.CARD_BG,
                activebackground=DarkTheme.BG,
                activeforeground=DarkTheme.ACCENT,
                font=("Segoe UI", 10),
                command=self._refresh_tasks_display
            )
            rb.pack(side="left", padx=5)

        list_frame = tk.Frame(panel, bg=DarkTheme.CARD_BG, highlightthickness=1, highlightbackground=DarkTheme.BORDER)
        list_frame.grid(row=2, column=0, sticky="nsew", padx=20, pady=10)
        list_frame.grid_rowconfigure(1, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        task_headers = ["ID", "Type", "Description", "Status", "Assigned Node"]
        for col, h in enumerate(task_headers):
            lbl = tk.Label(
                list_frame,
                text=h,
                bg=DarkTheme.CARD_BG,
                fg=DarkTheme.ACCENT,
                font=("Segoe UI", 10, "bold"),
                padx=15,
                pady=10
            )
            lbl.grid(row=0, column=col, sticky="w")

        self.tasks_table = tk.Frame(list_frame, bg=DarkTheme.CARD_BG)
        self.tasks_table.grid(row=1, column=0, columnspan=len(task_headers), sticky="nsew")
        self.tasks_table.grid_columnconfigure(0, weight=1)

        self.tasks_rows: List[tk.Widget] = []

    def _build_settings_panel(self):
        panel = tk.Frame(self.content_frame, bg=DarkTheme.BG)
        self.panels["settings"] = panel
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        header = tk.Label(
            panel,
            text="Settings",
            bg=DarkTheme.BG,
            fg=DarkTheme.FG,
            font=("Segoe UI", 18, "bold"),
            anchor="w"
        )
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))

        scroll = ScrollableFrame(panel)
        scroll.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)
        container = scroll.scrollable_frame

        ai_frame = tk.LabelFrame(
            container,
            text="AI Backend Configuration",
            bg=DarkTheme.BG,
            fg=DarkTheme.ACCENT,
            font=("Segoe UI", 12, "bold"),
            bd=1,
            highlightthickness=1,
            highlightbackground=DarkTheme.BORDER
        )
        ai_frame.pack(fill="x", pady=(0, 20), ipady=10)

        tk.Label(ai_frame, text="Backend:", bg=DarkTheme.BG, fg=DarkTheme.FG, font=("Segoe UI", 11)).grid(row=0, column=0, sticky="w", padx=15, pady=10)
        self.backend_var = tk.StringVar(value="ollama")
        backend_combo = ttk.Combobox(
            ai_frame,
            textvariable=self.backend_var,
            values=[b.value for b in ModelBackend],
            state="readonly",
            font=("Segoe UI", 11)
        )
        backend_combo.grid(row=0, column=1, sticky="ew", padx=15, pady=10)
        backend_combo.bind("<<ComboboxSelected>>", lambda e: self._on_backend_change())

        tk.Label(ai_frame, text="Base URL:", bg=DarkTheme.BG, fg=DarkTheme.FG, font=("Segoe UI", 11)).grid(row=1, column=0, sticky="w", padx=15, pady=10)
        self.base_url_var = tk.StringVar(value="http://localhost")
        tk.Entry(ai_frame, textvariable=self.base_url_var, bg=DarkTheme.INPUT_BG, fg=DarkTheme.FG, insertbackground=DarkTheme.FG, font=("Segoe UI", 11), relief="flat", highlightthickness=1, highlightbackground=DarkTheme.BORDER).grid(row=1, column=1, sticky="ew", padx=15, pady=10)

        tk.Label(ai_frame, text="Port:", bg=DarkTheme.BG, fg=DarkTheme.FG, font=("Segoe UI", 11)).grid(row=2, column=0, sticky="w", padx=15, pady=10)
        self.port_var = tk.StringVar(value="11434")
        tk.Entry(ai_frame, textvariable=self.port_var, bg=DarkTheme.INPUT_BG, fg=DarkTheme.FG, insertbackground=DarkTheme.FG, font=("Segoe UI", 11), relief="flat", highlightthickness=1, highlightbackground=DarkTheme.BORDER).grid(row=2, column=1, sticky="ew", padx=15, pady=10)

        tk.Label(ai_frame, text="Model:", bg=DarkTheme.BG, fg=DarkTheme.FG, font=("Segoe UI", 11)).grid(row=3, column=0, sticky="w", padx=15, pady=10)
        self.model_var = tk.StringVar(value="")
        self.model_combo = ttk.Combobox(ai_frame, textvariable=self.model_var, values=[], font=("Segoe UI", 11))
        self.model_combo.grid(row=3, column=1, sticky="ew", padx=15, pady=10)

        ai_btn_frame = tk.Frame(ai_frame, bg=DarkTheme.BG)
        ai_btn_frame.grid(row=4, column=0, columnspan=2, sticky="e", padx=15, pady=10)

        test_btn = tk.Button(
            ai_btn_frame,
            text="Test Connection",
            command=self._test_ai_connection,
            bg=DarkTheme.CARD_BG,
            fg=DarkTheme.FG,
            activebackground=DarkTheme.BORDER,
            bd=0,
            padx=15,
            pady=6,
            font=("Segoe UI", 10),
            cursor="hand2"
        )
        test_btn.pack(side="left", padx=(0, 10))

        save_btn = tk.Button(
            ai_btn_frame,
            text="Save AI Config",
            command=self._save_ai_config,
            bg=DarkTheme.ACCENT,
            fg=DarkTheme.BG,
            activebackground=DarkTheme.ACCENT_HOVER,
            bd=0,
            padx=15,
            pady=6,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2"
        )
        save_btn.pack(side="left")

        net_frame = tk.LabelFrame(
            container,
            text="Network Configuration",
            bg=DarkTheme.BG,
            fg=DarkTheme.ACCENT,
            font=("Segoe UI", 12, "bold"),
            bd=1,
            highlightthickness=1,
            highlightbackground=DarkTheme.BORDER
        )
        net_frame.pack(fill="x", pady=(0, 20), ipady=10)

        tk.Label(net_frame, text="Host:", bg=DarkTheme.BG, fg=DarkTheme.FG, font=("Segoe UI", 11)).grid(row=0, column=0, sticky="w", padx=15, pady=10)
        self.net_host_var = tk.StringVar(value="0.0.0.0")
        tk.Entry(net_frame, textvariable=self.net_host_var, bg=DarkTheme.INPUT_BG, fg=DarkTheme.FG, insertbackground=DarkTheme.FG, font=("Segoe UI", 11), relief="flat", highlightthickness=1, highlightbackground=DarkTheme.BORDER).grid(row=0, column=1, sticky="ew", padx=15, pady=10)

        tk.Label(net_frame, text="Port:", bg=DarkTheme.BG, fg=DarkTheme.FG, font=("Segoe UI", 11)).grid(row=1, column=0, sticky="w", padx=15, pady=10)
        self.net_port_var = tk.StringVar(value="8888")
        tk.Entry(net_frame, textvariable=self.net_port_var, bg=DarkTheme.INPUT_BG, fg=DarkTheme.FG, insertbackground=DarkTheme.FG, font=("Segoe UI", 11), relief="flat", highlightthickness=1, highlightbackground=DarkTheme.BORDER).grid(row=1, column=1, sticky="ew", padx=15, pady=10)

        tk.Label(net_frame, text="Multicast Group:", bg=DarkTheme.BG, fg=DarkTheme.FG, font=("Segoe UI", 11)).grid(row=2, column=0, sticky="w", padx=15, pady=10)
        self.mcast_group_var = tk.StringVar(value="224.0.0.1")
        tk.Entry(net_frame, textvariable=self.mcast_group_var, bg=DarkTheme.INPUT_BG, fg=DarkTheme.FG, insertbackground=DarkTheme.FG, font=("Segoe UI", 11), relief="flat", highlightthickness=1, highlightbackground=DarkTheme.BORDER).grid(row=2, column=1, sticky="ew", padx=15, pady=10)

        tk.Label(net_frame, text="Multicast Port:", bg=DarkTheme.BG, fg=DarkTheme.FG, font=("Segoe UI", 11)).grid(row=3, column=0, sticky="w", padx=15, pady=10)
        self.mcast_port_var = tk.StringVar(value="5000")
        tk.Entry(net_frame, textvariable=self.mcast_port_var, bg=DarkTheme.INPUT_BG, fg=DarkTheme.FG, insertbackground=DarkTheme.FG, font=("Segoe UI", 11), relief="flat", highlightthickness=1, highlightbackground=DarkTheme.BORDER).grid(row=3, column=1, sticky="ew", padx=15, pady=10)

        net_btn_frame = tk.Frame(net_frame, bg=DarkTheme.BG)
        net_btn_frame.grid(row=4, column=0, columnspan=2, sticky="e", padx=15, pady=10)

        net_save_btn = tk.Button(
            net_btn_frame,
            text="Save Network Config",
            command=self._save_network_config,
            bg=DarkTheme.ACCENT,
            fg=DarkTheme.BG,
            activebackground=DarkTheme.ACCENT_HOVER,
            bd=0,
            padx=15,
            pady=6,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2"
        )
        net_save_btn.pack(side="left")

        ai_frame.grid_columnconfigure(1, weight=1)
        net_frame.grid_columnconfigure(1, weight=1)

    def _show_panel(self, name: str):
        for key, panel in self.panels.items():
            panel.grid_remove()
        self.panels[name].grid(row=0, column=0, sticky="nsew")
        for key, btn in self.nav_buttons.items():
            btn.set_active(key == name)
        self.current_panel = name

    def _init_backend(self):
        try:
            backend = ModelBackend(self.backend_var.get())
            port = int(self.port_var.get())
            self.model_adapter = ModelAdapter(backend, self.base_url_var.get(), port)
            self.central_compute = CentralComputeNode(
                ai_backend=backend,
                ai_port=port
            )
            self.central_network = CentralNetworkNode(
                host=self.net_host_var.get(),
                port=int(self.net_port_var.get()),
                multicast_group=self.mcast_group_var.get(),
                multicast_port=int(self.mcast_port_var.get())
            )
            self.status_label.configure(text="Status: Ready", fg=DarkTheme.SUCCESS)
        except Exception as e:
            self.status_label.configure(text=f"Status: Error - {e}", fg=DarkTheme.ERROR)

    def _start_refresh_loop(self):
        self._refresh_nodes()
        self._refresh_network()
        self._refresh_tasks_display()
        self.root.after(5000, self._start_refresh_loop)

    def _send_chat(self):
        text = self.chat_input.get().strip()
        if not text:
            return
        self.chat_input.delete(0, tk.END)
        self._append_chat("You", text, DarkTheme.ACCENT)
        threading.Thread(target=self._chat_worker, args=(text,), daemon=True).start()

    def _chat_worker(self, text: str):
        try:
            if self.model_adapter:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(self.model_adapter.generate(text))
                loop.close()
                response = result.get("response", "No response")
            else:
                response = "AI backend not configured."
        except Exception as e:
            response = f"Error: {e}"
        self.root.after(0, lambda: self._append_chat("AI", response, DarkTheme.SUCCESS))

    def _append_chat(self, sender: str, text: str, color: str):
        self.chat_display.configure(state="normal")
        self.chat_display.insert(tk.END, f"{sender}: ", ("sender",))
        self.chat_display.insert(tk.END, f"{text}\n\n")
        self.chat_display.tag_config("sender", foreground=color, font=("Consolas", 11, "bold"))
        self.chat_display.configure(state="disabled")
        self.chat_display.see(tk.END)

    def _refresh_nodes(self):
        for widget in self.nodes_rows:
            widget.destroy()
        self.nodes_rows.clear()

        nodes = []
        if self.central_network:
            nodes = list(self.central_network.connected_nodes.values())
        elif self.central_compute:
            nodes = [
                type("Node", (), {
                    "node_id": nid,
                    "node_name": info.get("node_name", "unknown"),
                    "node_type": type("T", (), {"value": info.get("node_type", "compute_node")})(),
                    "ip_address": info.get("ip_address", "-"),
                    "status": type("S", (), {"value": info.get("status", "offline")})(),
                    "capabilities": info.get("capabilities", []),
                })()
                for nid, info in self.central_compute.available_nodes.items()
            ]

        if not nodes:
            lbl = tk.Label(
                self.nodes_table,
                text="No connected nodes",
                bg=DarkTheme.CARD_BG,
                fg=DarkTheme.FG,
                font=("Segoe UI", 11),
                padx=15,
                pady=20
            )
            lbl.grid(row=0, column=0, sticky="w")
            self.nodes_rows.append(lbl)
            return

        for idx, node in enumerate(nodes):
            status_color = DarkTheme.ONLINE if getattr(node, "status", None) and node.status.value == "online" else DarkTheme.OFFLINE
            if getattr(node, "status", None) and node.status.value == "busy":
                status_color = DarkTheme.BUSY
            elif getattr(node, "status", None) and node.status.value == "idle":
                status_color = DarkTheme.IDLE

            row_frame = tk.Frame(self.nodes_table, bg=DarkTheme.CARD_BG)
            row_frame.grid(row=idx, column=0, sticky="ew", pady=1)
            row_frame.grid_columnconfigure(0, weight=1)

            status_dot = tk.Canvas(row_frame, width=12, height=12, bg=DarkTheme.CARD_BG, highlightthickness=0)
            status_dot.create_oval(2, 2, 10, 10, fill=status_color, outline="")
            status_dot.grid(row=0, column=0, padx=(15, 5), pady=8)

            vals = [
                getattr(node, "node_name", "-"),
                getattr(node, "node_type", type("T", (), {"value": "-"})()).value if hasattr(getattr(node, "node_type", None), "value") else str(getattr(node, "node_type", "-")),
                getattr(node, "ip_address", "-"),
                ", ".join(getattr(node, "capabilities", [])[:3]) or "-"
            ]
            for col, val in enumerate(vals, start=1):
                lbl = tk.Label(
                    row_frame,
                    text=val,
                    bg=DarkTheme.CARD_BG,
                    fg=DarkTheme.FG,
                    font=("Segoe UI", 10),
                    padx=15,
                    pady=8
                )
                lbl.grid(row=0, column=col, sticky="w")

            self.nodes_rows.append(row_frame)

    def _refresh_network(self):
        node_count = 0
        if self.central_network:
            node_count = len(self.central_network.connected_nodes)
        elif self.central_compute:
            node_count = len(self.central_compute.available_nodes)

        self.net_stats["Connected Nodes"].configure(text=str(node_count))

        self.network_canvas.delete("all")
        w = self.network_canvas.winfo_width() or 800
        h = self.network_canvas.winfo_height() or 400

        cx, cy = w // 2, h // 2
        self.network_canvas.create_oval(cx - 30, cy - 30, cx + 30, cy + 30, fill=DarkTheme.ACCENT, outline="")
        self.network_canvas.create_text(cx, cy, text="C", fill=DarkTheme.BG, font=("Segoe UI", 14, "bold"))

        nodes = []
        if self.central_network:
            nodes = list(self.central_network.connected_nodes.values())
        elif self.central_compute:
            nodes = list(self.central_compute.available_nodes.keys())

        n = max(len(nodes), 1)
        radius = min(w, h) // 2 - 80
        for i, node in enumerate(nodes):
            angle = 2 * 3.14159 * i / n - 3.14159 / 2
            nx = cx + radius * 0.8 * (n > 1) * (1 if n == 1 else __import__("math").cos(angle))
            ny = cy + radius * 0.8 * (n > 1) * (1 if n == 1 else __import__("math").sin(angle))
            if n == 1:
                nx, ny = cx + radius * 0.8, cy

            self.network_canvas.create_line(cx, cy, nx, ny, fill=DarkTheme.BORDER, width=2)

            status_color = DarkTheme.ONLINE
            if hasattr(node, "status"):
                sv = node.status.value if hasattr(node.status, "value") else str(node.status)
                if sv == "offline":
                    status_color = DarkTheme.OFFLINE
                elif sv == "busy":
                    status_color = DarkTheme.BUSY
                elif sv == "idle":
                    status_color = DarkTheme.IDLE

            self.network_canvas.create_oval(nx - 20, ny - 20, nx + 20, ny + 20, fill=status_color, outline=DarkTheme.BORDER, width=2)
            name = getattr(node, "node_name", str(node))[:8]
            self.network_canvas.create_text(nx, ny, text=name, fill=DarkTheme.BG, font=("Segoe UI", 9, "bold"))

        if not nodes:
            self.network_canvas.create_text(cx, cy + 60, text="No nodes connected", fill=DarkTheme.FG, font=("Segoe UI", 12))

    def _refresh_tasks_display(self):
        for widget in self.tasks_rows:
            widget.destroy()
        self.tasks_rows.clear()

        tasks = []
        if self.central_compute:
            tasks = list(self.central_compute.tasks.values())

        filt = self.task_filter_var.get()
        if filt != "all":
            tasks = [t for t in tasks if t.status.value == filt]

        if not tasks:
            lbl = tk.Label(
                self.tasks_table,
                text="No tasks",
                bg=DarkTheme.CARD_BG,
                fg=DarkTheme.FG,
                font=("Segoe UI", 11),
                padx=15,
                pady=20
            )
            lbl.grid(row=0, column=0, sticky="w")
            self.tasks_rows.append(lbl)
            return

        for idx, task in enumerate(tasks):
            status_color = DarkTheme.FG
            if task.status == TaskStatus.COMPLETED:
                status_color = DarkTheme.SUCCESS
            elif task.status == TaskStatus.FAILED:
                status_color = DarkTheme.ERROR
            elif task.status == TaskStatus.PENDING:
                status_color = DarkTheme.WARNING
            elif task.status == TaskStatus.IN_PROGRESS:
                status_color = DarkTheme.ACCENT

            row_frame = tk.Frame(self.tasks_table, bg=DarkTheme.CARD_BG)
            row_frame.grid(row=idx, column=0, sticky="ew", pady=1)
            row_frame.grid_columnconfigure(0, weight=1)

            vals = [
                task.task_id[:8] + "...",
                task.task_type.value,
                task.description[:30] + ("..." if len(task.description) > 30 else ""),
                task.status.value,
                task.assigned_node[:8] + "..." if task.assigned_node else "-"
            ]
            for col, val in enumerate(vals):
                lbl = tk.Label(
                    row_frame,
                    text=val,
                    bg=DarkTheme.CARD_BG,
                    fg=status_color if col == 3 else DarkTheme.FG,
                    font=("Segoe UI", 10),
                    padx=15,
                    pady=8
                )
                lbl.grid(row=0, column=col, sticky="w")

            self.tasks_rows.append(row_frame)

    def _show_submit_task_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Submit New Task")
        dialog.configure(bg=DarkTheme.BG)
        dialog.geometry("500x350")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Task Type:", bg=DarkTheme.BG, fg=DarkTheme.FG, font=("Segoe UI", 11)).pack(anchor="w", padx=20, pady=(20, 5))
        task_type_var = tk.StringVar(value=TaskType.INFERENCE.value)
        ttk.Combobox(dialog, textvariable=task_type_var, values=[t.value for t in TaskType], state="readonly", font=("Segoe UI", 11)).pack(fill="x", padx=20, pady=5)

        tk.Label(dialog, text="Description:", bg=DarkTheme.BG, fg=DarkTheme.FG, font=("Segoe UI", 11)).pack(anchor="w", padx=20, pady=(10, 5))
        desc_entry = tk.Entry(dialog, bg=DarkTheme.INPUT_BG, fg=DarkTheme.FG, insertbackground=DarkTheme.FG, font=("Segoe UI", 11), relief="flat", highlightthickness=1, highlightbackground=DarkTheme.BORDER)
        desc_entry.pack(fill="x", padx=20, pady=5)

        tk.Label(dialog, text="Payload (JSON, optional):", bg=DarkTheme.BG, fg=DarkTheme.FG, font=("Segoe UI", 11)).pack(anchor="w", padx=20, pady=(10, 5))
        payload_text = tk.Text(dialog, height=5, bg=DarkTheme.INPUT_BG, fg=DarkTheme.FG, insertbackground=DarkTheme.FG, font=("Consolas", 10), relief="flat", highlightthickness=1, highlightbackground=DarkTheme.BORDER)
        payload_text.pack(fill="x", padx=20, pady=5)
        payload_text.insert("1.0", "{}")

        def submit():
            desc = desc_entry.get().strip()
            if not desc:
                messagebox.showwarning("Warning", "Description is required", parent=dialog)
                return
            try:
                payload = eval(payload_text.get("1.0", tk.END).strip())
            except Exception:
                payload = {}

            tt = TaskType(task_type_var.get())
            if self.central_compute:
                threading.Thread(target=self._submit_task_worker, args=(tt, desc, payload), daemon=True).start()
            else:
                messagebox.showerror("Error", "Central compute node not initialized", parent=dialog)
            dialog.destroy()
            self.root.after(500, self._refresh_tasks_display)

        btn_frame = tk.Frame(dialog, bg=DarkTheme.BG)
        btn_frame.pack(fill="x", padx=20, pady=20)

        tk.Button(btn_frame, text="Cancel", command=dialog.destroy, bg=DarkTheme.CARD_BG, fg=DarkTheme.FG, bd=0, padx=15, pady=6, font=("Segoe UI", 10), cursor="hand2").pack(side="right", padx=(10, 0))
        tk.Button(btn_frame, text="Submit", command=submit, bg=DarkTheme.ACCENT, fg=DarkTheme.BG, activebackground=DarkTheme.ACCENT_HOVER, bd=0, padx=15, pady=6, font=("Segoe UI", 10, "bold"), cursor="hand2").pack(side="right")

    def _submit_task_worker(self, task_type: TaskType, description: str, payload: dict):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.central_compute.submit_task(task_type, description, payload))
            loop.close()
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to submit task: {e}"))

    def _on_backend_change(self):
        backend_val = self.backend_var.get()
        default_ports = {"ollama": "11434", "vllm": "8000", "lm_studio": "1234", "openai": "8080"}
        if backend_val in default_ports:
            self.port_var.set(default_ports[backend_val])

    def _test_ai_connection(self):
        def worker():
            try:
                backend = ModelBackend(self.backend_var.get())
                adapter = ModelAdapter(backend, self.base_url_var.get(), int(self.port_var.get()))
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                ok = loop.run_until_complete(adapter.health_check())
                models = loop.run_until_complete(adapter.list_models()) if ok else []
                loop.close()
                if ok:
                    self.root.after(0, lambda: self.model_combo.configure(values=models))
                    self.root.after(0, lambda: messagebox.showinfo("Success", f"Connected! Models: {len(models)}"))
                else:
                    self.root.after(0, lambda: messagebox.showerror("Error", "Connection failed"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=worker, daemon=True).start()

    def _save_ai_config(self):
        try:
            backend = ModelBackend(self.backend_var.get())
            port = int(self.port_var.get())
            self.model_adapter = ModelAdapter(backend, self.base_url_var.get(), port)
            if self.central_compute:
                self.central_compute.ai_adapter = self.model_adapter
            messagebox.showinfo("Success", "AI configuration saved")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _save_network_config(self):
        try:
            self.central_network = CentralNetworkNode(
                host=self.net_host_var.get(),
                port=int(self.net_port_var.get()),
                multicast_group=self.mcast_group_var.get(),
                multicast_port=int(self.mcast_port_var.get())
            )
            messagebox.showinfo("Success", "Network configuration saved")
        except Exception as e:
            messagebox.showerror("Error", str(e))


def main():
    root = tk.Tk()
    app = CenterDashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
