"""Shared pytest configuration.

Ensures the project root (where ``outreach_drafts.py`` lives) is importable so
tests can ``import outreach_drafts`` regardless of where pytest is invoked from.
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
