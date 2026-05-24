#!/usr/bin/env python3
"""Argos management CLI — thin launcher.

For installed packages, use the ``argos-cli`` console script instead.
"""
from __future__ import annotations

import os
import sys

# Ensure the project root is on sys.path so argos.cli can import argos modules.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from argos.cli import main

if __name__ == "__main__":
    main()
