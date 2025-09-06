#!/usr/bin/env python3
"""Installation script for yuri_simple NDI streaming tool."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def check_yuri_simple():
    """Check if yuri_simple is available in PATH."""
    return shutil.which("yuri_simple") is not None


def install_via_apt():
    """Install yuri via apt (Ubuntu/Debian)."""
    try:
        print("🔄 Updating package lists...")
        subprocess.run(["sudo", "apt-get", "update"], check=True, capture_output=True)
        
        print("🔄 Installing yuri package...")
        subprocess.run(["sudo", "apt-get", "install", "-y", "yuri"], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ APT installation failed: {e}")
        return False


def install_via_brew():
    """Install yuri via Homebrew (macOS)."""
    try:
        print("🔄 Installing yuri via Homebrew...")
        subprocess.run(["brew", "install", "yuri"], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Homebrew installation failed: {e}")
        return False


def install_via_pip():
    """Install yuri via pip (fallback)."""
    try:
        pip_cmd = "pip3" if shutil.which("pip3") else "pip"
        print(f"🔄 Installing yuri via {pip_cmd}...")
        subprocess.run([pip_cmd, "install", "yuri"], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Pip installation failed: {e}")
        return False


def install_from_source():
    """Install yuri from source (GitHub)."""
    try:
        print("🔄 Installing yuri from source...")
        
        # Create temporary directory
        temp_dir = Path("/tmp/yuri_install")
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir()
        
        # Clone repository
        subprocess.run([
            "git", "clone", 
            "https://github.com/iimachines/yuri.git", 
            str(temp_dir)
        ], check=True, capture_output=True)
        
        # Build and install
        os.chdir(temp_dir)
        
        # Check if CMake is available
        if not shutil.which("cmake"):
            print("❌ CMake is required for source installation")
            return False
        
        # Create build directory and build
        build_dir = temp_dir / "build"
        build_dir.mkdir()
        os.chdir(build_dir)
        
        subprocess.run(["cmake", ".."], check=True, capture_output=True)
        subprocess.run(["make"], check=True, capture_output=True)
        subprocess.run(["sudo", "make", "install"], check=True, capture_output=True)
        
        # Clean up
        os.chdir("/")
        shutil.rmtree(temp_dir)
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Source installation failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Source installation error: {e}")
        return False


def install_yuri_simple(method=None):
    """Install yuri_simple using the specified method or auto-detect."""
    if check_yuri_simple():
        print("✅ yuri_simple is already installed and available")
        return True
    
    print("📦 yuri_simple not found. Attempting installation...")
    
    installation_methods = []
    
    if method:
        # Use specific method
        if method == "apt" and shutil.which("apt-get"):
            installation_methods = [install_via_apt]
        elif method == "brew" and shutil.which("brew"):
            installation_methods = [install_via_brew]
        elif method == "pip" and (shutil.which("pip") or shutil.which("pip3")):
            installation_methods = [install_via_pip]
        elif method == "source":
            installation_methods = [install_from_source]
        else:
            print(f"❌ Requested method '{method}' is not available or not supported")
            return False
    else:
        # Auto-detect available methods
        if shutil.which("apt-get"):
            installation_methods.append(install_via_apt)
        elif shutil.which("brew"):
            installation_methods.append(install_via_brew)
        
        if shutil.which("pip") or shutil.which("pip3"):
            installation_methods.append(install_via_pip)
        
        # Source installation as last resort
        if shutil.which("git") and shutil.which("cmake"):
            installation_methods.append(install_from_source)
    
    if not installation_methods:
        print("❌ No suitable installation method found")
        print("💡 Please install yuri_simple manually:")
        print("   - Ubuntu/Debian: sudo apt-get install yuri")
        print("   - macOS: brew install yuri")
        print("   - From source: https://github.com/iimachines/yuri")
        return False
    
    # Try each installation method
    for install_func in installation_methods:
        print(f"🔄 Trying installation method: {install_func.__name__}")
        if install_func():
            # Verify installation
            if check_yuri_simple():
                print("✅ yuri_simple successfully installed and verified")
                return True
            else:
                print("⚠️  Installation completed but yuri_simple not found in PATH")
    
    print("❌ All installation methods failed")
    return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Install yuri_simple NDI streaming tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 install_yuri_simple.py                    # Auto-detect and install
  python3 install_yuri_simple.py --method apt       # Use apt package manager
  python3 install_yuri_simple.py --method brew      # Use Homebrew
  python3 install_yuri_simple.py --method pip       # Use pip
  python3 install_yuri_simple.py --method source    # Build from source
  python3 install_yuri_simple.py --check            # Just check if installed
        """
    )
    
    parser.add_argument(
        "--method",
        choices=["apt", "brew", "pip", "source"],
        help="Installation method to use"
    )
    
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check if yuri_simple is installed"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show verbose output"
    )
    
    args = parser.parse_args()
    
    if args.check:
        if check_yuri_simple():
            print("✅ yuri_simple is installed and available")
            sys.exit(0)
        else:
            print("❌ yuri_simple is not installed")
            sys.exit(1)
    
    # Attempt installation
    success = install_yuri_simple(args.method)
    
    if success:
        print("\n🎉 Installation completed successfully!")
        print("You can now use yuri_simple for NDI streaming.")
    else:
        print("\n❌ Installation failed.")
        print("Please install yuri_simple manually or check the error messages above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
