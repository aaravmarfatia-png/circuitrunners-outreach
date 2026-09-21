"""CircuitRunners Outreach — desktop app for creating Gmail drafts.

A friendly tkinter front-end over the tested ``outreach_drafts`` module, meant
for the whole team to use on the shared CircuitRunners Gmail account. You fill
in one contact, pick the email type, and click "Create Draft". The app builds a
personalized Gmail *draft* (it never sends), CC's the team coordinators, and
attaches the demo photos for Elementary/Middle outreach.

Everything the app needs (OAuth credentials, saved login, photos) is bundled
inside the .app, so any teammate can just open it and go.
"""
import os
import sys
import shutil
import threading
import queue
import tkinter as tk
from tkinter import ttk, font as tkfont, filedialog

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
    """Pick the credentials.json to use, in priority order.

    1. A user-provided copy already saved in the writable folder (from a prior
       first-run setup on a shareable build).
    2. A credentials.json bundled next to the app resources (the internal
       CircuitRunners build ships one; the shareable build does not).
    Returns the chosen absolute path (which may not exist yet for a fresh
    shareable install — the GUI then shows first-run setup).
    """
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

    # Seed the writable token from a bundled one (internal build) on first run,
    # then always read/write the writable copy so refreshes persist.
    bundled_token = os.path.join(base, "token.json")
    writable_token = os.path.join(writable, "token.json")
    if not os.path.exists(writable_token) and os.path.exists(bundled_token):
        try:
            shutil.copyfile(bundled_token, writable_token)
        except OSError:
            writable_token = bundled_token
    od.TOKEN_FILE = writable_token


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

# Friendly descriptions shown in the preview for each template type.
TEMPLATE_INFO = {
    "Elementary": "Intro outreach to an elementary school — invites a robot demo.",
    "Middle": "Intro outreach to a middle school — invites a robot demo.",
    "Response": "Reply confirming attendance at an event (no photos attached).",
    "Post-Demo": "Thank-you follow-up after a demo (no photos attached).",
}
TEMPLATE_TYPES = ["Elementary", "Middle", "Response", "Post-Demo"]


class OutreachApp:
    """The polished single-draft window."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: "queue.Queue" = queue.Queue()

        self._init_style()
        # A credential-free (shareable) build shows first-run setup until the
        # team points it at their own credentials.json. The internal build
        # already has one bundled, so it goes straight to the form.
        if os.path.exists(od.CREDENTIALS_FILE):
            self._build()
            self._refresh_preview()
        else:
            self._build_setup()

    # -- first-run setup (shareable, credential-free build) ----------------
    def _build_setup(self) -> None:
        """Show a friendly one-time screen to select the team credentials.json."""
        for w in self.root.winfo_children():
            w.destroy()
        self.root.configure(bg=BG)

        header = tk.Frame(self.root, bg=NAVY)
        header.pack(fill="x")
        inner = tk.Frame(header, bg=NAVY)
        inner.pack(fill="x", padx=24, pady=18)
        tk.Label(inner, text=APP_NAME, bg=NAVY, fg="white",
                 font=self.f_title).pack(anchor="w")
        tk.Label(inner, text="First-time setup", bg=NAVY, fg="#c7d6ea",
                 font=self.f_sub).pack(anchor="w", pady=(4, 0))

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=20)
        card = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True)

        steps = (
            "This app creates Gmail drafts (it never sends). To use it with your "
            "own Gmail account you need a Google OAuth client file named "
            "credentials.json.\n\n"
            "How to get it (one time):\n"
            "  1.  Go to console.cloud.google.com and create a project.\n"
            "  2.  Enable the Gmail API for that project.\n"
            "  3.  Configure the OAuth consent screen (add yourself as a test user).\n"
            "  4.  Create an OAuth client ID of type \u201cDesktop app\u201d.\n"
            "  5.  Download it and click the button below to select that file.\n\n"
            "Your credentials stay on this computer. The app requests only the "
            "draft-creation scope \u2014 it cannot send email."
        )
        tk.Label(card, text=steps, bg=CARD, fg=TEXT, font=self.f_small,
                 justify="left", wraplength=560).pack(anchor="w", padx=22, pady=(18, 12))

        self.setup_status = tk.Label(card, text="", bg=CARD, fg=MUTED,
                                     font=self.f_small, wraplength=560, justify="left")
        self.setup_status.pack(anchor="w", padx=22, pady=(0, 8))

        btn = tk.Button(card, text="Choose credentials.json\u2026", font=self.f_btn,
                        fg="white", bg=BLUE, activebackground=BLUE_DARK,
                        activeforeground="white", relief="flat", bd=0,
                        cursor="hand2", height=2, command=self._pick_credentials)
        btn.pack(fill="x", padx=22, pady=(4, 18))
        self._hover(btn, BLUE, BLUE_DARK)

    def _pick_credentials(self) -> None:
        path = filedialog.askopenfilename(
            title="Select your Google credentials.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        # Validate it looks like an OAuth client file before accepting it.
        try:
            import json
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            key = next(iter(data))
            if key not in ("installed", "web") or "client_id" not in data[key]:
                raise ValueError("not an OAuth client file")
        except Exception:
            self.setup_status.config(
                text="That file doesn't look like a Google OAuth client "
                     "(credentials.json). Please pick the downloaded file.",
                fg=RED)
            return
        # Copy into the writable folder and continue to the main form.
        dest = os.path.join(_writable_base(), "credentials.json")
        try:
            shutil.copyfile(path, dest)
        except OSError as e:
            self.setup_status.config(text=f"Could not save the file: {e}", fg=RED)
            return
        od.CREDENTIALS_FILE = dest
        for w in self.root.winfo_children():
            w.destroy()
        self._build()
        self._refresh_preview()

    # -- styling -----------------------------------------------------------
    def _init_style(self) -> None:
        self.root.configure(bg=BG)
        self.root.minsize(640, 660)

        base = tkfont.nametofont("TkDefaultFont")
        family = base.actual("family")
        self.f_title = tkfont.Font(family=family, size=22, weight="bold")
        self.f_sub = tkfont.Font(family=family, size=12)
        self.f_label = tkfont.Font(family=family, size=12, weight="bold")
        self.f_body = tkfont.Font(family=family, size=12)
        self.f_small = tkfont.Font(family=family, size=11)
        self.f_btn = tkfont.Font(family=family, size=14, weight="bold")

        st = ttk.Style()
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Card.TFrame", background=CARD)
        st.configure("Bg.TFrame", background=BG)
        st.configure("Field.TLabel", background=CARD, foreground=TEXT, font=self.f_label)
        st.configure("Hint.TLabel", background=CARD, foreground=MUTED, font=self.f_small)
        st.configure("TEntry", fieldbackground="#ffffff", bordercolor=BORDER,
                     relief="flat", padding=8)
        st.configure("TCombobox", fieldbackground="#ffffff", padding=6)
        st.map("TCombobox", fieldbackground=[("readonly", "#ffffff")])

    # -- layout ------------------------------------------------------------
    def _build(self) -> None:
        # Header band
        header = tk.Frame(self.root, bg=NAVY)
        header.pack(fill="x")
        inner = tk.Frame(header, bg=NAVY)
        inner.pack(fill="x", padx=24, pady=18)
        tk.Label(inner, text="CircuitRunners Outreach", bg=NAVY, fg="white",
                 font=self.f_title).pack(anchor="w")
        tk.Label(inner,
                 text="Create a personalized Gmail draft. Nothing is ever sent — "
                      "you review every draft in Gmail first.",
                 bg=NAVY, fg="#c7d6ea", font=self.f_sub,
                 wraplength=560, justify="left").pack(anchor="w", pady=(4, 0))

        # Scrollable body not needed at this size; use a padded card.
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=20)

        card = tk.Frame(body, bg=CARD, highlightbackground=BORDER,
                        highlightthickness=1)
        card.pack(fill="both", expand=True)
        card.columnconfigure(0, weight=1)

        pad = {"padx": 22}

        # Variables
        self.v_email = tk.StringVar()
        self.v_rname = tk.StringVar()
        self.v_sname = tk.StringVar()
        self.v_school = tk.StringVar()
        self.v_type = tk.StringVar(value=TEMPLATE_TYPES[0])

        r = 0
        tk.Frame(card, bg=CARD, height=10).grid(row=r, column=0); r += 1

        self.e_email = self._field(card, r, "Recipient email",
                                   self.v_email, "principal@school.org"); r += 2
        self.e_rname = self._field(card, r, "Recipient name",
                                   self.v_rname, "e.g. Ms. Rivera"); r += 2
        self.e_sname = self._field(card, r, "Your name (sender)",
                                   self.v_sname, "e.g. Aarav Marfatia"); r += 2
        self.e_school = self._field(card, r, "School / Event name",
                                    self.v_school, "e.g. Sunrise Elementary School"); r += 2

        # Template type row
        tk.Label(card, text="Email type", bg=CARD, fg=TEXT,
                 font=self.f_label).grid(row=r, column=0, sticky="w", **pad,
                                         pady=(10, 2)); r += 1
        self.combo = ttk.Combobox(card, textvariable=self.v_type,
                                  values=TEMPLATE_TYPES, state="readonly",
                                  font=self.f_body)
        self.combo.grid(row=r, column=0, sticky="ew", **pad); r += 1

        # Now that every entry + combo exists, wire live-preview updates.
        for var in (self.v_email, self.v_rname, self.v_sname, self.v_school,
                    self.v_type):
            var.trace_add("write", lambda *_: self._refresh_preview())


        # Live preview panel
        prev = tk.Frame(card, bg="#eef3fb", highlightbackground=BORDER,
                        highlightthickness=1)
        prev.grid(row=r, column=0, sticky="ew", padx=22, pady=(16, 4)); r += 1
        prev.columnconfigure(0, weight=1)
        tk.Label(prev, text="PREVIEW", bg="#eef3fb", fg=BLUE_DARK,
                 font=self.f_small).grid(row=0, column=0, sticky="w",
                                         padx=12, pady=(8, 0))
        self.lbl_desc = tk.Label(prev, text="", bg="#eef3fb", fg=TEXT,
                                 font=self.f_small, wraplength=520, justify="left")
        self.lbl_desc.grid(row=1, column=0, sticky="w", padx=12, pady=(2, 0))
        self.lbl_subject = tk.Label(prev, text="", bg="#eef3fb", fg=TEXT,
                                    font=self.f_body, wraplength=520, justify="left")
        self.lbl_subject.grid(row=2, column=0, sticky="w", padx=12, pady=(6, 0))
        self.lbl_attach = tk.Label(prev, text="", bg="#eef3fb", fg=MUTED,
                                   font=self.f_small, wraplength=520, justify="left")
        self.lbl_attach.grid(row=3, column=0, sticky="w", padx=12, pady=(4, 0))
        self.lbl_cc = tk.Label(prev, text="", bg="#eef3fb", fg=MUTED,
                               font=self.f_small, wraplength=520, justify="left")
        self.lbl_cc.grid(row=4, column=0, sticky="w", padx=12, pady=(2, 10))

        # Buttons
        btns = tk.Frame(card, bg=CARD)
        btns.grid(row=r, column=0, sticky="ew", padx=22, pady=(14, 6)); r += 1
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=0)

        self.btn_create = tk.Button(
            btns, text="Create Draft", font=self.f_btn, fg="white", bg=BLUE,
            activebackground=BLUE_DARK, activeforeground="white",
            relief="flat", bd=0, cursor="hand2", height=2,
            command=self._on_create)
        self.btn_create.grid(row=0, column=0, sticky="ew", ipady=2)
        self._hover(self.btn_create, BLUE, BLUE_DARK)

        self.btn_clear = tk.Button(
            btns, text="Clear", font=self.f_body, fg=TEXT, bg="#e7ebf2",
            activebackground="#d7dde8", relief="flat", bd=0,
            cursor="hand2", command=self._on_clear)
        self.btn_clear.grid(row=0, column=1, sticky="e", padx=(10, 0), ipadx=14, ipady=10)

        # Status banner
        self.status = tk.Label(card, text="", bg=CARD, fg=MUTED,
                               font=self.f_small, wraplength=560, justify="left")
        self.status.grid(row=r, column=0, sticky="w", padx=22, pady=(2, 14)); r += 1

        # Footer
        footer = tk.Frame(self.root, bg=BG)
        footer.pack(fill="x", padx=24, pady=(0, 14))
        cc_text = "Every draft is CC'd to: " + ", ".join(od.CC_RECIPIENTS)
        tk.Label(footer, text=cc_text, bg=BG, fg=MUTED,
                 font=self.f_small, wraplength=580, justify="left").pack(anchor="w")
        tk.Label(footer, text="Shared CircuitRunners account · drafts only, never sends",
                 bg=BG, fg=MUTED, font=self.f_small).pack(anchor="w")

        # Keyboard: Enter submits, focus first field
        self.root.bind("<Return>", lambda e: self._on_create())
        self.e_email.focus_set()

    def _field(self, parent, row, label, var, hint):
        pad = {"padx": 22}
        tk.Label(parent, text=label, bg=CARD, fg=TEXT,
                 font=self.f_label).grid(row=row, column=0, sticky="w",
                                         **pad, pady=(10, 2))
        entry = tk.Entry(parent, textvariable=var, font=self.f_body,
                         relief="flat", highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=BLUE,
                         bg="#ffffff")
        entry.grid(row=row + 1, column=0, sticky="ew", **pad, ipady=7)
        # Placeholder behavior
        self._placeholder(entry, var, hint)
        return entry

    def _placeholder(self, entry, var, hint):
        def show():
            if not var.get():
                entry.config(fg=MUTED)
                entry._ph = True
                var.set(hint)
        def on_focus_in(_):
            if getattr(entry, "_ph", False):
                var.set("")
                entry.config(fg=TEXT)
                entry._ph = False
        def on_focus_out(_):
            if not var.get():
                show()
        entry._ph = False
        show()
        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)

    def _hover(self, widget, normal, hot):
        widget.bind("<Enter>", lambda e: widget.config(bg=hot))
        widget.bind("<Leave>", lambda e: widget.config(bg=normal))

    # -- helpers -----------------------------------------------------------
    def _clean(self, entry, var):
        """Return the real value, treating an untouched placeholder as empty."""
        if getattr(entry, "_ph", False):
            return ""
        return var.get().strip()

    def _current_row(self):
        # Guard: preview traces may fire before every widget is assigned.
        if not hasattr(self, "e_school"):
            return {
                "Recipient_Email": "", "Recipient_Name": "", "Sender_Name": "",
                "School_Name": "", "Template_Type": self.v_type.get().strip(),
            }
        return {
            "Recipient_Email": self._clean(self.e_email, self.v_email),
            "Recipient_Name": self._clean(self.e_rname, self.v_rname),
            "Sender_Name": self._clean(self.e_sname, self.v_sname),
            "School_Name": self._clean(self.e_school, self.v_school),
            "Template_Type": self.v_type.get().strip(),
        }

    def _refresh_preview(self, *_):
        row = self._current_row()
        ttype = row["Template_Type"]
        info = TEMPLATE_INFO.get(ttype, "")
        self.lbl_desc.config(text=info)

        template = od.TEMPLATES.get(ttype)
        if template:
            # Use placeholders' current (possibly empty) values for a live subject.
            preview_row = {
                "Recipient_Name": row["Recipient_Name"] or "{name}",
                "Sender_Name": row["Sender_Name"] or "{sender}",
                "School_Name": row["School_Name"] or "{school}",
            }
            subject = od.render_template(template["subject"], preview_row)
            self.lbl_subject.config(text=f"Subject:  {subject}")
            atts = template["attachments"]
            if atts:
                self.lbl_attach.config(text=f"Attaches {len(atts)} photo(s): " + ", ".join(atts))
            else:
                self.lbl_attach.config(text="No photo attachments for this type.")
        self.lbl_cc.config(text="CC: " + ", ".join(od.CC_RECIPIENTS))

    def _set_status(self, text, kind="info"):
        color = {"ok": GREEN, "error": RED, "info": MUTED}.get(kind, MUTED)
        self.status.config(text=text, fg=color)

    # -- actions -----------------------------------------------------------
    def _on_clear(self):
        for entry, var in ((self.e_email, self.v_email), (self.e_rname, self.v_rname),
                           (self.e_school, self.v_school)):
            var.set("")
            entry._ph = False
        # keep sender name (team member likely reuses it); reset type
        self._refresh_preview()
        self.e_email.focus_set()
        self._set_status("", "info")

    def _on_create(self):
        row = self._current_row()
        missing = [k for k in od.REQUIRED_FIELDS if not row.get(k)]
        if missing:
            nice = ", ".join(m.replace("_", " ").lower() for m in missing)
            self._set_status(f"Please fill in: {nice}.", "error")
            return
        if row["Template_Type"] not in od.TEMPLATES:
            self._set_status(f"Pick a valid email type.", "error")
            return

        self.btn_create.config(state="disabled", text="Creating…")
        self.btn_clear.config(state="disabled")
        self._set_status("Contacting Gmail and building the draft…", "info")

        threading.Thread(target=self._worker, args=(row,), daemon=True).start()
        self.root.after(100, self._poll)

    def _worker(self, row):
        try:
            creds = od.get_credentials()
            service = od.build_service(creds)
            from_address = od.get_sender_address(service)
            template = od.TEMPLATES[row["Template_Type"]]
            subject = od.render_template(template["subject"], row)
            body = od.render_template(template["body"], row)
            paths = [os.path.join(od.ATTACHMENTS_DIR, n) for n in template["attachments"]]
            message = od.create_message_with_attachments(
                from_address, row["Recipient_Email"], subject, body, paths, od.CC_RECIPIENTS)
            od.create_draft(service, message)
            self.q.put(("ok", row["School_Name"], row["Recipient_Email"]))
        except SystemExit as e:
            self.q.put(("error", "Couldn't sign in to Gmail. Check the app's credentials.", str(e)))
        except FileNotFoundError as e:
            self.q.put(("error", "A demo photo is missing from the app.", str(e)))
        except Exception as e:  # noqa: BLE001
            self.q.put(("error", "Something went wrong creating the draft.", str(e)))

    def _poll(self):
        try:
            kind, a, b = self.q.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll)
            return
        self.btn_create.config(state="normal", text="Create Draft")
        self.btn_clear.config(state="normal")
        if kind == "ok":
            self._set_status(f"✓ Draft created for {a} ({b}). Open Gmail → Drafts to review and send.", "ok")
        else:
            self._set_status(f"✕ {a}", "error")


def main():
    _configure_paths()
    root = tk.Tk()
    root.title("CircuitRunners Outreach")
    OutreachApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
