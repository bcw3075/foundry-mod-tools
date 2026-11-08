#!/usr/bin/env python3
"""Entry point: run from inside a mod repo. See modtools/guide.py for what it does."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from modtools import guide
guide.main()
