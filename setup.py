"""cx_Freeze build script - produces a Windows .msi for CircuitRunners Outreach.

Run on a Windows PC:
    py -3 -m pip install cx_Freeze
    py -3 setup.py bdist_msi
The installer lands in the 'dist' folder.
"""
import sys
from cx_Freeze import setup, Executable

# Bundle the demo photos alongside the frozen app. At runtime gui.py resolves
# them relative to the executable's folder (the sys.frozen branch).
include_files = [("attachments", "attachments")]

build_exe_options = {
    "include_files": include_files,
    "packages": [
        "google", "google_auth_oauthlib", "googleapiclient",
        "google_auth_httplib2", "googleapiclient.discovery", "tkinter",
    ],
    "include_msvcr": True,
}

# GUI app: base "Win32GUI" hides the console window on Windows.
base = "Win32GUI" if sys.platform == "win32" else None

executables = [
    Executable(
        "gui.py",
        base=base,
        target_name="CircuitRunners Outreach.exe",
        icon="AppIcon.ico",
        shortcut_name="CircuitRunners Outreach",
        shortcut_dir="StartMenuFolder",
    )
]

# A stable, fixed upgrade code lets future .msi versions upgrade cleanly
# instead of installing side by side.
bdist_msi_options = {
    "upgrade_code": "{6EE53089-CF97-4B47-AA43-828FE2CA0EA8}",
    "add_to_path": False,
    "all_users": False,
}

setup(
    name="CircuitRunners Outreach",
    version="1.0.0",
    description="Create personalized Gmail drafts (never sends).",
    options={
        "build_exe": build_exe_options,
        "bdist_msi": bdist_msi_options,
    },
    executables=executables,
)
