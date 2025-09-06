#!/usr/bin/env python3
"""Readiness check for NDI Module."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "shared"))
from feature_readiness import create_module_checker


def check_yuri_simple():
    """Check if yuri_simple is available."""
    if shutil.which("yuri_simple"):
        return True, "yuri_simple found in PATH"
    return False, "yuri_simple not found in PATH"


def install_yuri_simple():
    """Attempt to install yuri_simple."""
    try:
        # Check if we can install via package manager
        if shutil.which("apt-get"):
            # Try Ubuntu/Debian installation
            subprocess.run(["sudo", "apt-get", "update"], check=True, capture_output=True)
            subprocess.run(["sudo", "apt-get", "install", "-y", "yuri"], check=True, capture_output=True)
        elif shutil.which("brew"):
            # Try macOS installation
            subprocess.run(["brew", "install", "yuri"], check=True, capture_output=True)
        elif shutil.which("pip3") or shutil.which("pip"):
            # Try pip installation as fallback
            pip_cmd = "pip3" if shutil.which("pip3") else "pip"
            subprocess.run([pip_cmd, "install", "yuri"], check=True, capture_output=True)
        else:
            return False, "No suitable package manager found (apt-get, brew, or pip)"
        
        # Verify installation
        if shutil.which("yuri_simple"):
            return True, "yuri_simple successfully installed"
        else:
            return False, "Installation appeared successful but yuri_simple not found in PATH"
            
    except subprocess.CalledProcessError as e:
        return False, f"Installation failed: {e}"
    except Exception as e:
        return False, f"Installation error: {e}"


def main():
    """Main entry point."""
    module_dir = Path(__file__).parent
    checker = create_module_checker(module_dir, "ndi")
    
    # Add custom yuri_simple check
    def check_yuri_with_fix():
        """Check yuri_simple with optional auto-fix."""
        passed, message = check_yuri_simple()
        if not passed:
            # Check if --fix was requested
            if "--fix" in sys.argv:
                print("🔧 Attempting to install yuri_simple...")
                install_passed, install_message = install_yuri_simple()
                if install_passed:
                    return True, install_message
                else:
                    return False, f"{message}. Auto-install failed: {install_message}"
            else:
                return False, f"{message}. Run with --fix to attempt automatic installation"
        return True, message
    
    checker.add_check("yuri_simple", check_yuri_with_fix)
    
    # Add suggestions for failed checks
    suggestions = {
        "yuri_simple": "Install yuri_simple manually or run with --fix flag. For manual installation, see: https://github.com/iimachines/yuri or use your system package manager."
    }
    
    checker.main(suggestions)


if __name__ == "__main__":
    main()