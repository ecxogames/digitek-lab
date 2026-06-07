import urllib.request
import os
import subprocess
import sys
import platform
import tempfile
import zipfile
import shutil

WEBVIEW_HEADER_URL = "https://raw.githubusercontent.com/webview/webview/0.10.0/webview.h"
WEBVIEW2_NUGET_URL = "https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2"

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGET_DIR = os.path.join(BASE_DIR, "engine")
TARGET_PATH = os.path.join(TARGET_DIR, "webview.h")
WEBVIEW2_DIR = os.path.join(TARGET_DIR, "webview2")
BUILD_DIR = os.path.join(BASE_DIR, "build")

def download_webview():
    print(f"[*] Downloading webview.h from {WEBVIEW_HEADER_URL}...")
    try:
        os.makedirs(TARGET_DIR, exist_ok=True)
        urllib.request.urlretrieve(WEBVIEW_HEADER_URL, TARGET_PATH)
        print(f"[+] Successfully downloaded to {TARGET_PATH}")
    except Exception as e:
        print(f"[-] Error downloading webview.h: {e}")
        sys.exit(1)

def download_webview2_headers():
    if platform.system() != "Windows":
        return # WebView2 is Windows-only

    print(f"[*] Downloading Microsoft WebView2 SDK...")
    
    zip_path = os.path.join(tempfile.gettempdir(), "webview2.zip")
    try:
        urllib.request.urlretrieve(WEBVIEW2_NUGET_URL, zip_path)
        
        # Extract only the necessary C++ headers
        os.makedirs(WEBVIEW2_DIR, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.namelist():
                if member.startswith("build/native/include/"):
                    # Extract it while flattening the directory structure
                    filename = os.path.basename(member)
                    if filename: # Skip empty directories
                        source = zip_ref.open(member)
                        target = open(os.path.join(WEBVIEW2_DIR, filename), "wb")
                        with source, target:
                            shutil.copyfileobj(source, target)
        
        print(f"[+] Successfully extracted WebView2 headers to {WEBVIEW2_DIR}")
        os.remove(zip_path)
    except Exception as e:
        print(f"[-] Error downloading/extracting WebView2: {e}")
        sys.exit(1)

def install_cmake():
    print("\n[-] CMake not found in your system's PATH.")
    choice = input("[?] Would you like to automatically download and install CMake now? (Y/n): ")
    if choice.strip().lower() not in ['', 'y', 'yes']:
        print("[-] Please install CMake manually from https://cmake.org/download/ and try again.")
        sys.exit(1)
        
    if platform.system() != "Windows":
        print("[-] Automated installation is currently only supported on Windows.")
        print("[-] Please install via your package manager (e.g., `apt install cmake` or `brew install cmake`).")
        sys.exit(1)
        
    cmake_version = "3.29.3"
    msi_url = f"https://github.com/Kitware/CMake/releases/download/v{cmake_version}/cmake-{cmake_version}-windows-x86_64.msi"
    msi_path = os.path.join(tempfile.gettempdir(), f"cmake-{cmake_version}.msi")
    
    print(f"[*] Downloading CMake {cmake_version} installer... (This might take a minute)")
    try:
        urllib.request.urlretrieve(msi_url, msi_path)
        print("[*] Installing CMake... (Please accept the Administrator privilege prompt if it appears)")
        # /passive shows progress bar, ADD_CMAKE_TO_PATH=System adds it to the system environment variables
        subprocess.run(["msiexec.exe", "/i", msi_path, "ADD_CMAKE_TO_PATH=System", "/passive"], check=True)
        
        # Temporarily append the default installation directory to the current process PATH
        # so that the script can continue right away without requiring a terminal restart.
        os.environ["PATH"] += os.pathsep + r"C:\Program Files\CMake\bin"
        
        print("[+] CMake installation completed successfully.")
    except Exception as e:
        print(f"[-] Failed to install CMake automatically: {e}")
        sys.exit(1)

def install_python_deps():
    """Install the Python packages the DigiTek Lab backend needs for development."""
    deps = ["pynput", "vgamepad"]  # real keyboard/mouse plus virtual controller playback
    print(f"\n[*] Installing Python backend dependencies: {', '.join(deps)}...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", *deps], check=True)
        print("[+] Python dependencies installed.")
    except Exception as e:
        print(f"[-] Warning: could not install {deps} automatically: {e}")
        print(f"    Install manually with: pip install {' '.join(deps)}")


def configure_cmake():
    print("\n[*] Configuring CMake...")
    os.makedirs(BUILD_DIR, exist_ok=True)
    try:
        subprocess.run(["cmake", ".."], cwd=BUILD_DIR, check=True)
        print("[+] CMake configuration completed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"[-] Error during CMake configuration: {e}")
        print("Note: On Windows, to compile you will also need the WebView2 SDK. Check the readme for https://github.com/webview/webview")
        sys.exit(1)
    except FileNotFoundError:
        install_cmake()
        print("\n[*] Retrying CMake configuration...")
        try:
            subprocess.run(["cmake", ".."], cwd=BUILD_DIR, check=True)
            print("[+] CMake configuration completed successfully.")
        except Exception as e:
            print(f"[-] Error running CMake after installation. Note: You might need to restart your terminal to refresh the system PATH.")
            sys.exit(1)

def print_instructions():
    print("\n" + "="*55)
    print(" Setup Complete! Here are your next steps:")
    print("="*55)
    print("\n1. Build the project:")
    print("   cd build")
    print("   cmake --build .")
    print("\n2. Run the application:")
    if os.name == 'nt': # Windows
        print("   .\\build\\Debug\\ESDEngine.exe")
    else:
        print("   ./build/ESDEngine")
    print("\n" + "="*55 + "\n")

if __name__ == "__main__":
    print("Starting ESD Suite Environment Setup...\n")
    download_webview()
    download_webview2_headers()
    install_python_deps()
    configure_cmake()
    print_instructions()
