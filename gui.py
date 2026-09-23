"""CircuitRunners Outreach — desktop app for creating Gmail drafts.

A friendly tkinter front-end over the tested ``outreach_drafts`` module, meant
for the whole team to use on the shared CircuitRunners Gmail account. Supports:
- Single draft creation with live preview and validation
- Bulk CSV import and batch draft processing with progress tracking
- Managed Photo Pool for Elementary/Middle outreach demo photos
- Settings persistence and Google connection testing

The app builds personalized Gmail *drafts* (it never sends), CC's the team
coordinators, and attaches demo photos from the photo pool.
"""
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

import outreach_drafts as od

APP_NAME = "CircuitRunners Outreach"


# ---------------------------------------------------------------------------
# Bundle-aware, cross-platform paths (script, macOS .app, or Windows .exe)
# ---------------------------------------------------------------------------
def _resource_base() -> str:
    """Folder holding bundled resources (attachments, and credentials if any)."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _writable_base() -> str:
    """A per-user writable folder for the saved login token + user credentials.

    Windows -> %APPDATA%/CircuitRunners Outreach
    macOS   -> ~/Library/Application Support/CircuitRunners Outreach
    script  -> the project folder
    """
    if getattr(sys, "frozen", False):
        if sys.platform.startswith("win"):
            root = os.environ.get("APPDATA") or os.path.expanduser("~")
            base = os.path.join(root, APP_NAME)
        elif sys.platform == "darwin":
            base = os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
        else:
            base = os.path.expanduser(f"~/.{APP_NAME.lower().replace(' ', '-')}")
        os.makedirs(base, exist_ok=True)
        return base
    return os.path.dirname(os.path.abspath(__file__))


def _resolve_credentials_path() -> str:
    """Pick the credentials.json to use, in priority order."""
    writable_creds = os.path.join(_writable_base(), "credentials.json")
    if os.path.exists(writable_creds):
        return writable_creds
    bundled_creds = os.path.join(_resource_base(), "credentials.json")
    return bundled_creds if os.path.exists(bundled_creds) else writable_creds


def _configure_paths() -> None:
    base = _resource_base()
    writable = _writable_base()

    od.ATTACHMENTS_DIR = os.path.join(base, "attachments")
    od.CREDENTIALS_FILE = _resolve_credentials_path()

    bundled_token = os.path.join(base, "token.json")
    writable_token = os.path.join(writable, "token.json")
    if not os.path.exists(writable_token) and os.path.exists(bundled_token):
        try:
            shutil.copyfile(bundled_token, writable_token)
        except OSError:
            writable_token = bundled_token
    od.TOKEN_FILE = writable_token

    # Seed the photo pool on startup if not already seeded
    pool_dir = od.photo_pool_dir()
    if os.path.isdir(od.ATTACHMENTS_DIR):
        try:
            od.seed_photo_pool(pool_dir, od.ATTACHMENTS_DIR)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Palette + template metadata
# ---------------------------------------------------------------------------
NAVY = "#0d1b3e"
BLUE = "#1e7ac8"
BLUE_DARK = "#155a97"
BG = "#f4f6fb"
CARD = "#ffffff"
TEXT = "#1c2530"
MUTED = "#6b7688"
GREEN = "#127a1f"
RED = "#b00020"
BORDER = "#d9dee8"
HIGHLIGHT = "#eef3fb"

TEMPLATE_INFO = {
    "Elementary": "Intro outreach to an elementary school — invites a robot demo (attaches 2 photos from pool).",
    "Middle": "Intro outreach to a middle school — invites a robot demo (attaches 2 photos from pool).",
    "Response": "Reply confirming attendance at an event (no photos attached).",
    "Post-Demo": "Thank-you follow-up after a demo (no photos attached).",
}
TEMPLATE_TYPES = ["Elementary", "Middle", "Response", "Post-Demo"]


class OutreachApp:
    """The modern v1.1.0 CircuitRunners Outreach desktop application."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.settings = od.load_settings()

        # State for bulk runner
        self.bulk_rows: list[dict] = []
        self.bulk_cancel = threading.Event()
        self.bulk_running = False

        self._init_style()

        if os.path.exists(od.CREDENTIALS_FILE):
            self._build_main_ui()
        else:
            self._build_setup()

    def _clear_root(self) -> None:
        for widget in self.root.winfo_children():
            widget.destroy()

    def _init_style(self) -> None:
        self.root.configure(bg=BG)
        # Apply remembered window size if present
        win_size = self.settings.get("window_size", "760x740")
        try:
            self.root.geometry(win_size)
        except Exception:
            self.root.geometry("760x740")
        self.root.minsize(720, 680)

        base = tkfont.nametofont("TkDefaultFont")
        family = base.actual("family")
        self.f_title = tkfont.Font(family=family, size=20, weight="bold")
        self.f_sub = tkfont.Font(family=family, size=11)
        self.f_tab = tkfont.Font(family=family, size=11, weight="bold")
        self.f_label = tkfont.Font(family=family, size=11, weight="bold")
        self.f_body = tkfont.Font(family=family, size=11)
        self.f_small = tkfont.Font(family=family, size=10)
        self.f_mono = tkfont.Font(family="Courier", size=10)
        self.f_btn = tkfont.Font(family=family, size=12, weight="bold")

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background="#dde3ed", foreground=TEXT,
                        padding=[16, 8], font=self.f_tab)
        style.map("TNotebook.Tab",
                  background=[("selected", CARD)],
                  foreground=[("selected", BLUE_DARK)])

        style.configure("Card.TFrame", background=CARD)
        style.configure("Bg.TFrame", background=BG)
        style.configure("Treeview", font=self.f_body, rowheight=26, background="#ffffff")
        style.configure("Treeview.Heading", font=self.f_label, padding=[6, 4])
        style.configure("TProgressbar", thickness=14, troughcolor="#e2e7ef", background=BLUE)
        style.configure("TCombobox", fieldbackground="#ffffff", padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", "#ffffff")])

    def _make_header(self, title: str, subtitle: str) -> tk.Frame:
        header = tk.Frame(self.root, bg=NAVY)
        header.pack(fill="x")
        inner = tk.Frame(header, bg=NAVY)
        inner.pack(fill="x", padx=24, pady=14)
        tk.Label(inner, text=title, bg=NAVY, fg="white", font=self.f_title).pack(anchor="w")
        tk.Label(inner, text=subtitle, bg=NAVY, fg="#c7d6ea", font=self.f_sub).pack(anchor="w", pady=(3, 0))
        return header

    def _make_button(self, parent, text, command, *, bg=BLUE, fg="white", height=1, compact=False):
        button = tk.Button(
            parent,
            text=text,
            font=self.f_btn if not compact else self.f_body,
            fg=fg,
            bg=bg,
            activebackground=BLUE_DARK if bg == BLUE else "#d7dde8",
            activeforeground="white" if fg == "white" else TEXT,
            relief="flat",
            bd=0,
            cursor="hand2",
            height=height,
            command=command,
        )
        self._hover(button, bg, BLUE_DARK if bg == BLUE else "#d7dde8")
        return button

    def _hover(self, widget, normal, hot):
        widget.bind("<Enter>", lambda event: widget.config(bg=hot))
        widget.bind("<Leave>", lambda event: widget.config(bg=normal))

    # -----------------------------------------------------------------------
    # Setup Screen (shown when credentials.json is missing)
    # -----------------------------------------------------------------------
    def _build_setup(self) -> None:
        self._clear_root()
        self.root.configure(bg=BG)
        self._make_header(f"{APP_NAME} v{od.__version__}", "First-time setup")

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=20)
        card = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True)

        steps = (
            "This app creates Gmail drafts (it never sends). To use it with your "
            "own Gmail account, you need a Google OAuth client file named credentials.json.\n\n"
            "How to get it (one-time setup):\n"
            "  1. Go to console.cloud.google.com and create a project.\n"
            "  2. Enable the Gmail API for that project.\n"
            "  3. Configure the OAuth consent screen (add your email as a Test user).\n"
            "  4. Create an OAuth client ID of type \"Desktop app\".\n"
            "  5. Download it and click the button below to select that file.\n\n"
            "Your credentials stay on this computer. The app requests only the "
            "draft-creation scope (gmail.compose) — it cannot send email."
        )
        tk.Label(
            card,
            text=steps,
            bg=CARD,
            fg=TEXT,
            font=self.f_body,
            justify="left",
            wraplength=600,
        ).pack(anchor="w", padx=24, pady=(20, 14))

        self.setup_status = tk.Label(
            card,
            text="",
            bg=CARD,
            fg=MUTED,
            font=self.f_small,
            wraplength=600,
            justify="left",
        )
        self.setup_status.pack(anchor="w", padx=24, pady=(0, 10))

        btn = self._make_button(card, "Choose credentials.json…", self._pick_credentials)
        btn.pack(fill="x", padx=24, pady=(4, 20))

    def _pick_credentials(self) -> None:
        path = filedialog.askopenfilename(
            title="Select your Google credentials.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return

        import json
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            if not data:
                raise ValueError("empty credentials file")
            key = next(iter(data))
            if key not in ("installed", "web") or "client_id" not in data[key]:
                raise ValueError("not an OAuth client file")
        except Exception:
            self.setup_status.config(
                text="That file doesn't look like a valid Google OAuth client (credentials.json).",
                fg=RED,
            )
            return

        dest = os.path.join(_writable_base(), "credentials.json")
        try:
            shutil.copyfile(path, dest)
        except OSError as exc:
            self.setup_status.config(text=f"Could not save the file: {exc}", fg=RED)
            return

        od.CREDENTIALS_FILE = dest
        self._build_main_ui()

    # -----------------------------------------------------------------------
    # Main Application UI with Tabs
    # -----------------------------------------------------------------------
    def _build_main_ui(self) -> None:
        self._clear_root()
        self.root.configure(bg=BG)

        header = self._make_header(
            f"{APP_NAME} v{od.__version__}",
            "Personalized school outreach drafts for CircuitRunners Robotics · Drafts only, never sends.",
        )

        # Tabbed Notebook container
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=20, pady=(14, 8))

        # Build each tab
        self.tab_single = tk.Frame(self.notebook, bg=CARD)
        self.tab_bulk = tk.Frame(self.notebook, bg=CARD)
        self.tab_photos = tk.Frame(self.notebook, bg=CARD)
        self.tab_settings = tk.Frame(self.notebook, bg=CARD)

        self.notebook.add(self.tab_single, text="  Single Draft  ")
        self.notebook.add(self.tab_bulk, text="  Bulk CSV Runner  ")
        self.notebook.add(self.tab_photos, text="  Photo Pool  ")
        self.notebook.add(self.tab_settings, text="  Settings & Account  ")

        self._build_single_tab()
        self._build_bulk_tab()
        self._build_photos_tab()
        self._build_settings_tab()

        # Shared Footer
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", padx=24, pady=(2, 10))
        cc_text = "Every draft CC's team coordinators: " + ", ".join(od.CC_RECIPIENTS)
        tk.Label(footer, text=cc_text, bg=BG, fg=MUTED, font=self.f_small).pack(anchor="w")

    # -----------------------------------------------------------------------
    # Tab 1: Single Draft Form
    # -----------------------------------------------------------------------
    def _build_single_tab(self) -> None:
        parent = self.tab_single
        canvas = tk.Canvas(parent, bg=CARD, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=CARD)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=(16, 0), pady=12)
        scrollbar.pack(side="right", fill="y", pady=12)

        # Variables initialized from settings
        default_sender = self.settings.get("sender_name", "")
        default_template = self.settings.get("last_template", "Elementary")
        if default_template not in TEMPLATE_TYPES:
            default_template = "Elementary"

        self.v_email = tk.StringVar()
        self.v_rname = tk.StringVar()
        self.v_sname = tk.StringVar(value=default_sender)
        self.v_school = tk.StringVar()
        self.v_type = tk.StringVar(value=default_template)
        self.v_skip_dup = tk.BooleanVar(value=True)

        row = 0
        self.e_email = self._field(scrollable_frame, row, "Recipient email", self.v_email, "principal@school.org")
        row += 2
        self.lbl_email_hint = tk.Label(scrollable_frame, text="", bg=CARD, fg=RED, font=self.f_small)
        self.lbl_email_hint.grid(row=row, column=0, sticky="w", padx=20, pady=(0, 4))
        row += 1

        self.e_rname = self._field(scrollable_frame, row, "Recipient name", self.v_rname, "e.g. Ms. Rivera")
        row += 2
        self.e_sname = self._field(scrollable_frame, row, "Your name (sender)", self.v_sname, "e.g. Aarav Marfatia")
        row += 2
        self.e_school = self._field(scrollable_frame, row, "School / Event name", self.v_school, "e.g. Sunrise Elementary School")
        row += 2

        tk.Label(scrollable_frame, text="Email type", bg=CARD, fg=TEXT, font=self.f_label).grid(
            row=row, column=0, sticky="w", padx=20, pady=(8, 2)
        )
        row += 1

        combo = ttk.Combobox(
            scrollable_frame,
            textvariable=self.v_type,
            values=TEMPLATE_TYPES,
            state="readonly",
            font=self.f_body,
        )
        combo.grid(row=row, column=0, sticky="ew", padx=20)
        row += 1

        # Duplicate Guard Checkbox
        chk_dup = tk.Checkbutton(
            scrollable_frame,
            text="Skip creating draft if an identical draft already exists (Duplicate Guard)",
            variable=self.v_skip_dup,
            bg=CARD,
            fg=TEXT,
            activebackground=CARD,
            font=self.f_small,
        )
        chk_dup.grid(row=row, column=0, sticky="w", padx=20, pady=(8, 4))
        row += 1

        # Live trace for preview & validation
        for var in (self.v_email, self.v_rname, self.v_sname, self.v_school, self.v_type):
            var.trace_add("write", lambda *_: self._refresh_single_preview())

        # Preview Frame
        preview = tk.Frame(scrollable_frame, bg=HIGHLIGHT, highlightbackground=BORDER, highlightthickness=1)
        preview.grid(row=row, column=0, sticky="ew", padx=20, pady=(12, 6))
        preview.columnconfigure(0, weight=1)

        tk.Label(preview, text="LIVE DRAFT PREVIEW", bg=HIGHLIGHT, fg=BLUE_DARK, font=self.f_small).grid(
            row=0, column=0, sticky="w", padx=12, pady=(8, 0)
        )
        self.lbl_desc = tk.Label(preview, text="", bg=HIGHLIGHT, fg=TEXT, font=self.f_small, wraplength=580, justify="left")
        self.lbl_desc.grid(row=1, column=0, sticky="w", padx=12, pady=(2, 0))
        self.lbl_subject = tk.Label(preview, text="", bg=HIGHLIGHT, fg=TEXT, font=self.f_body, wraplength=580, justify="left")
        self.lbl_subject.grid(row=2, column=0, sticky="w", padx=12, pady=(6, 0))
        self.lbl_attach = tk.Label(preview, text="", bg=HIGHLIGHT, fg=MUTED, font=self.f_small, wraplength=580, justify="left")
        self.lbl_attach.grid(row=3, column=0, sticky="w", padx=12, pady=(4, 0))
        self.lbl_cc = tk.Label(preview, text="", bg=HIGHLIGHT, fg=MUTED, font=self.f_small, wraplength=580, justify="left")
        self.lbl_cc.grid(row=4, column=0, sticky="w", padx=12, pady=(2, 10))
        row += 1

        # Action Buttons
        actions = tk.Frame(scrollable_frame, bg=CARD)
        actions.grid(row=row, column=0, sticky="ew", padx=20, pady=(10, 6))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=0)

        self.btn_create = self._make_button(actions, "Create Draft", self._on_single_create)
        self.btn_create.grid(row=0, column=0, sticky="ew", ipady=3)
        self.btn_clear = self._make_button(
            actions, "Clear", self._on_single_clear, bg="#e7ebf2", fg=TEXT, compact=True
        )
        self.btn_clear.grid(row=0, column=1, sticky="e", padx=(10, 0), ipadx=14, ipady=8)
        row += 1

        self.single_status = tk.Label(scrollable_frame, text="", bg=CARD, fg=MUTED, font=self.f_small, wraplength=600, justify="left")
        self.single_status.grid(row=row, column=0, sticky="w", padx=20, pady=(2, 16))

        scrollable_frame.columnconfigure(0, weight=1)
        self._refresh_single_preview()

    def _field(self, parent, row, label, var, hint):
        tk.Label(parent, text=label, bg=CARD, fg=TEXT, font=self.f_label).grid(
            row=row, column=0, sticky="w", padx=20, pady=(8, 2)
        )
        entry = tk.Entry(
            parent,
            textvariable=var,
            font=self.f_body,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BLUE,
            bg="#ffffff",
        )
        entry.grid(row=row + 1, column=0, sticky="ew", padx=20, ipady=6)
        return entry

    def _refresh_single_preview(self, *_args):
        if not hasattr(self, "lbl_desc"):
            return

        email = self.v_email.get().strip()
        if email and not od.is_valid_email(email):
            self.lbl_email_hint.config(text="⚠ Please enter a valid email address (e.g. name@domain.com)")
        else:
            self.lbl_email_hint.config(text="")

        template_type = self.v_type.get().strip()
        self.lbl_desc.config(text=TEMPLATE_INFO.get(template_type, ""))

        template = od.TEMPLATES.get(template_type)
        if template:
            preview_row = {
                "Recipient_Name": self.v_rname.get().strip() or "{Recipient_Name}",
                "Sender_Name": self.v_sname.get().strip() or "{Sender_Name}",
                "School_Name": self.v_school.get().strip() or "{School_Name}",
            }
            subject = od.render_template(template["subject"], preview_row)
            self.lbl_subject.config(text=f"Subject:  {subject}")
            if template_type in ("Elementary", "Middle"):
                pool_photos = od.list_pool_photos(od.photo_pool_dir())
                photo_count = len(pool_photos)
                self.lbl_attach.config(
                    text=f"Attaches 2 random demo photos from the photo pool ({photo_count} photos available)."
                )
            else:
                self.lbl_attach.config(text="No photo attachments for this template type.")
        self.lbl_cc.config(text="CC: " + ", ".join(od.CC_RECIPIENTS))

    def _on_single_clear(self):
        for var in (self.v_email, self.v_rname, self.v_school):
            var.set("")
        self.single_status.config(text="")
        self.lbl_email_hint.config(text="")
        self.e_email.focus_set()

    def _on_single_create(self):
        row = {
            "Recipient_Email": self.v_email.get().strip(),
            "Recipient_Name": self.v_rname.get().strip(),
            "Sender_Name": self.v_sname.get().strip(),
            "School_Name": self.v_school.get().strip(),
            "Template_Type": self.v_type.get().strip(),
        }
        missing = [key for key in od.REQUIRED_FIELDS if not row.get(key)]
        if missing:
            names = ", ".join(k.replace("_", " ").lower() for k in missing)
            self.single_status.config(text=f"Please fill in: {names}.", fg=RED)
            return

        if not od.is_valid_email(row["Recipient_Email"]):
            self.single_status.config(text="Recipient email format is invalid.", fg=RED)
            return

        # Auto-save sender name and last template to settings
        self.settings["sender_name"] = row["Sender_Name"]
        self.settings["last_template"] = row["Template_Type"]
        od.save_settings(self.settings)

        self.btn_create.config(state="disabled", text="Creating Draft…")
        self.btn_clear.config(state="disabled")
        self.single_status.config(text="Contacting Gmail and building draft…", fg=MUTED)

        skip_dup = self.v_skip_dup.get()

        def _worker():
            try:
                creds = od.get_credentials()
                service = od.build_service(creds)
                sender = od.get_sender_address(service)
                template = od.TEMPLATES[row["Template_Type"]]
                subject = od.render_template(template["subject"], row)
                body = od.render_template(template["body"], row)

                # Resolve attachments using the photo pool policy
                paths = od.attachments_for(row)

                message = od.create_message_with_attachments(
                    sender, row["Recipient_Email"], subject, body, paths, od.CC_RECIPIENTS
                )

                if skip_dup and od.find_duplicate_draft(service, row["Recipient_Email"], subject):
                    self.q.put(("single_result", "skipped", "Draft already exists in Gmail Drafts (Duplicate Guard)."))
                    return

                od.create_draft_with_retry(service, message)
                self.q.put(("single_result", "ok", f"Draft created for {row['School_Name']} ({row['Recipient_Email']})."))
            except Exception as exc:
                self.q.put(("single_result", "error", str(exc)))

        threading.Thread(target=_worker, daemon=True).start()
        self.root.after(100, self._poll_queue)

    # -----------------------------------------------------------------------
    # Tab 2: Bulk CSV Runner
    # -----------------------------------------------------------------------
    def _build_bulk_tab(self) -> None:
        parent = self.tab_bulk
        container = tk.Frame(parent, bg=CARD)
        container.pack(fill="both", expand=True, padx=20, pady=16)

        # File picker section
        file_frame = tk.Frame(container, bg=CARD)
        file_frame.pack(fill="x", pady=(0, 10))

        tk.Label(file_frame, text="Contacts CSV:", bg=CARD, fg=TEXT, font=self.f_label).pack(side="left")
        self.v_csv_path = tk.StringVar()
        default_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contacts.csv")
        if os.path.exists(default_csv):
            self.v_csv_path.set(default_csv)

        self.e_csv = tk.Entry(file_frame, textvariable=self.v_csv_path, font=self.f_body,
                              relief="flat", highlightthickness=1, highlightbackground=BORDER)
        self.e_csv.pack(side="left", fill="x", expand=True, padx=10, ipady=4)

        btn_browse = self._make_button(file_frame, "Browse…", self._on_browse_csv,
                                       bg="#e7ebf2", fg=TEXT, compact=True)
        btn_browse.pack(side="left", padx=(0, 6), ipadx=8, ipady=4)

        btn_load = self._make_button(file_frame, "Load CSV", self._on_load_csv,
                                     bg=BLUE, fg="white", compact=True)
        btn_load.pack(side="left", ipadx=8, ipady=4)

        # Options + Stats bar
        options_bar = tk.Frame(container, bg=CARD)
        options_bar.pack(fill="x", pady=(0, 8))

        self.v_bulk_skip_dup = tk.BooleanVar(value=True)
        chk_bulk_dup = tk.Checkbutton(
            options_bar,
            text="Skip duplicates (checks existing drafts in Gmail)",
            variable=self.v_bulk_skip_dup,
            bg=CARD,
            fg=TEXT,
            font=self.f_small,
        )
        chk_bulk_dup.pack(side="left")

        self.lbl_bulk_counts = tk.Label(options_bar, text="No contacts loaded.", bg=CARD, fg=MUTED, font=self.f_small)
        self.lbl_bulk_counts.pack(side="right")

        # Table showing rows
        table_frame = tk.Frame(container, bg=CARD)
        table_frame.pack(fill="both", expand=True, pady=(0, 10))

        columns = ("row", "email", "name", "school", "type", "status")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=10)
        self.tree.heading("row", text="#")
        self.tree.heading("email", text="Recipient Email")
        self.tree.heading("name", text="Recipient Name")
        self.tree.heading("school", text="School / Event")
        self.tree.heading("type", text="Type")
        self.tree.heading("status", text="Draft Status")

        self.tree.column("row", width=40, anchor="center")
        self.tree.column("email", width=190)
        self.tree.column("name", width=130)
        self.tree.column("school", width=180)
        self.tree.column("type", width=90, anchor="center")
        self.tree.column("status", width=140)

        # Tag colors
        self.tree.tag_configure("ok", foreground=GREEN)
        self.tree.tag_configure("skipped", foreground="#b87a00")
        self.tree.tag_configure("failed", foreground=RED)
        self.tree.tag_configure("pending", foreground=MUTED)

        tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        # Progress bar
        self.progress_bar = ttk.Progressbar(container, mode="determinate")
        self.progress_bar.pack(fill="x", pady=(0, 6))

        # Action bar
        act_frame = tk.Frame(container, bg=CARD)
        act_frame.pack(fill="x")

        self.btn_bulk_start = self._make_button(act_frame, "Start Bulk Draft Creation", self._on_bulk_start)
        self.btn_bulk_start.pack(side="left", fill="x", expand=True, ipady=3)

        self.btn_bulk_stop = self._make_button(
            act_frame, "Stop", self._on_bulk_stop, bg="#e7ebf2", fg=TEXT, compact=True
        )
        self.btn_bulk_stop.pack(side="left", padx=(10, 0), ipadx=16, ipady=6)
        self.btn_bulk_stop.config(state="disabled")

        self.lbl_bulk_status = tk.Label(container, text="", bg=CARD, fg=MUTED, font=self.f_small)
        self.lbl_bulk_status.pack(anchor="w", pady=(6, 0))

        # Auto-load default contacts.csv if present
        if os.path.exists(default_csv):
            self._on_load_csv()

    def _on_browse_csv(self):
        path = filedialog.askopenfilename(
            title="Select Contacts CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.v_csv_path.set(path)
            self._on_load_csv()

    def _on_load_csv(self):
        path = self.v_csv_path.get().strip()
        if not path or not os.path.exists(path):
            self.lbl_bulk_counts.config(text="File does not exist.", fg=RED)
            return

        try:
            self.bulk_rows = od.read_contacts(path)
        except Exception as exc:
            self.lbl_bulk_counts.config(text=f"Failed to read CSV: {exc}", fg=RED)
            return

        for item in self.tree.get_children():
            self.tree.delete(item)

        valid_count = 0
        for i, row in enumerate(self.bulk_rows, start=1):
            err = od.validate_row(row, i)
            status_text = "Pending" if err is None else f"Invalid ({err})"
            tag = "pending" if err is None else "failed"
            if err is None:
                valid_count += 1
            self.tree.insert("", "end", iid=str(i), values=(
                i,
                row.get("Recipient_Email", ""),
                row.get("Recipient_Name", ""),
                row.get("School_Name", ""),
                row.get("Template_Type", ""),
                status_text,
            ), tags=(tag,))

        total = len(self.bulk_rows)
        self.lbl_bulk_counts.config(
            text=f"Loaded {total} contacts ({valid_count} ready, {total - valid_count} invalid).",
            fg=TEXT if valid_count > 0 else RED,
        )
        self.lbl_bulk_status.config(text="Ready to run.", fg=MUTED)

    def _on_bulk_start(self):
        if not self.bulk_rows:
            messagebox.showwarning("No Contacts", "Please load a valid contacts CSV first.")
            return

        self.bulk_running = True
        self.bulk_cancel.clear()
        self.btn_bulk_start.config(state="disabled", text="Processing Drafts…")
        self.btn_bulk_stop.config(state="normal")
        self.progress_bar["maximum"] = len(self.bulk_rows)
        self.progress_bar["value"] = 0

        override = not self.v_bulk_skip_dup.get()

        def _worker():
            try:
                creds = od.get_credentials()
                service = od.build_service(creds)
                sender = od.get_sender_address(service)

                success_cnt = 0
                skip_cnt = 0
                fail_cnt = 0

                for i, row in enumerate(self.bulk_rows, start=1):
                    if self.bulk_cancel.is_set():
                        self.q.put(("bulk_done", "Cancelled by user.", success_cnt, skip_cnt, fail_cnt))
                        return

                    res = od.process_contact_row(
                        row,
                        i,
                        service=service,
                        sender=sender,
                        override=override,
                        attachments_for=od.attachments_for,
                    )

                    if res.outcome == "success":
                        success_cnt += 1
                    elif res.outcome == "skipped":
                        skip_cnt += 1
                    else:
                        fail_cnt += 1

                    self.q.put(("bulk_row", i, res))
                    import time
                    time.sleep(od.RATE_LIMIT_SECONDS)

                self.q.put(("bulk_done", "Completed successfully.", success_cnt, skip_cnt, fail_cnt))
            except Exception as exc:
                self.q.put(("bulk_error", str(exc)))

        threading.Thread(target=_worker, daemon=True).start()
        self.root.after(100, self._poll_queue)

    def _on_bulk_stop(self):
        if self.bulk_running:
            self.bulk_cancel.set()
            self.lbl_bulk_status.config(text="Stopping batch after current row…", fg=RED)

    # -----------------------------------------------------------------------
    # Tab 3: Photo Pool Manager
    # -----------------------------------------------------------------------
    def _build_photos_tab(self) -> None:
        parent = self.tab_photos
        container = tk.Frame(parent, bg=CARD)
        container.pack(fill="both", expand=True, padx=20, pady=16)

        info_text = (
            "The Photo Pool stores robot demo pictures for school outreach.\n"
            "Elementary and Middle school drafts automatically pick 2 distinct random "
            "photos from this pool on each run."
        )
        tk.Label(container, text=info_text, bg=CARD, fg=TEXT, font=self.f_body, justify="left").pack(anchor="w", pady=(0, 10))

        # Pool location display
        pool_dir = od.photo_pool_dir()
        loc_frame = tk.Frame(container, bg=CARD)
        loc_frame.pack(fill="x", pady=(0, 10))
        tk.Label(loc_frame, text="Storage folder:", bg=CARD, fg=MUTED, font=self.f_small).pack(side="left")
        tk.Label(loc_frame, text=pool_dir, bg=CARD, fg=TEXT, font=self.f_mono).pack(side="left", padx=8)

        # Photo list
        list_frame = tk.Frame(container, bg=CARD)
        list_frame.pack(fill="both", expand=True, pady=(0, 10))

        self.photo_listbox = tk.Listbox(
            list_frame, font=self.f_body, selectmode="single",
            highlightthickness=1, highlightbackground=BORDER, relief="flat",
        )
        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.photo_listbox.yview)
        self.photo_listbox.configure(yscrollcommand=list_scroll.set)

        self.photo_listbox.pack(side="left", fill="both", expand=True)
        list_scroll.pack(side="right", fill="y")

        # Action bar
        act_frame = tk.Frame(container, bg=CARD)
        act_frame.pack(fill="x")

        btn_add = self._make_button(act_frame, "Add Photos…", self._on_add_photos, bg=BLUE)
        btn_add.pack(side="left", padx=(0, 8), ipadx=10, ipady=3)

        btn_remove = self._make_button(
            act_frame, "Remove Selected", self._on_remove_photo, bg="#e7ebf2", fg=TEXT, compact=True
        )
        btn_remove.pack(side="left", padx=(0, 8), ipadx=10, ipady=5)

        btn_seed = self._make_button(
            act_frame, "Restore Default Photos", self._on_seed_defaults, bg="#e7ebf2", fg=TEXT, compact=True
        )
        btn_seed.pack(side="left", ipadx=10, ipady=5)

        self.lbl_photo_status = tk.Label(container, text="", bg=CARD, fg=MUTED, font=self.f_small)
        self.lbl_photo_status.pack(anchor="w", pady=(8, 0))

        self._refresh_photo_list()

    def _refresh_photo_list(self):
        self.photo_listbox.delete(0, tk.END)
        pool = od.list_pool_photos(od.photo_pool_dir())
        for path in pool:
            size_kb = os.path.getsize(path) / 1024
            name = os.path.basename(path)
            self.photo_listbox.insert(tk.END, f"{name}  ({size_kb:.1f} KB)")
        self.lbl_photo_status.config(
            text=f"{len(pool)} photo(s) currently in the pool.",
            fg=GREEN if len(pool) >= 2 else RED,
        )

    def _on_add_photos(self):
        paths = filedialog.askopenfilenames(
            title="Select demo photos to add to pool",
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.gif *.bmp"), ("All files", "*.*")],
        )
        if paths:
            od.add_pool_photos(od.photo_pool_dir(), paths)
            self._refresh_photo_list()
            self._refresh_single_preview()

    def _on_remove_photo(self):
        sel = self.photo_listbox.curselection()
        if not sel:
            return
        item_text = self.photo_listbox.get(sel[0])
        name = item_text.split("  ")[0]
        od.remove_pool_photo(od.photo_pool_dir(), name)
        self._refresh_photo_list()
        self._refresh_single_preview()

    def _on_seed_defaults(self):
        od.seed_photo_pool(od.photo_pool_dir(), od.ATTACHMENTS_DIR)
        self._refresh_photo_list()
        self._refresh_single_preview()

    # -----------------------------------------------------------------------
    # Tab 4: Settings & Account
    # -----------------------------------------------------------------------
    def _build_settings_tab(self) -> None:
        parent = self.tab_settings
        container = tk.Frame(parent, bg=CARD)
        container.pack(fill="both", expand=True, padx=20, pady=16)

        # Group 1: User Preferences
        lbl_p = tk.Label(container, text="Outreach Preferences", bg=CARD, fg=BLUE_DARK, font=self.f_label)
        lbl_p.pack(anchor="w", pady=(0, 6))

        pref_frame = tk.Frame(container, bg=HIGHLIGHT, highlightbackground=BORDER, highlightthickness=1)
        pref_frame.pack(fill="x", pady=(0, 16), padx=2, ipadx=10, ipady=10)

        tk.Label(pref_frame, text="Default Sender Name:", bg=HIGHLIGHT, fg=TEXT, font=self.f_small).grid(
            row=0, column=0, sticky="w", padx=10, pady=4
        )
        self.v_pref_sender = tk.StringVar(value=self.settings.get("sender_name", ""))
        e_pref_s = tk.Entry(pref_frame, textvariable=self.v_pref_sender, font=self.f_body,
                            relief="flat", highlightthickness=1, highlightbackground=BORDER)
        e_pref_s.grid(row=0, column=1, sticky="ew", padx=10, pady=4, ipady=3)

        tk.Label(pref_frame, text="Default Email Type:", bg=HIGHLIGHT, fg=TEXT, font=self.f_small).grid(
            row=1, column=0, sticky="w", padx=10, pady=4
        )
        self.v_pref_type = tk.StringVar(value=self.settings.get("last_template", "Elementary"))
        c_pref_t = ttk.Combobox(pref_frame, textvariable=self.v_pref_type, values=TEMPLATE_TYPES, state="readonly")
        c_pref_t.grid(row=1, column=1, sticky="w", padx=10, pady=4)

        btn_save_pref = self._make_button(
            pref_frame, "Save Preferences", self._on_save_preferences, bg=BLUE, fg="white", compact=True
        )
        btn_save_pref.grid(row=2, column=1, sticky="e", padx=10, pady=(6, 2), ipadx=10, ipady=4)
        pref_frame.columnconfigure(1, weight=1)

        # Group 2: Google Account Connection
        lbl_c = tk.Label(container, text="Google Account Connection", bg=CARD, fg=BLUE_DARK, font=self.f_label)
        lbl_c.pack(anchor="w", pady=(0, 6))

        conn_frame = tk.Frame(container, bg=HIGHLIGHT, highlightbackground=BORDER, highlightthickness=1)
        conn_frame.pack(fill="x", pady=(0, 16), padx=2, ipadx=10, ipady=10)

        self.lbl_conn_status = tk.Label(
            conn_frame, text="Click \"Test Connection\" to verify Gmail API access.",
            bg=HIGHLIGHT, fg=MUTED, font=self.f_small, justify="left"
        )
        self.lbl_conn_status.pack(anchor="w", padx=10, pady=(4, 8))

        conn_btn_row = tk.Frame(conn_frame, bg=HIGHLIGHT)
        conn_btn_row.pack(fill="x", padx=10)

        self.btn_test_conn = self._make_button(
            conn_btn_row, "Test Connection", self._on_test_connection, bg=BLUE, fg="white", compact=True
        )
        self.btn_test_conn.pack(side="left", padx=(0, 8), ipadx=10, ipady=4)

        btn_reauth = self._make_button(
            conn_btn_row, "Re-authenticate Account…", self._on_reauth, bg="#e7ebf2", fg=TEXT, compact=True
        )
        btn_reauth.pack(side="left", ipadx=10, ipady=4)

        # Group 3: About & Assurances
        lbl_a = tk.Label(container, text="About & Privacy", bg=CARD, fg=BLUE_DARK, font=self.f_label)
        lbl_a.pack(anchor="w", pady=(0, 6))

        about_frame = tk.Frame(container, bg=CARD)
        about_frame.pack(fill="x", padx=2)

        about_text = (
            f"CircuitRunners Outreach Version {od.__version__}\n"
            "Wheeler High School Robotics Team\n\n"
            "• Drafts only: Requests only gmail.compose scope. Cannot send email.\n"
            "• CC Policy: Automatically includes team coordinators on all drafts.\n"
            "• Local Data: Your credentials and tokens are stored securely on your computer."
        )
        tk.Label(about_frame, text=about_text, bg=CARD, fg=MUTED, font=self.f_small, justify="left").pack(anchor="w")

    def _on_save_preferences(self):
        self.settings["sender_name"] = self.v_pref_sender.get().strip()
        self.settings["last_template"] = self.v_pref_type.get().strip()
        od.save_settings(self.settings)
        # Update single form variable
        self.v_sname.set(self.settings["sender_name"])
        self.v_type.set(self.settings["last_template"])
        messagebox.showinfo("Preferences Saved", "Your outreach preferences have been saved.")

    def _on_test_connection(self):
        self.btn_test_conn.config(state="disabled", text="Testing…")
        self.lbl_conn_status.config(text="Connecting to Gmail API…", fg=MUTED)

        def _worker():
            try:
                creds = od.get_credentials()
                service = od.build_service(creds)
                email = od.get_sender_address(service)
                self.q.put(("conn_result", True, f"✓ Successfully connected as: {email}"))
            except Exception as exc:
                self.q.put(("conn_result", False, f"✕ Connection failed: {exc}"))

        threading.Thread(target=_worker, daemon=True).start()
        self.root.after(100, self._poll_queue)

    def _on_reauth(self):
        if messagebox.askyesno("Re-authenticate", "Clear saved login token and re-authorize with Google?"):
            if os.path.exists(od.TOKEN_FILE):
                try:
                    os.remove(od.TOKEN_FILE)
                except OSError:
                    pass
            self._on_test_connection()

    # -----------------------------------------------------------------------
    # Background Thread Queue Polling
    # -----------------------------------------------------------------------
    def _poll_queue(self):
        try:
            while True:
                msg = self.q.get_nowait()
                mtype = msg[0]

                if mtype == "single_result":
                    _, outcome, text = msg
                    self.btn_create.config(state="normal", text="Create Draft")
                    self.btn_clear.config(state="normal")
                    if outcome == "ok":
                        self.single_status.config(text=f"✓ {text} Check Gmail Drafts.", fg=GREEN)
                    elif outcome == "skipped":
                        self.single_status.config(text=f"ⓘ {text}", fg="#b87a00")
                    else:
                        self.single_status.config(text=f"✕ {text}", fg=RED)

                elif mtype == "bulk_row":
                    _, row_num, res = msg
                    self.progress_bar["value"] = row_num
                    iid = str(row_num)
                    if self.tree.exists(iid):
                        tag = res.outcome
                        status_str = "Created" if res.outcome == "success" else f"{res.outcome.capitalize()}: {res.reason}"
                        vals = list(self.tree.item(iid, "values"))
                        vals[5] = status_str
                        self.tree.item(iid, values=vals, tags=(tag,))
                        self.tree.see(iid)

                elif mtype == "bulk_done":
                    _, summary_text, succ, skip, fail = msg
                    self.bulk_running = False
                    self.btn_bulk_start.config(state="normal", text="Start Bulk Draft Creation")
                    self.btn_bulk_stop.config(state="disabled")
                    self.lbl_bulk_status.config(
                        text=f"{summary_text} Drafts created: {succ} | Skipped: {skip} | Failed: {fail}",
                        fg=GREEN if fail == 0 else RED,
                    )
                    messagebox.showinfo(
                        "Batch Complete",
                        f"{summary_text}\n\nSuccessful drafts: {succ}\nSkipped: {skip}\nFailed: {fail}\n\nReview them in Gmail Drafts.",
                    )

                elif mtype == "bulk_error":
                    _, err_text = msg
                    self.bulk_running = False
                    self.btn_bulk_start.config(state="normal", text="Start Bulk Draft Creation")
                    self.btn_bulk_stop.config(state="disabled")
                    self.lbl_bulk_status.config(text=f"Batch error: {err_text}", fg=RED)
                    messagebox.showerror("Batch Error", f"An error occurred during bulk processing:\n{err_text}")

                elif mtype == "conn_result":
                    _, ok, status_str = msg
                    self.btn_test_conn.config(state="normal", text="Test Connection")
                    self.lbl_conn_status.config(text=status_str, fg=GREEN if ok else RED)

        except queue.Empty:
            if self.bulk_running or self.btn_create["state"] == "disabled":
                self.root.after(100, self._poll_queue)


def main():
    _configure_paths()
    root = tk.Tk()
    root.title(f"{APP_NAME} v{od.__version__}")
    OutreachApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
