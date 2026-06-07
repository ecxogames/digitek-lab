import os
import time
import subprocess
import sys
import shutil

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
try:
    from scripts.build import prepare_icon
except ImportError:
    prepare_icon = lambda: None

WATCH_PATHS = ['engine', 'server', 'ui', 'properties.config', 'CMakeLists.txt']
BUILD_DIR = 'build'

def get_exe_path():
    bases = [
        os.path.join('build', 'Debug', 'ESDEngine.exe'),
        os.path.join('build', 'Release', 'ESDEngine.exe'),
        os.path.join('build', 'ESDEngine.exe'),
        os.path.join('build', 'ESDEngine')
    ]
    for b in bases:
        if os.path.exists(b):
            return b
    return None

def get_latest_mtime():
    max_ts = 0
    IGNORE_FILES = {'icon.rc', 'converted_icon.ico'}
    IGNORE_DIRS = {'__pycache__'}

    for path in WATCH_PATHS:
        if not os.path.exists(path):
            continue
        if os.path.isfile(path):
            if os.path.basename(path) not in IGNORE_FILES:
                max_ts = max(max_ts, os.path.getmtime(path))
        else:
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
                for f in files:
                    if f in IGNORE_FILES:
                        continue
                    try:
                        max_ts = max(max_ts, os.path.getmtime(os.path.join(root, f)))
                    except FileNotFoundError:
                        pass
    return max_ts

def clean_build():
    if not os.path.exists(BUILD_DIR):
        return
    print("[Dev] Clearing build directory...")
    shutil.rmtree(BUILD_DIR)

def build_project():
    print("[Dev] Building project...")
    try:
        prepare_icon()
        cache_file = os.path.join(BUILD_DIR, "CMakeCache.txt")
        if os.path.exists(cache_file):
            try:
                os.remove(cache_file)
            except OSError:
                pass
        subprocess.run(['cmake', '-B', BUILD_DIR, '-DESD_EMBED_HTML=OFF'], check=True, stdout=subprocess.DEVNULL)
    except Exception as e:
        print(f"[Dev] Warning: pre-build step failed: {e}")

    result = subprocess.run(['cmake', '--build', BUILD_DIR])
    return result.returncode == 0

SERVER_PORT = 2024

def free_port():
    """Kill any process currently bound to SERVER_PORT so the new server can bind cleanly."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(('127.0.0.1', SERVER_PORT)) != 0:
            return  # port already free
    try:
        result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if f':{SERVER_PORT}' in line and 'LISTENING' in line:
                parts = line.split()
                pid = parts[-1]
                if pid.isdigit() and pid != '0':
                    subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True)
                    print(f"[Dev] Released port {SERVER_PORT} (killed PID {pid})")
                    time.sleep(0.3)
                    break
    except Exception as e:
        print(f"[Dev] Warning: could not release port {SERVER_PORT}: {e}")

def clear_webview_cache():
    """Delete WebView2's persistent disk cache so every launch loads fresh content."""
    exe = get_exe_path()
    candidates = []

    if exe:
        exe_dir = os.path.dirname(os.path.abspath(exe))
        candidates.append(os.path.join(exe_dir, 'ESDEngine.exe.WebView2'))

    local_appdata = os.environ.get('LOCALAPPDATA', '')
    if local_appdata:
        candidates.append(os.path.join(local_appdata, 'ESDEngine.exe.WebView2'))
        candidates.append(os.path.join(local_appdata, 'ESDEngine'))

    for path in candidates:
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
                print(f"[Dev] Cleared WebView2 cache: {path}")
            except Exception as e:
                print(f"[Dev] Warning: could not clear cache at {path}: {e}")

def launch_exe():
    exe = get_exe_path()
    if not exe:
        print("[Dev] Could not find compiled executable.")
        return None
    free_port()
    clear_webview_cache()
    print(f"[Dev] Starting {exe}...")
    return subprocess.Popen([exe])

def start_app(fresh=False):
    if fresh:
        clean_build()
    if not build_project():
        print("[Dev] Build failed. Waiting for changes to try again...")
        return None
    return launch_exe()

def ask_startup_choice():
    print("\n" + "=" * 50)
    print("  ESD Suite - Dev Server")
    print("=" * 50)
    print("\n  [1] Fresh build   — clears the build dir and compiles from scratch")
    print("  [2] Previous build — launches the last compiled binary immediately")
    print()
    while True:
        choice = input("Select (1/2): ").strip()
        if choice in ('1', '2'):
            return choice
        print("  Please enter 1 or 2.")

def main():
    choice = ask_startup_choice()
    print(f"\n[Dev] Watching: {', '.join(WATCH_PATHS)}")

    if choice == '2':
        exe = get_exe_path()
        if exe:
            print(f"[Dev] Launching existing binary: {exe}")
            app_process = subprocess.Popen([exe])
        else:
            print("[Dev] No previous build found — running a fresh build instead.")
            app_process = start_app(fresh=True)
    else:
        app_process = start_app(fresh=True)

    last_mtime = get_latest_mtime()

    try:
        while True:
            time.sleep(1)
            current_mtime = get_latest_mtime()

            if current_mtime > last_mtime:
                print("\n[Dev] File changes detected — rebuilding...")

                if app_process and app_process.poll() is None:
                    app_process.terminate()
                    app_process.wait()

                app_process = start_app(fresh=False)
                last_mtime = get_latest_mtime()

    except KeyboardInterrupt:
        print("\n[Dev] Shutting down.")
        if app_process and app_process.poll() is None:
            app_process.terminate()
            app_process.wait()
        sys.exit(0)

if __name__ == '__main__':
    main()
