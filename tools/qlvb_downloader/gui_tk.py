import sys
import os
import subprocess
import threading
import queue
import json
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import customtkinter as ctk

from tools.qlvb_downloader.config import QLVBConfig, load_config, save_config, VERSION
from tools.qlvb_downloader.paths import project_root
from tools.qlvb_downloader.storage import StorageManager
from tools.qlvb_downloader.assignment_draft_service import AssignmentDraftService, AssignmentDraftServiceError
from tools.qlvb_downloader.assignment_draft_ui import AssignmentDraftDetailDialog
from tools.qlvb_downloader.assignment_draft_planner_handoff import planner_display_status

# Set UI Theme
ctk.set_appearance_mode("System")  # Modes: "System", "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue", "green", "dark-blue"

class ConfigApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window Settings
        self.title(f"Smart Office AI 360 - Desktop Agent V{VERSION.split('_')[0]}")
        self.geometry("1100x720")
        self.minsize(1000, 650)
        self.root_dir = project_root()

        # Load Configuration
        try:
            self.cfg = load_config()
        except Exception:
            self.cfg = QLVBConfig()

        # Storage Manager
        self.storage = StorageManager(
            self.cfg.root_path,
            copy_files_to_queue=self.cfg.download.copy_files_to_queue,
            create_ready_marker=self.cfg.download.create_ready_marker,
        )

        # Threading / Subprocess states
        self.running_proc = None
        self.is_running = False
        self.stdout_queue = queue.Queue()

        # Build UI layout
        self._build_sidebar()
        self._build_frames()
        self._build_assignment_drafts_frame()
        self.select_frame_by_name("overview")

        # Auto check system at startup
        self.after(500, self.quick_system_check)

    def _build_sidebar(self):
        # Sidebar container
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, rowspan=4, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(9, weight=1)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Logo and Title
        self.logo_label = ctk.CTkLabel(
            self.sidebar_frame, 
            text="SmartOfficeAI 360", 
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 5))
        
        self.sub_logo_label = ctk.CTkLabel(
            self.sidebar_frame, 
            text="V22.2.3-QC Maintenance 1",
            font=ctk.CTkFont(size=11, slant="italic")
        )
        self.sub_logo_label.grid(row=1, column=0, padx=20, pady=(0, 20))

        # Navigation Buttons
        self.nav_buttons = {}
        nav_items = [
            ("overview", "Tổng quan", "home"),
            ("login_gate", "Đăng nhập QLVB", "lock"),
            ("config", "Cấu hình", "settings"),
            ("download", "Tải văn bản", "download"),
            ("queue", "Hàng đợi", "list"),
            ("sync", "Đồng bộ KPI", "cloud-upload"),
            ("logs", "Nhật ký", "file-text"),
            ("help", "Trợ giúp & Bảo mật", "help-circle"),
            ("assignment_drafts", "Dự thảo giao việc", "clipboard"),
        ]

        for idx, (name, label, icon) in enumerate(nav_items, start=2):
            btn = ctk.CTkButton(
                self.sidebar_frame,
                text=label,
                corner_radius=6,
                height=38,
                border_spacing=10,
                anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray70", "gray30"),
                command=lambda n=name: self.select_frame_by_name(n)
            )
            btn.grid(row=idx, column=0, padx=12, pady=3, sticky="ew")
            self.nav_buttons[name] = btn

        # Theme Switcher
        self.theme_label = ctk.CTkLabel(self.sidebar_frame, text="Giao diện:", anchor="w")
        self.theme_label.grid(row=10, column=0, padx=20, pady=(10, 0), sticky="w")
        self.theme_optionmenu = ctk.CTkOptionMenu(
            self.sidebar_frame,
            values=["System", "Light", "Dark"],
            command=self.change_appearance_mode_event
        )
        self.theme_optionmenu.grid(row=11, column=0, padx=20, pady=(0, 20), sticky="ew")

    def _build_frames(self):
        # Create all Tab frames
        self.frames = {
            "overview": ctk.CTkFrame(self, corner_radius=0, fg_color="transparent"),
            "login_gate": ctk.CTkFrame(self, corner_radius=0, fg_color="transparent"),
            "config": ctk.CTkFrame(self, corner_radius=0, fg_color="transparent"),
            "download": ctk.CTkFrame(self, corner_radius=0, fg_color="transparent"),
            "queue": ctk.CTkFrame(self, corner_radius=0, fg_color="transparent"),
            "sync": ctk.CTkFrame(self, corner_radius=0, fg_color="transparent"),
            "logs": ctk.CTkFrame(self, corner_radius=0, fg_color="transparent"),
            "help": ctk.CTkFrame(self, corner_radius=0, fg_color="transparent"),
        }

        # ------------------ 1. OVERVIEW FRAME ------------------
        f = self.frames["overview"]
        f.grid_columnconfigure((0, 1, 2), weight=1)
        f.grid_rowconfigure(3, weight=1)

        title = ctk.CTkLabel(f, text="TỔNG QUAN HỆ THỐNG", font=ctk.CTkFont(size=20, weight="bold"))
        title.grid(row=0, column=0, columnspan=3, padx=20, pady=(20, 10), sticky="w")

        # Stats Cards
        self.card_qlvb = self._create_stat_card(f, "Trạng thái QLVB", "Chưa kiểm tra", "gray", 0, 1)
        self.card_session = self._create_stat_card(f, "Phiên làm việc", "Chưa kiểm tra", "gray", 1, 1)
        self.card_today = self._create_stat_card(f, "Văn bản đã tải hôm nay", "0", "#0f4c81", 2, 1)
        
        self.card_pending = self._create_stat_card(f, "Đang chờ đồng bộ KPI", "0", "#2d8a4e", 0, 2)
        self.card_failed = self._create_stat_card(f, "Hồ sơ đồng bộ lỗi", "0", "#b22222", 1, 2)

        # Quick Actions Panel
        action_frame = ctk.CTkFrame(f)
        action_frame.grid(row=3, column=0, columnspan=3, padx=20, pady=20, sticky="nsew")
        action_frame.grid_columnconfigure((0, 1, 2), weight=1)
        
        lbl = ctk.CTkLabel(action_frame, text="Thao tác nhanh", font=ctk.CTkFont(size=16, weight="bold"))
        lbl.grid(row=0, column=0, columnspan=3, padx=20, pady=15, sticky="w")

        btn_check = ctk.CTkButton(action_frame, text="Kiểm tra hệ thống (Doctor)", height=45, command=self.quick_system_check)
        btn_check.grid(row=1, column=0, padx=15, pady=15, sticky="ew")

        btn_login = ctk.CTkButton(action_frame, text="Đăng nhập QLVB", height=45, fg_color="#2b5c8f", command=lambda: self.select_frame_by_name("login_gate"))
        btn_login.grid(row=1, column=1, padx=15, pady=15, sticky="ew")

        btn_dl = ctk.CTkButton(action_frame, text="Tải văn bản mới nhất", height=45, fg_color="#2d8a4e", command=lambda: self.select_frame_by_name("download"))
        btn_dl.grid(row=1, column=2, padx=15, pady=15, sticky="ew")

        # ------------------ 2. LOGIN GATE FRAME ------------------
        f = self.frames["login_gate"]
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(3, weight=1)

        title = ctk.CTkLabel(f, text="ĐĂNG NHẬP QLVB GIAO DIỆN", font=ctk.CTkFont(size=20, weight="bold"))
        title.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        # Instruction Card
        inst_card = ctk.CTkFrame(f)
        inst_card.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        inst_card.grid_columnconfigure(0, weight=1)

        inst_title = ctk.CTkLabel(inst_card, text="Hướng dẫn Đăng nhập / Giải CAPTCHA", font=ctk.CTkFont(size=14, weight="bold"), text_color="#0f4c81")
        inst_title.grid(row=0, column=0, padx=15, pady=(15, 5), sticky="w")

        inst_body = ctk.CTkLabel(
            inst_card, 
            text="1. Nhấp nút 'Mở trình duyệt đăng nhập' bên dưới.\n"
                 "2. Cửa sổ trình duyệt QLVB sẽ mở ra (chế độ hiện trình duyệt).\n"
                 "3. Bạn hãy nhập tài khoản, mật khẩu và giải CAPTCHA/OTP (nếu có).\n"
                 "4. Khi vào màn hình chính của QLVB thành công, hệ thống sẽ tự lưu phiên (session) và đóng trình duyệt.\n"
                 "5. Những lần chạy sau có thể chạy ẩn (headless) mà không cần đăng nhập lại cho đến khi phiên hết hạn.",
            justify="left",
            anchor="w"
        )
        inst_body.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="w")

        # Action Panel
        login_act_frame = ctk.CTkFrame(f)
        login_act_frame.grid(row=2, column=0, padx=20, pady=10, sticky="ew")
        login_act_frame.grid_columnconfigure(1, weight=1)

        self.lbl_login_status = ctk.CTkLabel(login_act_frame, text="Trạng thái phiên: Chưa kiểm tra", font=ctk.CTkFont(size=14, weight="bold"))
        self.lbl_login_status.grid(row=0, column=0, padx=20, pady=20, sticky="w")

        self.btn_open_browser = ctk.CTkButton(login_act_frame, text="Mở trình duyệt đăng nhập", height=40, fg_color="#2d8a4e", command=self.run_login_only)
        self.btn_open_browser.grid(row=0, column=1, padx=20, pady=20, sticky="e")

        # Console area
        self.login_console = ctk.CTkTextbox(f, height=180)
        self.login_console.grid(row=3, column=0, padx=20, pady=15, sticky="nsew")

        # ------------------ 3. CONFIGURATION FRAME ------------------
        f = self.frames["config"]
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(1, weight=1)

        title = ctk.CTkLabel(f, text="CẤU HÌNH THÔNG SỐ AGENT", font=ctk.CTkFont(size=20, weight="bold"))
        title.grid(row=0, column=0, padx=20, pady=(20, 5), sticky="w")

        # Scrollable container for configuration forms
        scroll_frm = ctk.CTkScrollableFrame(f)
        scroll_frm.grid(row=1, column=0, padx=20, pady=(5, 10), sticky="nsew")
        scroll_frm.grid_columnconfigure(1, weight=1)

        # Section: QLVB Settings
        qlvb_section = ctk.CTkLabel(scroll_frm, text="1. Cấu hình kết nối QLVB", font=ctk.CTkFont(size=14, weight="bold"), text_color="#0f4c81")
        qlvb_section.grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="w")

        self.entry_base = self._create_config_field(scroll_frm, "Địa chỉ Base URL", 1)
        self.entry_login = self._create_config_field(scroll_frm, "Địa chỉ Đăng nhập", 2)
        self.entry_user = self._create_config_field(scroll_frm, "Tên tài khoản", 3)
        self.entry_pass = self._create_config_field(scroll_frm, "Mật khẩu QLVB", 4, show="*")
        
        # Save password locally checkbox
        self.remember_pass_var = ctk.BooleanVar(value=self.cfg.remember_password)
        self.chk_remember = ctk.CTkCheckBox(scroll_frm, text="Lưu mật khẩu cục bộ (không lưu khi phân phối code)", variable=self.remember_pass_var)
        self.chk_remember.grid(row=5, column=1, padx=10, pady=5, sticky="w")

        self.use_fixed_urls_var = ctk.BooleanVar(value=self.cfg.use_fixed_urls)
        self.chk_fixed_urls = ctk.CTkCheckBox(scroll_frm, text="Bật chế độ Link Cố Định (Bỏ qua click menu)", variable=self.use_fixed_urls_var)
        self.chk_fixed_urls.grid(row=6, column=1, padx=10, pady=5, sticky="w")

        self.entry_in_pending = self._create_config_field_with_btn(scroll_frm, "Link Văn bản đến (chờ xử lý)", 7, "incoming_pending")
        self.entry_in_processed = self._create_config_field_with_btn(scroll_frm, "Link Văn bản đến (đã xử lý)", 8, "incoming_processed")
        self.entry_out_issued = self._create_config_field_with_btn(scroll_frm, "Link Văn bản đi (đã ban hành)", 9, "outgoing_issued")
        self.entry_save = self._create_config_field(scroll_frm, "Nơi lưu dữ liệu (Data Root)", 10)

        # Section: Download Settings
        dl_section = ctk.CTkLabel(scroll_frm, text="2. Cấu hình Tải file & Browser", font=ctk.CTkFont(size=14, weight="bold"), text_color="#0f4c81")
        dl_section.grid(row=11, column=0, columnspan=2, padx=10, pady=(15, 5), sticky="w")

        self.headless_var = ctk.BooleanVar(value=self.cfg.browser.headless)
        self.chk_headless = ctk.CTkCheckBox(scroll_frm, text="Chạy ẩn trình duyệt (Headless mode)", variable=self.headless_var)
        self.chk_headless.grid(row=12, column=1, padx=10, pady=5, sticky="w")

        self.entry_max_items = self._create_config_field(scroll_frm, "Số văn bản tải tối đa/lần", 13)
        self.entry_max_pages = self._create_config_field(scroll_frm, "Số trang danh sách tối đa", 14)
        self.entry_manual_wait = self._create_config_field(scroll_frm, "Thời gian chờ đăng nhập (giây)", 15)

        # Section: Planner KPI Settings
        planner_section = ctk.CTkLabel(scroll_frm, text="3. Tích hợp Planner KPI Backend", font=ctk.CTkFont(size=14, weight="bold"), text_color="#0f4c81")
        planner_section.grid(row=16, column=0, columnspan=2, padx=10, pady=(15, 5), sticky="w")

        self.entry_planner_url = self._create_config_field(scroll_frm, "Địa chỉ API Planner URL", 17)
        self.entry_planner_token = self._create_config_field(scroll_frm, "Token Xác thực (Ingest Token)", 18, show="*")

        self.show_secrets_var = ctk.BooleanVar(value=False)
        self.chk_show_secrets = ctk.CTkCheckBox(
            scroll_frm, 
            text="Hiển thị mật khẩu và Token", 
            variable=self.show_secrets_var,
            command=self.toggle_secrets_visibility
        )
        self.chk_show_secrets.grid(row=19, column=1, padx=10, pady=6, sticky="w")

        # Load current values into form fields
        self.entry_base.insert(0, self.cfg.qlvb_base_url)
        self.entry_login.insert(0, self.cfg.login_url)
        self.entry_user.insert(0, self.cfg.username)
        self.entry_pass.insert(0, self.cfg.password)
        self.entry_in_pending.insert(0, self.cfg.incoming_pending_url)
        self.entry_in_processed.insert(0, self.cfg.incoming_processed_url)
        self.entry_out_issued.insert(0, self.cfg.outgoing_issued_url)
        self.entry_save.insert(0, self.cfg.save_root)
        self.entry_max_items.insert(0, str(self.cfg.download.max_items_per_run))
        self.entry_max_pages.insert(0, str(self.cfg.download.max_pages_per_direction))
        self.entry_manual_wait.insert(0, str(self.cfg.browser.manual_login_wait_seconds))
        self.entry_planner_url.insert(0, self.cfg.planner_api_url)
        self.entry_planner_token.insert(0, self.cfg.planner_ingest_token)

        # Button Panel
        btn_panel = ctk.CTkFrame(f)
        btn_panel.grid(row=2, column=0, padx=20, pady=10, sticky="ew")
        btn_panel.grid_columnconfigure((0, 1), weight=1)

        btn_test_conn = ctk.CTkButton(btn_panel, text="Kiểm tra cấu hình", fg_color="#2b5c8f", height=38, command=self.test_configuration)
        btn_test_conn.grid(row=0, column=0, padx=15, pady=10, sticky="ew")

        btn_save_cfg = ctk.CTkButton(btn_panel, text="Lưu cấu hình", fg_color="#2d8a4e", height=38, command=self.save_configuration)
        btn_save_cfg.grid(row=0, column=1, padx=15, pady=10, sticky="ew")

        # ------------------ 4. DOWNLOAD FRAME ------------------
        f = self.frames["download"]
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        title = ctk.CTkLabel(f, text="TẢI VĂN BẢN QUẢN LÝ VĂN BẢN (QLVB)", font=ctk.CTkFont(size=20, weight="bold"))
        title.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        # Parameter Form
        param_frame = ctk.CTkFrame(f)
        param_frame.grid(row=1, column=0, padx=20, pady=5, sticky="ew")
        param_frame.grid_columnconfigure((1, 3, 5), weight=1)

        # Select direction
        ctk.CTkLabel(param_frame, text="Luồng tải:").grid(row=0, column=0, padx=10, pady=12, sticky="w")
        self.combo_dir = ctk.CTkComboBox(param_frame, values=["incoming", "outgoing", "both"])
        self.combo_dir.grid(row=0, column=1, padx=10, pady=12, sticky="ew")
        self.combo_dir.set("both")

        # Select max items
        ctk.CTkLabel(param_frame, text="Tải tối đa:").grid(row=0, column=2, padx=10, pady=12, sticky="w")
        self.entry_run_max = ctk.CTkEntry(param_frame, placeholder_text="Mặc định")
        self.entry_run_max.grid(row=0, column=3, padx=10, pady=12, sticky="ew")

        # Dry run checkbox
        self.dry_run_var = ctk.BooleanVar(value=False)
        self.chk_dry = ctk.CTkCheckBox(param_frame, text="Chỉ quét (Dry-run)", variable=self.dry_run_var)
        self.chk_dry.grid(row=0, column=4, padx=15, pady=12, sticky="w")

        # Execution Controls
        self.start_btn = ctk.CTkButton(param_frame, text="Bắt đầu tải", fg_color="#2d8a4e", text_color="white", height=32, command=self.start_download)
        self.start_btn.grid(row=0, column=5, padx=10, pady=12, sticky="ew")

        self.stop_btn = ctk.CTkButton(param_frame, text="Dừng an toàn", fg_color="#b22222", text_color="white", height=32, state="disabled", command=self.stop_command)
        self.stop_btn.grid(row=0, column=6, padx=10, pady=12, sticky="ew")

        # Log & Progress Console
        console_frame = ctk.CTkFrame(f)
        console_frame.grid(row=2, column=0, padx=20, pady=10, sticky="nsew")
        console_frame.grid_columnconfigure(0, weight=1)
        console_frame.grid_rowconfigure(1, weight=1)

        self.progress_bar = ctk.CTkProgressBar(console_frame)
        self.progress_bar.grid(row=0, column=0, padx=15, pady=(15, 5), sticky="ew")
        self.progress_bar.set(0)

        self.log_textbox = ctk.CTkTextbox(console_frame, font=("Consolas", 12))
        self.log_textbox.grid(row=1, column=0, padx=15, pady=(5, 15), sticky="nsew")

        # ------------------ 5. QUEUE FRAME (PLACEHOLDER FOR STAGE 2) ------------------
        f = self.frames["queue"]
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        title = ctk.CTkLabel(f, text="HÀNG ĐỢI VĂN BẢN CHỜ AI/PLANNER KPI", font=ctk.CTkFont(size=20, weight="bold"))
        title.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        # Table & filters placeholder
        table_filter = ctk.CTkFrame(f)
        table_filter.grid(row=1, column=0, padx=20, pady=5, sticky="ew")
        table_filter.grid_columnconfigure((1, 3), weight=1)

        # Filters
        ctk.CTkLabel(table_filter, text="Loại:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.q_filter_dir = ctk.CTkComboBox(table_filter, values=["Tất cả", "incoming", "outgoing"], command=lambda e: self.refresh_queue_table())
        self.q_filter_dir.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
        self.q_filter_dir.set("Tất cả")

        ctk.CTkLabel(table_filter, text="Trạng thái Sync:").grid(row=0, column=2, padx=10, pady=10, sticky="w")
        self.q_filter_status = ctk.CTkComboBox(table_filter, values=["Tất cả", "PENDING", "SYNCING", "SYNCED", "FAILED", "SKIPPED"], command=lambda e: self.refresh_queue_table())
        self.q_filter_status.grid(row=0, column=3, padx=10, pady=10, sticky="ew")
        self.q_filter_status.set("Tất cả")

        btn_q_refresh = ctk.CTkButton(table_filter, text="Làm mới", width=100, command=self.refresh_queue_table)
        btn_q_refresh.grid(row=0, column=4, padx=10, pady=10)

        # Table container
        table_frame = ctk.CTkFrame(f)
        table_frame.grid(row=2, column=0, padx=20, pady=10, sticky="nsew")
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        # Embed a themed Tkinter Treeview for the data grid
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", rowheight=25, font=("Arial", 10))
        style.map("Treeview", background=[("selected", "#0f4c81")])

        self.tree = ttk.Treeview(
            table_frame, 
            columns=("no", "date", "agency", "title", "data_quality", "sync_status", "time"), 
            show="headings"
        )
        self.tree.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        # Headers
        self.tree.heading("no", text="Số ký hiệu")
        self.tree.heading("date", text="Ngày ban hành")
        self.tree.heading("agency", text="Cơ quan gửi")
        self.tree.heading("title", text="Trích yếu")
        self.tree.heading("data_quality", text="Đánh giá dữ liệu")
        self.tree.heading("sync_status", text="Trạng thái Sync")
        self.tree.heading("time", text="Thời gian tải")

        self.tree.column("no", width=110, anchor="w")
        self.tree.column("date", width=90, anchor="center")
        self.tree.column("agency", width=120, anchor="w")
        self.tree.column("title", width=280, anchor="w")
        self.tree.column("data_quality", width=110, anchor="center")
        self.tree.column("sync_status", width=90, anchor="center")
        self.tree.column("time", width=130, anchor="center")

        # Scrollbar
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky="ns", pady=10)

        # Table Actions Panel
        q_act_panel = ctk.CTkFrame(f)
        q_act_panel.grid(row=3, column=0, padx=20, pady=10, sticky="ew")
        
        btn_open_dir = ctk.CTkButton(q_act_panel, text="Mở thư mục Queue", fg_color="#2b5c8f", command=self.open_selected_queue_folder)
        btn_open_dir.pack(side="left", padx=10, pady=10)

        btn_view_manifest = ctk.CTkButton(q_act_panel, text="Xem manifest.json", fg_color="#0f4c81", command=self.view_selected_manifest)
        btn_view_manifest.pack(side="left", padx=10, pady=10)

        btn_sync_now = ctk.CTkButton(q_act_panel, text="Thử đồng bộ KPI", fg_color="#2d8a4e", command=self.sync_selected_queue_item)
        btn_sync_now.pack(side="left", padx=10, pady=10)

        btn_audit = ctk.CTkButton(q_act_panel, text="Kiểm tra dữ liệu (Audit)", fg_color="#ea7a1e", command=self.run_audit_tool)
        btn_audit.pack(side="left", padx=10, pady=10)

        btn_quarantine = ctk.CTkButton(q_act_panel, text="Cách ly dữ liệu lỗi", fg_color="#d9383a", command=self.run_quarantine)
        btn_quarantine.pack(side="left", padx=10, pady=10)

        # ------------------ 6. SYNC FRAME (PLACEHOLDER FOR STAGE 3) ------------------
        f = self.frames["sync"]
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        title = ctk.CTkLabel(f, text="ĐỒNG BỘ VĂN BẢN SANG PLANNER KPI", font=ctk.CTkFont(size=20, weight="bold"))
        title.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        # Dashboard status panel
        sync_stat_frame = ctk.CTkFrame(f)
        sync_stat_frame.grid(row=1, column=0, padx=20, pady=5, sticky="ew")
        sync_stat_frame.grid_columnconfigure(1, weight=1)

        self.lbl_sync_conn = ctk.CTkLabel(sync_stat_frame, text="Kiểm tra kết nối Planner API: Chưa kiểm tra", font=ctk.CTkFont(size=13, weight="bold"))
        self.lbl_sync_conn.grid(row=0, column=0, padx=15, pady=15, sticky="w")

        btn_test_sync_api = ctk.CTkButton(sync_stat_frame, text="Kiểm tra kết nối API", width=120, command=self.test_planner_connection)
        btn_test_sync_api.grid(row=0, column=1, padx=15, pady=15, sticky="e")

        # Sync panel container
        sync_panel = ctk.CTkFrame(f)
        sync_panel.grid(row=2, column=0, padx=20, pady=10, sticky="nsew")
        sync_panel.grid_columnconfigure(0, weight=1)
        sync_panel.grid_rowconfigure(1, weight=1)

        lbl_queue_pending = ctk.CTkLabel(sync_panel, text="Danh sách hồ sơ chưa đồng bộ (PENDING/FAILED):", font=ctk.CTkFont(size=13, weight="bold"))
        lbl_queue_pending.grid(row=0, column=0, padx=15, pady=10, sticky="w")

        # Sync treeview for pending items
        self.sync_tree = ttk.Treeview(
            sync_panel, 
            columns=("no", "agency", "title", "status", "err_msg"), 
            show="headings"
        )
        self.sync_tree.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))

        self.sync_tree.heading("no", text="Số ký hiệu")
        self.sync_tree.heading("agency", text="Cơ quan gửi")
        self.sync_tree.heading("title", text="Trích yếu")
        self.sync_tree.heading("status", text="Trạng thái")
        self.sync_tree.heading("err_msg", text="Chi tiết lỗi")

        self.sync_tree.column("no", width=120, anchor="w")
        self.sync_tree.column("agency", width=150, anchor="w")
        self.sync_tree.column("title", width=380, anchor="w")
        self.sync_tree.column("status", width=100, anchor="center")
        self.sync_tree.column("err_msg", width=200, anchor="w")

        # Scrollbar
        sync_scroll = ttk.Scrollbar(sync_panel, orient="vertical", command=self.sync_tree.yview)
        self.sync_tree.configure(yscrollcommand=sync_scroll.set)
        sync_scroll.grid(row=1, column=1, sticky="ns", pady=(0, 15))

        # Sync Control buttons
        sync_ctrl_panel = ctk.CTkFrame(f)
        sync_ctrl_panel.grid(row=3, column=0, padx=20, pady=10, sticky="ew")

        btn_sync_single = ctk.CTkButton(sync_ctrl_panel, text="Đồng bộ hồ sơ chọn", fg_color="#2b5c8f", command=self.sync_selected_pending_item)
        btn_sync_single.pack(side="left", padx=15, pady=10)

        btn_sync_all = ctk.CTkButton(sync_ctrl_panel, text="Đồng bộ tất cả PENDING", fg_color="#2d8a4e", command=self.sync_all_pending_items)
        btn_sync_all.pack(side="left", padx=15, pady=10)

        # ------------------ 7. LOGS FRAME ------------------
        f = self.frames["logs"]
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        title = ctk.CTkLabel(f, text="NHẬT KÝ HOẠT ĐỘNG & LOG LỖI", font=ctk.CTkFont(size=20, weight="bold"))
        title.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        # Action Panel
        log_panel = ctk.CTkFrame(f)
        log_panel.grid(row=1, column=0, padx=20, pady=5, sticky="ew")
        log_panel.grid_columnconfigure(1, weight=1)

        # Log selection combo
        ctk.CTkLabel(log_panel, text="Chọn file Log:").grid(row=0, column=0, padx=15, pady=10, sticky="w")
        self.combo_log_files = ctk.CTkComboBox(log_panel, values=["Chưa có log"], command=lambda e: self.load_log_file_contents())
        self.combo_log_files.grid(row=0, column=1, padx=15, pady=10, sticky="ew")

        btn_refresh_logs = ctk.CTkButton(log_panel, text="Làm mới log", width=100, command=self.scan_log_files)
        btn_refresh_logs.grid(row=0, column=2, padx=10, pady=10)

        btn_open_log_dir = ctk.CTkButton(log_panel, text="Mở thư mục log", width=120, fg_color="#2b5c8f", command=self.open_logs_folder)
        btn_open_log_dir.grid(row=0, column=3, padx=10, pady=10)

        btn_diagnose_zip = ctk.CTkButton(log_panel, text="Xuất gói chẩn đoán", width=130, fg_color="#2d8a4e", command=self.run_doctor_support_package)
        btn_diagnose_zip.grid(row=0, column=4, padx=15, pady=10)

        # Log text editor
        self.log_viewer_text = ctk.CTkTextbox(f, font=("Consolas", 11))
        self.log_viewer_text.grid(row=2, column=0, padx=20, pady=10, sticky="nsew")

        # ------------------ 8. HELP FRAME ------------------
        f = self.frames["help"]
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        title = ctk.CTkLabel(f, text="HƯỚNG DẪN & CẢNH BÁO BẢO MẬT", font=ctk.CTkFont(size=20, weight="bold"))
        title.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        # Help content scroll area
        help_scroll = ctk.CTkScrollableFrame(f)
        help_scroll.grid(row=1, column=0, rowspan=2, padx=20, pady=10, sticky="nsew")
        help_scroll.grid_columnconfigure(0, weight=1)

        # Onboarding Guide
        g_lbl = ctk.CTkLabel(help_scroll, text="QUY TRÌNH 3 BƯỚC VẬN HÀNH AGENT:", font=ctk.CTkFont(size=15, weight="bold"), text_color="#2d8a4e")
        g_lbl.grid(row=0, column=0, padx=15, pady=(15, 10), sticky="w")

        g_body = ctk.CTkLabel(
            help_scroll,
            text="* Bước 1: Khai báo thông tin cấu hình QLVB và Planner KPI trong Tab 'Cấu hình'. Nhấp 'Lưu cấu hình'.\n"
                 "* Bước 2: Bấm vào Tab 'Đăng nhập QLVB' -> Click 'Mở trình duyệt đăng nhập'. Thực hiện đăng nhập và giải captcha.\n"
                 "* Bước 3: Vào Tab 'Tải văn bản' để bắt đầu quét tải các văn bản mới về máy. Dữ liệu sẽ được lưu tự động thành các\n"
                 "          gói hàng đợi (queue) chứa file manifest.json chuẩn.\n"
                 "* Bước 4: Chuyển sang Tab 'Đồng bộ KPI' và thực hiện đẩy hàng đợi văn bản sang Planner KPI backend.",
            justify="left",
            anchor="w",
            font=ctk.CTkFont(size=12)
        )
        g_body.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="w")

        # Security warnings
        sec_lbl = ctk.CTkLabel(help_scroll, text="CẢNH BÁO BẢO MẬT QUAN TRỌNG:", font=ctk.CTkFont(size=15, weight="bold"), text_color="#b22222")
        sec_lbl.grid(row=2, column=0, padx=15, pady=(15, 10), sticky="w")

        sec_body = ctk.CTkLabel(
            help_scroll,
            text="- Không sử dụng Agent để tải, xử lý các văn bản có mức độ Mật, Tối Mật, Tuyệt Mật.\n"
                 "- Tuyệt đối không đưa file cấu hình thực tế chứa mật khẩu hoặc token (qlvb_downloader_config.json)\n"
                 "  lên kho lưu trữ mã nguồn Git (dự án đã cấu hình loại trừ qua .gitignore).\n"
                 "- Không chia sẻ thư mục 'Data/runtime' (chứa session đăng nhập trình duyệt) cho bất kỳ ai.\n"
                 "- Khi gặp sự cố kỹ thuật, hãy xuất 'Gói chẩn đoán' trong Tab Nhật ký (đã được ẩn mật khẩu tự động)\n"
                 "  để gửi cho bộ phận kỹ thuật hỗ trợ.",
            justify="left",
            anchor="w",
            font=ctk.CTkFont(size=12)
        )
        sec_body.grid(row=3, column=0, padx=15, pady=(0, 15), sticky="w")

    def _create_stat_card(self, parent, title, value, color, col, row) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, height=100)
        card.grid(row=row, column=col, padx=15, pady=15, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        
        lbl_title = ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=12, weight="bold"), text_color="gray")
        lbl_title.grid(row=0, column=0, padx=15, pady=(15, 2), sticky="w")

        lbl_val = ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=22, weight="bold"), text_color=color)
        lbl_val.grid(row=1, column=0, padx=15, pady=(0, 15), sticky="w")
        return card

    def _create_config_field(self, parent, label, row, show=None) -> ctk.CTkEntry:
        lbl = ctk.CTkLabel(parent, text=label, anchor="w")
        lbl.grid(row=row, column=0, padx=10, pady=6, sticky="w")
        
        entry = ctk.CTkEntry(parent, show=show)
        entry.grid(row=row, column=1, padx=10, pady=6, sticky="ew")
        return entry

    def _create_config_field_with_btn(self, parent, label, row, link_type) -> ctk.CTkEntry:
        lbl = ctk.CTkLabel(parent, text=label, anchor="w")
        lbl.grid(row=row, column=0, padx=10, pady=6, sticky="w")
        
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.grid(row=row, column=1, padx=10, pady=6, sticky="ew")
        container.grid_columnconfigure(0, weight=1)
        
        entry = ctk.CTkEntry(container)
        entry.grid(row=0, column=0, sticky="ew")
        
        btn = ctk.CTkButton(container, text="Kiểm tra", width=70, command=lambda: self.test_fixed_url(entry.get(), link_type))
        btn.grid(row=0, column=1, padx=(10, 0))
        
        return entry

    def test_fixed_url(self, url: str, link_type: str):
        if not url:
            messagebox.showwarning("Cảnh báo", "Vui lòng nhập đường dẫn trước khi kiểm tra.")
            return
            
        def worker():
            from tools.qlvb_downloader.downloader import QLVBDownloader
            from tools.qlvb_downloader.config import load_config
            try:
                cfg = load_config()
                cfg.qlvb_base_url = self.entry_base.get()
                cfg.login_url = self.entry_login.get()
                cfg.username = self.entry_user.get()
                cfg.password = self.entry_pass.get()
                
                dl = QLVBDownloader(cfg)
                res = dl.validate_fixed_qlvb_url(url, link_type)
                if res.get("valid"):
                    if res.get("status") == "VALID_EMPTY":
                        msg = f"✓ HỢP LỆ\n\nTiêu đề trang: {res.get('title')}\nSố dòng dữ liệu: 0\nTrạng thái: {res.get('message')}"
                        messagebox.showinfo("Thành công (Trống)", msg)
                    else:
                        msg = f"✅ HỢP LỆ\n\nTiêu đề trang: {res.get('title')}\nSố dòng dữ liệu: {res.get('record_count')}\nCột: {', '.join(res.get('columns', []))}"
                        messagebox.showinfo("Thành công", msg)
                else:
                    messagebox.showerror("Lỗi kiểm tra", f"❌ KHÔNG HỢP LỆ\n\nChi tiết lỗi: {res.get('error')}")
            except Exception as e:
                messagebox.showerror("Lỗi", f"Lỗi hệ thống: {e}")
                
        # Show busy cursor while testing
        btn = [b for b in self.winfo_children() if isinstance(b, ctk.CTkButton) and b.cget("text") == "Kiểm tra"]
        threading.Thread(target=worker, daemon=True).start()

    def toggle_secrets_visibility(self):
        show_char = "" if self.show_secrets_var.get() else "*"
        self.entry_pass.configure(show=show_char)
        self.entry_planner_token.configure(show=show_char)

    def change_appearance_mode_event(self, new_appearance_mode: str):
        ctk.set_appearance_mode(new_appearance_mode)

    def select_frame_by_name(self, name):
        # Update sidebar button states
        for key in self.nav_buttons:
            if key == name:
                self.nav_buttons[key].configure(fg_color=("gray75", "gray25"))
            else:
                self.nav_buttons[key].configure(fg_color="transparent")

        # Hide all frames
        for f in self.frames.values():
            f.grid_forget()

        # Show selected frame
        self.frames[name].grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

        # Trigger screen refresh actions
        if name == "overview":
            self.quick_system_check()
        elif name == "queue":
            self.refresh_queue_table()
        elif name == "sync":
            self.refresh_sync_table()
        elif name == "logs":
            self.scan_log_files()
        elif name == "assignment_drafts":
            self.refresh_assignment_drafts()

    def _build_assignment_drafts_frame(self):
        frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["assignment_drafts"] = frame
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(3, weight=1)
        ctk.CTkLabel(frame, text="Dự thảo giao việc", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, padx=20, pady=(20, 8), sticky="w")
        self.assignment_tenant_label = ctk.CTkLabel(frame, text="")
        self.assignment_tenant_label.grid(row=1, column=0, padx=20, pady=(0, 8), sticky="w")
        actions = ctk.CTkFrame(frame); actions.grid(row=2, column=0, padx=20, pady=8, sticky="ew")
        ctk.CTkButton(actions, text="Làm mới", command=self.refresh_assignment_drafts).pack(side="left", padx=8, pady=8)
        ctk.CTkButton(actions, text="Xem chi tiết", command=self.show_assignment_draft).pack(side="left", padx=8, pady=8)
        self.assignment_tree = ttk.Treeview(frame, columns=("title", "unit", "due", "priority", "version", "status"), show="headings")
        for key, text, width in (("title", "Tiêu đề nhiệm vụ", 300), ("unit", "Đơn vị", 130), ("due", "Thời hạn", 100), ("priority", "Ưu tiên", 90), ("version", "Phiên bản", 80), ("status", "Trạng thái", 160)):
            self.assignment_tree.heading(key, text=text); self.assignment_tree.column(key, width=width, anchor="w")
        self.assignment_tree.grid(row=3, column=0, padx=20, pady=(0, 20), sticky="nsew")

    def refresh_assignment_drafts(self):
        for item in self.assignment_tree.get_children(): self.assignment_tree.delete(item)
        tenant = self.cfg.active_tenant_id.strip()
        if not tenant:
            self.assignment_tenant_label.configure(text="Chưa xác định đơn vị làm việc")
            return
        try:
            service = AssignmentDraftService(str(self.cfg.root_path))
            self.assignment_tenant_label.configure(text=f"Đơn vị làm việc: {tenant}")
            for draft in service.list_pending_drafts(tenant):
                self.assignment_tree.insert("", "end", iid=draft.id, values=(draft.task_title, draft.lead_unit_source_key or "", draft.proposed_due_date or "", draft.priority, draft.draft_version, planner_display_status(draft.current_status)))
        except AssignmentDraftServiceError as exc: self.assignment_tenant_label.configure(text=str(exc))

    def show_assignment_draft(self):
        selected = self.assignment_tree.selection()
        tenant = self.cfg.active_tenant_id.strip()
        if not selected or not tenant:
            return
        try:
            AssignmentDraftDetailDialog(
                self,
                AssignmentDraftService(str(self.cfg.root_path)),
                tenant,
                selected[0],
                self.refresh_assignment_drafts,
                self.cfg.planner_api_url,
                self.cfg.planner_ingest_token,
            ).show()
        except AssignmentDraftServiceError as exc:
            messagebox.showerror("Du thao giao viec", str(exc))

    def _legacy_show_assignment_draft(self):
        selected = self.assignment_tree.selection()
        tenant = self.cfg.active_tenant_id.strip()
        if not selected or not tenant: return
        try:
            draft = AssignmentDraftService(str(self.cfg.root_path)).get_draft_detail(tenant, selected[0])
            if not draft: raise AssignmentDraftServiceError("Không tìm thấy dự thảo")
            window = ctk.CTkToplevel(self); window.title("Chi tiết dự thảo"); window.geometry("700x560")
            text = ctk.CTkTextbox(window); text.pack(fill="both", expand=True, padx=16, pady=16)
            people = "\n".join(f"- {p.role_type}: {p.personnel_source_key}" for p in draft.personnel) or "Chưa đề xuất"
            warnings = "\n".join(f"- {w.get('code', '')}" for w in draft.warnings) or "Không có"
            text.insert("1.0", f"Văn bản: {draft.source_document_id}\nPhiên bản: {draft.draft_version}\nTrạng thái: {draft.initial_status}\n\n{draft.task_title}\n\n{draft.task_description}\n\nĐơn vị: {draft.lead_unit_source_key or ''}\nThời hạn: {draft.proposed_due_date or ''}\nƯu tiên: {draft.priority}\nTin cậy: {draft.overall_confidence}\n\nNhân sự:\n{people}\n\nCảnh báo:\n{warnings}")
            text.configure(state="disabled")
            controls = ctk.CTkFrame(window); controls.pack(fill="x", padx=16, pady=(0, 16))
            service = AssignmentDraftService(str(self.cfg.root_path)); reviewer = "LOCAL_OFFICE"
            def disable_actions():
                for button in (edit_button, approve_button, reject_button): button.configure(state="disabled")
            def revise():
                title = simpledialog.askstring("Chỉnh sửa", "Tiêu đề nhiệm vụ:", initialvalue=draft.task_title, parent=window)
                if title is None: return
                due = simpledialog.askstring("Chỉnh sửa", "Thời hạn (YYYY-MM-DD):", initialvalue=draft.proposed_due_date or "", parent=window)
                if due is None: return
                reason = simpledialog.askstring("Lý do chỉnh sửa", "Lý do (không bắt buộc):", parent=window)
                edits = {}
                if title != draft.task_title: edits["task_title"] = title
                if due != (draft.proposed_due_date or ""): edits["proposed_due_date"] = due or None
                if not edits: return
                try:
                    service.revise_draft(tenant, draft.id, edits, reviewer, reason)
                    messagebox.showinfo("Dự thảo giao việc", "Đã lưu phiên bản mới"); self.refresh_assignment_drafts(); window.destroy()
                except AssignmentDraftServiceError as exc: messagebox.showerror("Dự thảo giao việc", str(exc))
            def approve():
                if not messagebox.askyesno("Xác nhận", "Xác nhận duyệt dự thảo để chuẩn bị gửi Planner KPI?", parent=window): return
                try:
                    service.approve_draft(tenant, draft.id, reviewer)
                    messagebox.showinfo("Dự thảo giao việc", "Đã duyệt, sẵn sàng chuẩn bị gửi Planner KPI"); disable_actions(); self.refresh_assignment_drafts()
                except AssignmentDraftServiceError as exc: messagebox.showerror("Dự thảo giao việc", str(exc))
            def reject():
                reason = simpledialog.askstring("Từ chối", "Lý do từ chối:", parent=window)
                if not reason or not reason.strip(): messagebox.showwarning("Dự thảo giao việc", "Lý do từ chối là bắt buộc", parent=window); return
                try:
                    service.reject_draft(tenant, draft.id, reviewer, reason)
                    messagebox.showinfo("Dự thảo giao việc", "Đã từ chối dự thảo"); disable_actions(); self.refresh_assignment_drafts()
                except AssignmentDraftServiceError as exc: messagebox.showerror("Dự thảo giao việc", str(exc))
            edit_button = ctk.CTkButton(controls, text="Chỉnh sửa", command=revise); edit_button.pack(side="left", padx=6, pady=8)
            approve_button = ctk.CTkButton(controls, text="Duyệt để chuẩn bị gửi Planner", command=approve); approve_button.pack(side="left", padx=6, pady=8)
            reject_button = ctk.CTkButton(controls, text="Từ chối", fg_color="#b22222", command=reject); reject_button.pack(side="left", padx=6, pady=8)
        except AssignmentDraftServiceError as exc: messagebox.showerror("Dự thảo giao việc", str(exc))

    def write_log(self, text: str):
        self.log_textbox.insert("end", text)
        self.log_textbox.see("end")

    # ------------------ ACTIONS & THREADED COMMAND RUNNERS ------------------

    def run_command_async(self, cmd, console_widget, on_finish=None):
        if self.is_running:
            messagebox.showwarning("Cảnh báo", "Đang có tiến trình chạy nền. Hãy đợi kết thúc.")
            return

        console_widget.delete("1.0", "end")
        self.is_running = True
        
        if hasattr(self, "start_btn"):
            self.start_btn.configure(state="disabled")
        if hasattr(self, "stop_btn"):
            self.stop_btn.configure(state="normal")
        if hasattr(self, "progress_bar"):
            self.progress_bar.set(0)

        self.stdout_queue = queue.Queue()

        def worker():
            try:
                # Set environment encoding for python output
                env = os.environ.copy()
                env["PYTHONUTF8"] = "1"
                env["PYTHONIOENCODING"] = "utf-8"
                
                self.running_proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.root_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    encoding="utf-8",
                    errors="replace",
                    text=True,
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                )
                assert self.running_proc.stdout is not None
                for line in self.running_proc.stdout:
                    self.stdout_queue.put(line)
                self.running_proc.wait()
            except Exception as e:
                self.stdout_queue.put(f"Lỗi chạy tiến trình con: {e}\n")
            finally:
                self.stdout_queue.put(None) # Sentinel

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, lambda: self.poll_command_output(console_widget, on_finish))

    def poll_command_output(self, console_widget, on_finish=None):
        try:
            while True:
                line = self.stdout_queue.get_nowait()
                if line is None:
                    # Finished
                    self.is_running = False
                    if hasattr(self, "start_btn"):
                        self.start_btn.configure(state="normal")
                    if hasattr(self, "stop_btn"):
                        self.stop_btn.configure(state="disabled")
                    if hasattr(self, "progress_bar"):
                        self.progress_bar.set(1.0)
                        
                    exit_code = self.running_proc.returncode if self.running_proc else -1
                    self.running_proc = None
                    
                    console_widget.insert("end", f"\n--- Tiến trình kết thúc (Mã thoát: {exit_code}) ---\n")
                    console_widget.see("end")
                    
                    if on_finish:
                        on_finish(exit_code)
                    return
                else:
                    console_widget.insert("end", line)
                    console_widget.see("end")
                    if hasattr(self, "progress_bar"):
                        if "trang" in line.lower() or "tai tep" in line.lower():
                            self.progress_bar.set(0.5)
        except queue.Empty:
            pass

        if self.is_running:
            self.after(100, lambda: self.poll_command_output(console_widget, on_finish))

    def stop_command(self):
        if self.running_proc:
            self.write_log("\n[DỪNG] Đang yêu cầu dừng tiến trình...\n")
            try:
                self.running_proc.terminate()
                threading.Timer(2.0, self.force_kill_proc).start()
            except Exception as e:
                self.write_log(f"Lỗi dừng tiến trình: {e}\n")

    def force_kill_proc(self):
        if self.running_proc:
            try:
                self.running_proc.kill()
                self.write_log("[DỪNG] Đã buộc dừng tiến trình.\n")
            except Exception:
                pass

    def get_command_prefix(self, module_name: str) -> list[str]:
        if getattr(sys, 'frozen', False):
            exe_dir = Path(sys.executable).parent
            if module_name == "doctor":
                exe_path = exe_dir / "qlvb_doctor.exe"
                if exe_path.exists():
                    return [str(exe_path)]
            elif module_name == "runner":
                exe_path = exe_dir / "qlvb_runner.exe"
                if exe_path.exists():
                    return [str(exe_path)]
        # Fallback to standard Python invocation
        return [sys.executable, "-m", f"tools.qlvb_downloader.{module_name}"]

    # 1. Action: Quick check system
    def quick_system_check(self):
        # Run doctor check in background
        cmd = self.get_command_prefix("doctor") + ["--check"]
        
        # Read configs to see qlvb status
        def on_finish(exit_code):
            # Check login and session
            # Update stats on Overview screen
            has_session = (self.cfg.browser_profile_path / "Default/Cookies").exists() or \
                          (self.cfg.browser_profile_path / "Cookies").exists() or \
                          any(self.cfg.browser_profile_path.rglob("Cookies*"))
                          
            status_text = "Đã cấu hình" if self.cfg.qlvb_base_url else "Chưa cấu hình"
            self.card_qlvb.winfo_children()[1].configure(text=status_text, text_color="green" if self.cfg.qlvb_base_url else "red")
            
            sess_text = "Có Session" if has_session else "Chưa có session"
            self.card_session.winfo_children()[1].configure(text=sess_text, text_color="green" if has_session else "orange")
            
            # Count queues
            self._update_queue_counts()

        # Run invisibly
        self.run_doctor_invisible(on_finish)

    def run_doctor_invisible(self, on_finish):
        # Short background execution without writing to UI console
        def worker():
            try:
                env = os.environ.copy()
                env["PYTHONUTF8"] = "1"
                env["PYTHONIOENCODING"] = "utf-8"
                p = subprocess.Popen(
                    self.get_command_prefix("doctor") + ["--check"],
                    cwd=str(self.root_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                p.wait()
            except Exception:
                pass
            finally:
                self.after(10, on_finish, 0)
        threading.Thread(target=worker, daemon=True).start()

    def _update_queue_counts(self):
        # Update overview counts by scanning files
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_count = 0
        pending_count = 0
        failed_count = 0
        
        for direction in ["incoming", "outgoing"]:
            d_dir = self.storage.queue_root / direction
            if d_dir.exists():
                for item in d_dir.iterdir():
                    if item.is_dir():
                        # Read manifest
                        manifest_path = item / "manifest.json"
                        if manifest_path.exists():
                            try:
                                data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                                sync_data = data.get("sync", {})
                                p_status = sync_data.get("planner_kpi_status", "PENDING")
                                if p_status in ["PENDING", "SYNCING"]:
                                    pending_count += 1
                                elif p_status == "FAILED":
                                    failed_count += 1
                                
                                dl_at = data.get("downloaded_at", "")
                                if dl_at and dl_at.startswith(today_str):
                                    today_count += 1
                            except Exception:
                                pass
                                
        self.card_today.winfo_children()[1].configure(text=str(today_count))
        self.card_pending.winfo_children()[1].configure(text=str(pending_count))
        self.card_failed.winfo_children()[1].configure(text=str(failed_count))

    # 2. Action: Run Login Only
    def run_login_only(self):
        self.lbl_login_status.configure(text="Trạng thái phiên: Đang mở trình duyệt đăng nhập...")
        cmd = self.get_command_prefix("runner") + ["--login-only", "--headless", "false"]
        
        def on_finish(exit_code):
            if exit_code == 0:
                self.lbl_login_status.configure(text="Trạng thái phiên: Đăng nhập THÀNH CÔNG và đã lưu phiên")
                messagebox.showinfo("Đăng nhập", "Đã lưu phiên đăng nhập QLVB thành công!")
            else:
                self.lbl_login_status.configure(text="Trạng thái phiên: Chưa đăng nhập thành công")
                messagebox.showerror("Đăng nhập", "Đăng nhập chưa thành công. Vui lòng thử lại.")
            self.quick_system_check()
            
        self.run_command_async(cmd, self.login_console, on_finish)

    # 3. Action: Test Configuration
    def test_configuration(self):
        self.save_configuration(silent=True)
        cmd = self.get_command_prefix("doctor") + ["--check"]
        self.run_command_async(cmd, self.log_textbox)

    # 4. Action: Save Configuration
    def save_configuration(self, silent=False):
        self.cfg.qlvb_base_url = self.entry_base.get().strip()
        self.cfg.login_url = self.entry_login.get().strip()
        self.cfg.username = self.entry_user.get().strip()
        self.cfg.password = self.entry_pass.get()
        self.cfg.incoming_pending_url = self.entry_in_pending.get().strip()
        self.cfg.incoming_processed_url = self.entry_in_processed.get().strip()
        self.cfg.outgoing_issued_url = self.entry_out_issued.get().strip()
        self.cfg.use_fixed_urls = self.use_fixed_urls_var.get()
        self.cfg.save_root = self.entry_save.get().strip()
        
        self.cfg.remember_password = self.remember_pass_var.get()
        self.cfg.browser.headless = self.headless_var.get()
        
        try:
            self.cfg.download.max_items_per_run = int(self.entry_max_items.get().strip())
            self.cfg.download.max_pages_per_direction = int(self.entry_max_pages.get().strip())
            self.cfg.browser.manual_login_wait_seconds = int(self.entry_manual_wait.get().strip())
        except Exception:
            pass

        self.cfg.planner_api_url = self.entry_planner_url.get().strip()
        self.cfg.planner_ingest_token = self.entry_planner_token.get().strip()

        save_config(self.cfg)
        if not silent:
            messagebox.showinfo("Thành công", "Đã lưu cấu hình thành công!")

    # 5. Action: Start Download
    def start_download(self):
        direction = self.combo_dir.get()
        headless_str = "true" if self.headless_var.get() else "false"
        dry_run_str = "true" if self.dry_run_var.get() else "false"
        
        cmd = self.get_command_prefix("runner") + [
            "--directions", direction,
            "--headless", headless_str,
            "--dry-run", dry_run_str
        ]
        
        max_limit = self.entry_run_max.get().strip()
        if max_limit:
            cmd.extend(["--max-items", max_limit])
            
        def on_finish(exit_code):
            self.quick_system_check()
            if exit_code == 0:
                messagebox.showinfo("Tải hoàn tất", "Hoàn thành phiên quét văn bản QLVB.")
            else:
                messagebox.showerror("Lỗi", "Phiên quét văn bản thất bại hoặc bị hủy.")
                
        self.run_command_async(cmd, self.log_textbox, on_finish)

    # 6. Action: Refresh Queue Table (Placeholder for stage 2)
    def refresh_queue_table(self):
        # Clear table
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        dir_filter = self.q_filter_dir.get()
        status_filter = self.q_filter_status.get()
        
        directions = ["incoming", "outgoing"] if dir_filter == "Tất cả" else [dir_filter]
        
        from tools.qlvb_downloader.parser import validate_record_data

        for d in directions:
            q_path = self.storage.queue_root / d
            if q_path.exists():
                for folder in q_path.iterdir():
                    if folder.is_dir() and not folder.name.endswith("_ERROR"):
                        manifest_path = folder / "manifest.json"
                        if manifest_path.exists():
                            try:
                                data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                                sync_data = data.get("sync", {})
                                p_status = sync_data.get("planner_kpi_status", "PENDING")
                                
                                if status_filter != "Tất cả" and p_status != status_filter:
                                    continue
                                    
                                file_count = len(data.get("attachments", []))
                                main_doc = data.get("main_document")
                                if main_doc:
                                    file_count += 1
                                    
                                # Evaluate data quality
                                doc_no = data.get("document_number") or ""
                                title = data.get("summary") or ""
                                doc_date = data.get("issued_date") or ""
                                agency = data.get("issuing_agency") or ""
                                
                                if main_doc is None:
                                    status_quality = "Nghi ngờ"
                                else:
                                    q_status, q_reason = validate_record_data(doc_no, title, doc_date, agency, main_doc_meta=main_doc)
                                    if q_status == "INVALID":
                                        status_quality = "Tài khoản"
                                    elif q_status == "SUSPICIOUS":
                                        status_quality = "Nghi ngờ"
                                    else:
                                        status_quality = "Hợp lệ"
                                    
                                self.tree.insert("", "end", values=(
                                    doc_no or "N/A",
                                    doc_date or "N/A",
                                    agency or "N/A",
                                    title or "N/A",
                                    status_quality,
                                    p_status,
                                    data.get("downloaded_at", "").replace("T", " ")
                                ), tags=(folder.name, d))
                            except Exception:
                                pass

    # Action: Open Selected Queue Folder
    def open_selected_queue_folder(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Cảnh báo", "Hãy chọn một hàng đợi trong danh sách.")
            return
        
        tags = self.tree.item(sel[0], "tags")
        folder_name = tags[0]
        direction = tags[1]
        
        target = self.storage.queue_root / direction / folder_name
        if target.exists():
            try:
                if os.name == 'nt':
                    os.startfile(target)
                else:
                    subprocess.Popen(["xdg-open", str(target)])
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không mở được thư mục: {e}")

    # Action: View Selected Manifest
    def view_selected_manifest(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Cảnh báo", "Hãy chọn một hàng đợi trong danh sách.")
            return
            
        tags = self.tree.item(sel[0], "tags")
        folder_name = tags[0]
        direction = tags[1]
        
        manifest_path = self.storage.queue_root / direction / folder_name / "manifest.json"
        if manifest_path.exists():
            try:
                # Open in a new text window
                content = manifest_path.read_text(encoding="utf-8-sig")
                try:
                    obj = json.loads(content)
                    content = json.dumps(obj, indent=2, ensure_ascii=False)
                except Exception:
                    pass
                
                win = ctk.CTkToplevel(self)
                win.title(f"Manifest: {folder_name}")
                win.geometry("650x550")
                win.lift()
                win.attributes("-topmost", True)
                
                tb = ctk.CTkTextbox(win, font=("Consolas", 11))
                tb.pack(fill="both", expand=True, padx=15, pady=15)
                tb.insert("1.0", content)
                tb.configure(state="disabled") # Make it read-only
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không đọc được file manifest: {e}")

    # Action: Sync Selected Queue Item (Placeholder for stage 3)
    def sync_selected_queue_item(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Cảnh báo", "Hãy chọn một hàng đợi trong danh sách.")
            return
            
        tags = self.tree.item(sel[0], "tags")
        doc_id = tags[0]
        direction = tags[1]
        
        # Check data quality column
        values = self.tree.item(sel[0], "values")
        if len(values) > 4:
            quality = values[4]
            if quality in ["Nghi ngờ", "Tài khoản", "Không hợp lệ"]:
                messagebox.showerror(
                    "Lỗi đồng bộ",
                    f"Không thể đồng bộ bản ghi này do chất lượng dữ liệu: {quality}.\n"
                    "Bản ghi Nghi ngờ/Tài khoản bị chặn đồng bộ sang KPI."
                )
                return
        
        # Trigger client sync
        self.sync_document_to_api(direction, doc_id)

    # 7. Action: Refresh Sync Table (Placeholder for stage 3)
    def refresh_sync_table(self):
        for item in self.sync_tree.get_children():
            self.sync_tree.delete(item)
            
        for d in ["incoming", "outgoing"]:
            q_path = self.storage.queue_root / d
            if q_path.exists():
                for folder in q_path.iterdir():
                    if folder.is_dir() and not folder.name.endswith("_ERROR"):
                        manifest_path = folder / "manifest.json"
                        if manifest_path.exists():
                            try:
                                data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                                sync_data = data.get("sync", {})
                                p_status = sync_data.get("planner_kpi_status", "PENDING")
                                
                                if p_status in ["PENDING", "FAILED"]:
                                    self.sync_tree.insert("", "end", values=(
                                        data.get("document_number") or "N/A",
                                        data.get("issuing_agency") or "N/A",
                                        data.get("summary") or "N/A",
                                        p_status,
                                        sync_data.get("last_error") or ""
                                    ), tags=(folder.name, d))
                            except Exception:
                                pass

    # Action: Sync Selected Pending Item
    def sync_selected_pending_item(self):
        sel = self.sync_tree.selection()
        if not sel:
            messagebox.showwarning("Cảnh báo", "Hãy chọn một hồ sơ chưa đồng bộ.")
            return
            
        tags = self.sync_tree.item(sel[0], "tags")
        doc_id = tags[0]
        direction = tags[1]
        
        # Load manifest to evaluate quality
        manifest_info = self.storage.get_queue_item_files(direction, doc_id)
        if manifest_info:
            manifest = manifest_info.get("manifest", {})
            from tools.qlvb_downloader.parser import validate_record_data
            doc_no = manifest.get("document_number") or ""
            title = manifest.get("summary") or ""
            doc_date = manifest.get("issued_date") or ""
            agency = manifest.get("issuing_agency") or ""
            main_doc = manifest.get("main_document")
            
            if main_doc is None:
                status_quality = "Nghi ngờ"
            else:
                q_status, q_reason = validate_record_data(doc_no, title, doc_date, agency, main_doc_meta=main_doc)
                if q_status == "INVALID":
                    status_quality = "Tài khoản"
                elif q_status == "SUSPICIOUS":
                    status_quality = "Nghi ngờ"
                else:
                    status_quality = "Hợp lệ"
            
            if status_quality in ["Nghi ngờ", "Tài khoản"]:
                messagebox.showerror(
                    "Lỗi đồng bộ",
                    f"Không thể đồng bộ bản ghi này do chất lượng dữ liệu: {status_quality}.\n"
                    "Vui lòng thực hiện cách ly dữ liệu lỗi trước."
                )
                return
        
        self.sync_document_to_api(direction, doc_id)

    # Action: Sync All Pending Items
    def sync_all_pending_items(self):
        items = self.sync_tree.get_children()
        if not items:
            messagebox.showinfo("Đồng bộ", "Không có hồ sơ nào cần đồng bộ.")
            return
            
        # Run sync sequentially in a thread to prevent blocking UI
        def worker():
            success_count = 0
            fail_count = 0
            skipped_count = 0
            for it in items:
                tags = self.sync_tree.item(it, "tags")
                doc_id = tags[0]
                direction = tags[1]
                
                # Check data quality
                manifest_info = self.storage.get_queue_item_files(direction, doc_id)
                if manifest_info:
                    manifest = manifest_info.get("manifest", {})
                    from tools.qlvb_downloader.parser import validate_record_data
                    doc_no = manifest.get("document_number") or ""
                    title = manifest.get("summary") or ""
                    doc_date = manifest.get("issued_date") or ""
                    agency = manifest.get("issuing_agency") or ""
                    main_doc = manifest.get("main_document")
                    
                    if main_doc is None:
                        status_quality = "Nghi ngờ"
                    else:
                        q_status, q_reason = validate_record_data(doc_no, title, doc_date, agency, main_doc_meta=main_doc)
                        if q_status == "INVALID":
                            status_quality = "Tài khoản"
                        elif q_status == "SUSPICIOUS":
                            status_quality = "Nghi ngờ"
                        else:
                            status_quality = "Hợp lệ"
                            
                    if status_quality in ["Nghi ngờ", "Tài khoản"]:
                        skipped_count += 1
                        continue
                
                ok = self.perform_sync_upload(direction, doc_id)
                if ok:
                    success_count += 1
                else:
                    fail_count += 1
                    
            msg_parts = [f"Đã đồng bộ xong tất cả hồ sơ hợp lệ.", f"Thành công: {success_count}", f"Thất bại: {fail_count}"]
            if skipped_count > 0:
                msg_parts.append(f"Bị bỏ qua do lỗi dữ liệu: {skipped_count}")
                
            self.after(10, lambda: messagebox.showinfo(
                "Đồng bộ hoàn tất", 
                "\n".join(msg_parts)
            ))
            self.after(10, self.refresh_sync_table)
            self.after(10, self.quick_system_check)

        threading.Thread(target=worker, daemon=True).start()

    # Action: Test Planner Connection
    def test_planner_connection(self):
        self.lbl_sync_conn.configure(text="Đang kết nối đến Planner KPI API...")
        
        # Make requests call in thread
        def worker():
            import requests
            url = self.cfg.planner_api_url
            token = self.cfg.planner_ingest_token
            
            if not url:
                self.after(10, lambda: self.lbl_sync_conn.configure(text="Kết nối thất bại: Chưa cấu hình URL", text_color="red"))
                return
                
            try:
                # We can check health endpoint
                headers = {"Authorization": f"Bearer {token}"}
                # Fallback path /api/db-health or /api/health
                health_url = url.rstrip('/') + "/api/db-health"
                r = requests.get(health_url, headers=headers, timeout=5)
                if r.ok:
                    msg = f"Kết nối THÀNH CÔNG (HTTP {r.status_code})"
                    color = "green"
                else:
                    msg = f"Kết nối lỗi (HTTP {r.status_code}): {r.text[:50]}"
                    color = "orange"
            except Exception as e:
                msg = f"Kết nối THẤT BẠI: {str(e)[:50]}"
                color = "red"
                
            self.after(10, lambda: self.lbl_sync_conn.configure(text=msg, text_color=color))

        threading.Thread(target=worker, daemon=True).start()

    # Dummy/Placeholder sync client methods (Stage 3 actual implementation will use these)
    def sync_document_to_api(self, direction, doc_id):
        # Sync single document
        def worker():
            ok = self.perform_sync_upload(direction, doc_id)
            if ok:
                self.after(10, lambda: messagebox.showinfo("Đồng bộ", f"Đã đồng bộ thành công hồ sơ: {doc_id}"))
            else:
                self.after(10, lambda: messagebox.showerror("Lỗi đồng bộ", f"Đồng bộ thất bại hồ sơ: {doc_id}"))
            self.after(10, self.refresh_queue_table)
            self.after(10, self.refresh_sync_table)
            self.after(10, self.quick_system_check)

        threading.Thread(target=worker, daemon=True).start()

    def perform_sync_upload(self, direction, doc_id) -> bool:
        # Check if sync client module exists
        try:
            from .sync_client import sync_upload
            return sync_upload(self.cfg, direction, doc_id)
        except Exception as e:
            # Local fallback simulator if sync_client.py is not created yet
            # In Phase 3, this will be fully active
            try:
                manifest_path = self.storage.queue_root / direction / doc_id / "manifest.json"
                if manifest_path.exists():
                    data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                    if "sync" not in data:
                        data["sync"] = {}
                    data["sync"]["planner_kpi_status"] = "FAILED"
                    data["sync"]["last_sync_at"] = datetime.now().isoformat()
                    data["sync"]["last_error"] = "Thư viện client đồng bộ chưa được nạp"
                    
                    self.storage.write_json(manifest_path, data)
            except Exception:
                pass
            return False

    # 8. Action: Scan Log Files
    def scan_log_files(self):
        log_dir = self.storage.log_root
        if not log_dir.exists():
            return
            
        logs = sorted(
            [f for f in log_dir.iterdir() if f.is_file() and f.name.endswith(".log")],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        
        self.combo_log_files.configure(values=[f.name for f in logs] if logs else ["Chưa có log"])
        if logs:
            self.combo_log_files.set(logs[0].name)
            self.load_log_file_contents()

    def load_log_file_contents(self):
        name = self.combo_log_files.get()
        if name and name != "Chưa có log":
            log_path = self.storage.log_root / name
            if log_path.exists():
                try:
                    content = log_path.read_text(encoding="utf-8", errors="replace")
                    self.log_viewer_text.delete("1.0", "end")
                    self.log_viewer_text.insert("1.0", content)
                    self.log_viewer_text.see("end")
                except Exception as e:
                    self.log_viewer_text.delete("1.0", "end")
                    self.log_viewer_text.insert("1.0", f"Lỗi đọc log: {e}")

    # Action: Open Log Folder
    def open_logs_folder(self):
        try:
            if os.name == 'nt':
                os.startfile(self.storage.log_root)
            else:
                subprocess.Popen(["xdg-open", str(self.storage.log_root)])
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không mở được thư mục: {e}")

    # Action: Run Doctor Support Package
    def run_doctor_support_package(self):
        cmd = self.get_command_prefix("doctor") + ["--support-package"]
        
        def on_finish(exit_code):
            if exit_code == 0:
                messagebox.showinfo("Thành công", "Đã xuất gói chẩn đoán lỗi thành công vào Data/support_packages/")
            else:
                messagebox.showerror("Thất bại", "Lỗi khi chạy gói chẩn đoán.")
                
        # Run inside log console
        self.run_command_async(cmd, self.log_viewer_text, on_finish)

    # Action: Run Audit Tool
    def run_audit_tool(self):
        def run_thread():
            try:
                from tools.qlvb_downloader.audit_queue import run_audit
                report = run_audit(apply=False, data_path=self.storage.data_root)
                st = report["stats"]
                
                msg = (
                    "Kết quả đánh giá dữ liệu hàng đợi:\n\n"
                    f"- Tổng hàng đợi (Queue): {st['total_queue']} (Hợp lệ: {st['queue_valid']}, Nghi ngờ: {st['queue_suspicious']}, Không hợp lệ: {st['queue_invalid']})\n"
                    f"- Tổng thư mục nguồn (Files): {st['total_files']} (Hợp lệ: {st['files_valid']}, Nghi ngờ: {st['files_suspicious']}, Không hợp lệ: {st['files_invalid']})\n"
                    f"- Số lượng đề xuất cách ly: {st['total_quarantine_candidates']}\n\n"
                    "Báo cáo chi tiết đã lưu tại Data/reports/latest_audit.txt"
                )
                
                def show_popup():
                    self.refresh_queue_table()
                    self.quick_system_check()
                    
                    win = ctk.CTkToplevel(self)
                    win.title("Báo cáo đánh giá chất lượng dữ liệu")
                    win.geometry("800x600")
                    win.lift()
                    win.attributes("-topmost", True)
                    
                    lbl = ctk.CTkLabel(win, text=msg, justify="left", font=("Arial", 12, "bold"))
                    lbl.pack(padx=20, pady=10, anchor="w")
                    
                    txt_path = self.storage.data_root / "reports" / "latest_audit.txt"
                    content = ""
                    if txt_path.exists():
                        content = txt_path.read_text(encoding="utf-8")
                        
                    tb = ctk.CTkTextbox(win, font=("Consolas", 10))
                    tb.pack(fill="both", expand=True, padx=20, pady=10)
                    tb.insert("1.0", content)
                    tb.configure(state="disabled")
                    
                self.after(10, show_popup)
            except Exception as e:
                self.after(10, lambda: messagebox.showerror("Lỗi", f"Lỗi khi chạy đánh giá dữ liệu: {e}"))
                
        threading.Thread(target=run_thread, daemon=True).start()

    # Action: Run Quarantine
    def run_quarantine(self):
        confirm = messagebox.askyesno(
            "Xác nhận cách ly dữ liệu lỗi",
            "Hành động này sẽ di chuyển toàn bộ hàng đợi/thư mục không hợp lệ (như tài khoản người dùng lấy nhầm, thiếu file chính) sang thư mục cách ly Data/quarantine/ để đảm bảo an toàn dữ liệu.\n\nBạn có muốn thực hiện không?"
        )
        if not confirm:
            return
            
        def run_thread():
            try:
                from tools.qlvb_downloader.audit_queue import run_audit
                report = run_audit(apply=True, data_path=self.storage.data_root)
                st = report["stats"]
                
                msg = (
                    "ĐÃ HOÀN TẤT CÁCH LY DỮ LIỆU LỖI!\n\n"
                    f"- Số lượng thư mục đã cách ly: {st['quarantined_count']}\n"
                    f"- Thư mục đích: Data/quarantine/{report['timestamp']}/\n\n"
                    "Hệ thống đã tự động dọn dẹp các thư mục này khỏi danh sách hàng đợi chính."
                )
                
                self.after(10, lambda: messagebox.showinfo("Hoàn tất cách ly", msg))
                self.after(10, self.refresh_queue_table)
                self.after(10, self.refresh_sync_table)
                self.after(10, self.quick_system_check)
            except Exception as e:
                self.after(10, lambda: messagebox.showerror("Lỗi cách ly", f"Lỗi khi thực hiện cách ly dữ liệu: {e}"))
                
        threading.Thread(target=run_thread, daemon=True).start()


def main():
    app = ConfigApp()
    app.mainloop()

if __name__ == "__main__":
    main()
