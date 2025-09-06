#!/usr/bin/env python3
"""Readiness check for Projector Plugin."""

import sys
from pathlib import Path

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "shared"))
from feature_readiness import create_plugin_checker


def main():
    """Main entry point."""
    plugin_dir = Path(__file__).parent
    checker = create_plugin_checker(plugin_dir, "projector")
    checker.main()


if __name__ == "__main__":
    main()