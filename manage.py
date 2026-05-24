#!/usr/bin/env python3
"""Hermes Agent Team management CLI — thin launcher.

For installed packages, use the ``hermes-mgmt`` console script instead.
"""
from __future__ import annotations

import os
import sys

# Ensure the project root is on sys.path so app.cli can import app modules.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.cli import main

if __name__ == "__main__":
    main()
