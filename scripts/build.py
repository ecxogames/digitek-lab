import os
import re
import sys
import shutil
import urllib.request
import zipfile
import subprocess

def print_header(title):
    print("\n" + "="*50)
    print(f"  {title}")
    print("="*50)

def get_or_convert_icon(props):
    icon_path = props.get("ICON", "")
    if not icon_path or not os.path.exists(icon_path):
        return None

    if icon_path.lower().endswith(".png"):
        try:
            from PIL import Image
            ico_path = os.path.join("engine", "converted_icon.ico")
            img = Image.open(icon_path)
            img.save(ico_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
            return ico_path
        except ImportError:
            print("[Warning] 'Pillow' is required to convert PNG icons to ICO. Run 'pip install Pillow'. Ignoring icon.")
            return None
        except Exception as e:
            print(f"[Warning] Failed to convert PNG to ICO: {e}")
            return None
    return icon_path

def prepare_icon():
    props = parse_properties_config()
    icon_path = get_or_convert_icon(props)
    rc_path = os.path.join("engine", "icon.rc")
    
    if icon_path and os.path.exists(icon_path):
        with open(rc_path, "w") as f:
            # RC compiler needs normalized/escaped paths 
            abs_icon = os.path.abspath(icon_path).replace("\\", "/")
            f.write(f'101 ICON "{abs_icon}"\n')
    else:
        if os.path.exists(rc_path):
            try:
                os.remove(rc_path)
            except:
                pass

def run_cmake_build(embed_html=False):
    print_header("Compiling C++ Executable")
    prepare_icon()

    # Force CMake to re-evaluate whether icon.rc exists by removing the cache.
    cache_file = os.path.join("build", "CMakeCache.txt")
    if os.path.exists(cache_file):
        try:
            os.remove(cache_file)
        except OSError:
            pass

    cmake_configure = [
        "cmake",
        "-B",
        "build",
        f"-DESD_PYTHON_EXECUTABLE:FILEPATH={sys.executable}",
    ]
    if embed_html:
        cmake_configure.append("-DESD_EMBED_HTML=ON")
        print("[Info] HTML embedding enabled — UI pages will be baked into the binary.")

    subprocess.run(cmake_configure, check=True)
    subprocess.run(["cmake", "--build", "build", "--config", "Release"], check=True)

def find_exe():
    bases = [
        os.path.join('build', 'Release', 'ESDEngine.exe'),
        os.path.join('build', 'ESDEngine.exe'),
    ]
    for b in bases:
        if os.path.exists(b):
            return b
    return None

def bundle_tkinter(dist_dir):
    print(" -> Bundling Tkinter / Tcl runtime for native dialogs...")
    py_root = os.path.abspath(os.path.dirname(sys.executable))
    stdlib_dir = os.path.join(py_root, "Lib")
    dll_dir = os.path.join(py_root, "DLLs")

    try:
        tkinter_src = os.path.join(stdlib_dir, "tkinter")
        tcl_src = os.path.join(py_root, "tcl")
        if not os.path.isdir(tkinter_src):
            raise FileNotFoundError(f"Missing tkinter package: {tkinter_src}")
        if not os.path.isdir(tcl_src):
            raise FileNotFoundError(f"Missing Tcl data folder: {tcl_src}")

        shutil.copytree(tkinter_src, os.path.join(dist_dir, "tkinter"))
        shutil.copytree(tcl_src, os.path.join(dist_dir, "tcl"))

        for name in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll"):
            src = os.path.join(dll_dir, name)
            if not os.path.exists(src):
                src = os.path.join(py_root, name)
            if not os.path.exists(src):
                raise FileNotFoundError(f"Missing Tkinter runtime file: {name}")
            shutil.copy(src, dist_dir)

        print("    [Success] Bundled Tkinter native dialog support.")
    except Exception as e:
        print(f"    [Warning] Could not bundle Tkinter automatically: {e}")
        print("    Import/export and demo modal actions may fail in standalone builds.")

def build_regular():
    print_header("REGULAR BUILD (Local Testing Only)")
    print("[WARNING] The Regular build creates an executable that points directly to your local system's Python installation.")
    print("[WARNING] It will NOT work on other computers unless they have the exact same Python version installed in the same path.")
    
    run_cmake_build()
    exe = find_exe()
    if not exe:
        print("[Error] Executable not found after build.")
        return

    dist_dir = os.path.join("dist", "Regular")
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)
    os.makedirs(dist_dir)

    props = parse_properties_config()
    app_title = props.get("TITLE", "ESDEngine")
    safe_exe_name = "".join(c for c in app_title if c.isalnum() or c in " _-") + ".exe"

    print("\n -> Copying executable...")
    dest_exe = os.path.join(dist_dir, safe_exe_name)
    shutil.copy(exe, dest_exe)

    # Optional: copy resources like UI, Server, Config for local testing from this Regular directory
    try:
        shutil.copytree("ui", os.path.join(dist_dir, "ui"))
        shutil.copytree("server", os.path.join(dist_dir, "server"))
        if os.path.exists("properties.config"):
            shutil.copy("properties.config", dist_dir)
    except Exception as e:
        print(f" -> [Warning] Skipping some asset copies: {e}")

    print(f"\n[Success] Built locally for testing: {dest_exe}")

def build_standalone():
    print_header("SANDBOX / SELF-SUSTAINED BUILD")
    print("Building a completely self-contained distribution folder (Standalone Sandbox)...")
    print("This will embed the official Python runtime alongside the app, increasing file size but making it 100% portable.")

    # HTML pages are baked into the binary; the ui/ folder is intentionally excluded from dist.
    run_cmake_build(embed_html=True)
    exe = find_exe()
    if not exe:
        print("[Error] Executable not found after build.")
        return

    dist_dir = os.path.join("dist", "Standalone")
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)
    os.makedirs(dist_dir)

    props = parse_properties_config()
    app_title = props.get("TITLE", "ESDEngine")
    safe_exe_name = "".join(c for c in app_title if c.isalnum() or c in " _-") + ".exe"

    print("\n -> Copying executable...")
    shutil.copy(exe, os.path.join(dist_dir, safe_exe_name))

    print(" -> Copying Server assets...")
    shutil.copytree("server", os.path.join(dist_dir, "server"))

    print(" -> Copying Python backend support modules...")
    for package_dir in ("public", "private"):
        if os.path.exists(package_dir):
            shutil.copytree(package_dir, os.path.join(dist_dir, package_dir))

    if os.path.exists("data"):
        print(" -> Copying bundled sample data...")
        shutil.copytree("data", os.path.join(dist_dir, "data"))

    # HTML pages are embedded in the executable, but the native modal system
    # still reads modal templates/config from disk at runtime.
    modal_ui_dir = os.path.join("ui", "modals")
    splash_config = os.path.join("ui", "splash", "properties.config")
    if os.path.exists(modal_ui_dir):
        print(" -> Copying runtime modal UI templates...")
        shutil.copytree(modal_ui_dir, os.path.join(dist_dir, "ui", "modals"))
    if os.path.exists(splash_config):
        os.makedirs(os.path.join(dist_dir, "ui", "splash"), exist_ok=True)
        shutil.copy(splash_config, os.path.join(dist_dir, "ui", "splash"))

    if os.path.exists("properties.config"):
        shutil.copy("properties.config", dist_dir)

    print(" -> Bundling Python backend dependencies (pynput, vgamepad)...")
    # The embeddable Python's default _pth puts the exe dir ('.') on sys.path, so
    # installing packages into the dist root makes them importable at runtime.
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pynput", "vgamepad", "--target", dist_dir,
             "--no-compile", "--upgrade"],
            check=True)
        print("    [Success] Bundled pynput and vgamepad into the standalone runtime.")
    except Exception as e:
        print(f"    [Warning] Could not bundle pynput automatically: {e}")
        print("    Record/playback or Controller Axis actions may be disabled in the distributed build until")
        print("    pynput and vgamepad are installed into the embedded Python manually.")

    print(" -> Bundling Visual C++ Runtime libraries...")
    # Bundle MSVCP140.dll and VCRUNTIME to prevent "DLL not found" on fresh Windows
    sys32 = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'System32')
    for dll_name in ['msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll']:
        dll_path = os.path.join(sys32, dll_name)
        if os.path.exists(dll_path):
            shutil.copy(dll_path, dist_dir)

    print(f" -> Downloading Windows Embeddable Python ({sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro})...")
    # Fetch the exact Python version currently being used to build the engine
    embed_url = f"https://www.python.org/ftp/python/{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}/python-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}-embed-amd64.zip"
    
    zip_path = "python-embed.zip"
    try:
        urllib.request.urlretrieve(embed_url, zip_path)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(dist_dir)
        os.remove(zip_path)
        bundle_tkinter(dist_dir)
        print(f"\n[Success] Standalone build complete! Location: {os.path.abspath(dist_dir)}")
        print("You can zip this folder and send it to anyone. No installation is required!")
    except Exception as e:
        print(f"[Error] Failed to download/extract Python embed: {e}")
        print("Please ensure your Python version has a valid Windows embeddable package on python.org.")

def find_inno_setup():
    local_appdata = os.environ.get('LOCALAPPDATA', '')
    paths = [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        r"C:\Program Files\Inno Setup 5\ISCC.exe"
    ]
    if local_appdata:
        paths.append(os.path.join(local_appdata, r"Programs\Inno Setup 6\ISCC.exe"))
        paths.append(os.path.join(local_appdata, r"Programs\Inno Setup 5\ISCC.exe"))

    for p in paths:
        if os.path.exists(p):
            return p
    return shutil.which("ISCC")

def install_inno_setup_if_needed():
    print("\n[Warning] Inno Setup compiler (ISCC.exe) was not found on your system.")
    choice = input("Would you like to automatically install Inno Setup using Windows Package Manager (winget)? (y/n): ").strip().lower()
    if choice == 'y':
        print("\n -> Installing Inno Setup... (This may ask for Administrator privileges)")
        try:
            subprocess.run(["winget", "install", "--id", "JRSoftware.InnoSetup", "--silent", "--accept-package-agreements", "--accept-source-agreements"], check=True)
            print("\n[Success] Inno Setup installed successfully!")
            return True
        except FileNotFoundError:
            print("\n[Error] 'winget' command not found. Windows Package Manager is not available.")
        except subprocess.CalledProcessError as e:
            print(f"\n[Error] Failed to install Inno Setup via winget: {e}")
    return False

def parse_properties_config():
    props = {
        "TITLE": "ESD Suite Application",
        "VERSION": "1.0.0",
        "AUTHOR": "Ecxo Softwares"
    }
    config_path = "properties.config"
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    props[key.strip()] = val.strip()
    return props

def build_installer():
    print_header("INSTALLER BUILD")
    print("Preparing an installation package setup...")
    print("This will create a Standalone build and generate a setup installer script.")
    
    props = parse_properties_config()
    app_title = props.get("TITLE", "ESD Suite Application")
    app_version = props.get("VERSION", "1.0.0")
    app_publisher = props.get("AUTHOR", "Ecxo Softwares")
    safe_name = "".join(c for c in app_title if c.isalnum())
    safe_exe_name = "".join(c for c in app_title if c.isalnum() or c in " _-") + ".exe"
    
    dist_dir = os.path.join("dist", "Standalone")
    
    # Always rebuild so we guarantee the latest properties.config and Icon changes are applied
    build_standalone()
    
    print("\n -> Generating Inno Setup Installer Script (.iss)...")

    print(" -> Downloading Visual C++ Redistributable installer to bundle...")
    vcredist_url = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    vcredist_path = os.path.join(dist_dir, "vc_redist.x64.exe")
    if not os.path.exists(vcredist_path):
        try:
            urllib.request.urlretrieve(vcredist_url, vcredist_path)
            print("    [Success] Downloaded VC++ Redistributable.")
        except Exception as e:
            print(f"    [Error] Failed to download VC++ Redist: {e}")

    icon_prop = get_or_convert_icon(props)
    setup_icon_line = ""
    if icon_prop and os.path.exists(icon_prop):
        setup_icon_line = f"SetupIconFile={os.path.abspath(icon_prop)}\n"

    iss_content = f"""
[Setup]
AppName={app_title}
AppVersion={app_version}
AppPublisher={app_publisher}
{setup_icon_line}DefaultDirName={{autopf}}\\{safe_name}
DefaultGroupName={app_title}
OutputDir=dist
OutputBaseFilename={safe_name}_Installer
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "{os.path.abspath(dist_dir)}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{app_title}"; Filename: "{{app}}\\{safe_exe_name}"
Name: "{{autodesktop}}\\{app_title}"; Filename: "{{app}}\\{safe_exe_name}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Run]
Filename: "{{app}}\\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing Visual C++ Redistributable..."; Flags: waituntilterminated
"""
    iss_dir = "dist"
    if not os.path.exists(iss_dir):
        os.makedirs(iss_dir)
        
    iss_path = os.path.join(iss_dir, "installer.iss")
    with open(iss_path, "w") as f:
        f.write(iss_content.strip())
        
    print(f"\n[Success] Created installer generation script at: {os.path.abspath(iss_path)}")
    
    iscc_path = find_inno_setup()
    
    if not iscc_path:
        if install_inno_setup_if_needed():
            iscc_path = find_inno_setup() # Check again after installation
            
    if iscc_path:
        print(f"\n -> Found Inno Setup Compiler at: {iscc_path}")
        print(" -> Compiling installer executable. Please wait...")
        try:
            subprocess.run([iscc_path, iss_path], check=True)
            installer_exe = os.path.abspath(os.path.join(iss_dir, "ESDSuite_Installer.exe"))
            print(f"\n[Success] Your installer has been successfully built: {installer_exe}")
        except subprocess.CalledProcessError as e:
            print(f"\n[Error] Failed to compile installer: {e}")
    else:
        print("\n" + "-"*50)
        print(" TO FINISH BUILDING YOUR SETUP.EXE:")
        print(" 1. Download & Install 'Inno Setup' from: https://jrsoftware.org/isdl.php")
        print(f" 2. Right-click the file '{iss_path}'")
        print(" 3. Select 'Compile'")
        print(" 4. Your Setup.exe will magically appear in the 'dist' folder!")
        print("-" * 50)

def _minify_css(css):
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)
    css = re.sub(r'\s+', ' ', css)
    css = re.sub(r'\s*([{}:;,>~+])\s*', r'\1', css)
    return css.strip()

def _minify_js(js):
    js = re.sub(r'/\*.*?\*/', '', js, flags=re.DOTALL)
    js = re.sub(r'(?<![:/])//[^\n]*', '', js)
    js = re.sub(r'[ \t]+', ' ', js)
    js = re.sub(r'\n\s*\n', '\n', js)
    return js.strip()

def _obfuscate_html(content):
    def repl_style(m):
        return f'<style>{_minify_css(m.group(1))}</style>'
    content = re.sub(r'<style[^>]*>(.*?)</style>', repl_style, content, flags=re.DOTALL | re.IGNORECASE)

    def repl_script(m):
        open_tag, inner = m.group(1), m.group(2)
        if 'src=' in open_tag.lower():
            return m.group(0)
        return f'{open_tag}{_minify_js(inner)}</script>'
    content = re.sub(r'(<script\b[^>]*>)(.*?)</script>', repl_script, content, flags=re.DOTALL | re.IGNORECASE)

    content = re.sub(r'<!--(?!\[if).*?-->', '', content, flags=re.DOTALL)
    content = re.sub(r'>\s{2,}<', '><', content)
    content = '\n'.join(l.strip() for l in content.splitlines() if l.strip())
    return content

def _extract_page_parts(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    title_m = re.search(r'<title[^>]*>(.*?)</title>', content, re.DOTALL | re.IGNORECASE)
    title = title_m.group(1).strip() if title_m else os.path.splitext(os.path.basename(filepath))[0]

    styles = re.findall(r'<style[^>]*>.*?</style>', content, re.DOTALL | re.IGNORECASE)

    body_m = re.search(r'<body[^>]*>(.*?)</body>', content, re.DOTALL | re.IGNORECASE)
    body = body_m.group(1).strip() if body_m else content

    ext_css = re.findall(r'<link\b[^>]*rel=["\']stylesheet["\'][^>]*>', content, re.IGNORECASE)
    ext_css += re.findall(r'<link\b[^>]*href=["\'][^"\']+["\'][^>]*rel=["\']stylesheet["\'][^>]*>', content, re.IGNORECASE)

    scripts = re.findall(r'<script\b[^>]*>.*?</script>', content, re.DOTALL | re.IGNORECASE)
    ext_js = re.findall(r'<script\b[^>]*src=["\'][^"\']+["\'][^>]*(?:></script>|/>)', content, re.IGNORECASE)

    return {
        'title': title,
        'styles': styles,
        'ext_css': list(dict.fromkeys(ext_css)),
        'body': body,
        'scripts': scripts,
        'ext_js': list(dict.fromkeys(ext_js)),
    }

def _build_web_single_html(pages_dir, html_files, dist_dir, safe_name, do_obfuscate):
    print("\n -> Building single HTML file...")

    if len(html_files) == 1:
        src = os.path.join(pages_dir, html_files[0])
        with open(src, 'r', encoding='utf-8') as f:
            content = f.read()
        if do_obfuscate:
            content = _obfuscate_html(content)
        out_path = os.path.join(dist_dir, safe_name + ".html")
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\n[Success] Single HTML file: {os.path.abspath(out_path)}")
        return

    pages_data = []
    for fname in html_files:
        data = _extract_page_parts(os.path.join(pages_dir, fname))
        data['id'] = re.sub(r'[^a-zA-Z0-9_-]', '_', os.path.splitext(fname)[0])
        pages_data.append(data)

    seen_css, seen_js = set(), set()
    ext_css_lines, ext_js_lines = [], []
    for p in pages_data:
        for link in p['ext_css']:
            if link not in seen_css:
                seen_css.add(link)
                ext_css_lines.append(f'    {link}')
        for tag in p['ext_js']:
            if tag not in seen_js:
                seen_js.add(tag)
                ext_js_lines.append(f'    {tag}')

    seen_styles = []
    for p in pages_data:
        for s in p['styles']:
            if s not in seen_styles:
                seen_styles.append(s)

    tabs_html = ''.join(
        f'<button class="__tab" data-page="{p["id"]}" onclick="__showPage(\'{p["id"]}\')">{p["title"]}</button>'
        for p in pages_data
    )
    sections_html = ''.join(
        f'<div id="__page-{p["id"]}" class="__page-section" style="display:none">{p["body"]}</div>'
        for p in pages_data
    )
    first_id = pages_data[0]['id']
    all_scripts = ''.join(p['scripts'] for p in pages_data)

    combined = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_name}</title>
{chr(10).join(ext_css_lines)}
{chr(10).join(seen_styles)}
<style>
.__tab-bar{{display:flex;gap:4px;padding:8px;background:#0a0a0a;border-bottom:1px solid #2a2a2a;position:fixed;top:0;left:0;right:0;z-index:9999}}
.__tab{{padding:5px 14px;border:1px solid #2a2a2a;border-radius:4px;background:transparent;color:#a0a0a0;cursor:pointer;font-family:inherit;font-size:12px;transition:all .15s ease}}
.__tab:hover{{background:rgba(255,255,255,.07);color:#ccc}}
.__tab.active{{background:rgba(37,99,235,.18);border-color:rgba(37,99,235,.4);color:#60a5fa}}
.__page-section{{padding-top:44px}}
</style>
</head>
<body>
<div class="__tab-bar">{tabs_html}</div>
{sections_html}
{chr(10).join(ext_js_lines)}
{all_scripts}
<script>
function __showPage(id){{
  document.querySelectorAll('.__page-section').forEach(function(s){{s.style.display='none'}});
  document.querySelectorAll('.__tab').forEach(function(t){{t.classList.remove('active')}});
  var s=document.getElementById('__page-'+id);if(s)s.style.display='block';
  var t=document.querySelector('.__tab[data-page="'+id+'"]');if(t)t.classList.add('active');
}}
__showPage('{first_id}');
</script>
</body>
</html>"""

    if do_obfuscate:
        combined = _obfuscate_html(combined)

    out_path = os.path.join(dist_dir, safe_name + ".html")
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(combined)
    print(f"\n[Success] Combined HTML ({len(html_files)} pages): {os.path.abspath(out_path)}")

def _build_web_zip(pages_dir, dist_dir, safe_name, do_obfuscate):
    print("\n -> Packaging pages folder as ZIP...")

    out_path = os.path.join(dist_dir, safe_name + "_web.zip")
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(pages_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                arcname = os.path.relpath(fpath, os.path.dirname(pages_dir))
                if fname.lower().endswith('.html') and do_obfuscate:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        content = _obfuscate_html(f.read())
                    zf.writestr(arcname, content)
                else:
                    zf.write(fpath, arcname)

    print(f"\n[Success] ZIP archive: {os.path.abspath(out_path)}")

def build_web():
    print_header("WEB PUBLISH BUILD")
    print("Packages the ui/pages folder for web publishing.")

    pages_dir = os.path.join("ui", "pages")
    if not os.path.exists(pages_dir):
        print(f"[Error] Pages folder not found: {os.path.abspath(pages_dir)}")
        return

    html_files = sorted(f for f in os.listdir(pages_dir) if f.lower().endswith('.html'))
    if not html_files:
        print("[Error] No HTML files found in ui/pages/")
        return

    print(f"\n -> Found {len(html_files)} page(s): {', '.join(html_files)}")

    while True:
        print("\nSelect web output format:")
        print(" 1. Single HTML file  (all pages combined into one .html)")
        print(" 2. Structured ZIP    (pages folder packaged as a .zip archive)")
        fmt = input("Choose format (1/2): ").strip()
        if fmt in ('1', '2'):
            break
        print("Invalid choice. Please enter 1 or 2.")

    while True:
        obf = input("\nObfuscate / minify the output? (y/n): ").strip().lower()
        if obf in ('y', 'n', 'yes', 'no'):
            break
        print("Please enter 'y' or 'n'.")
    do_obfuscate = obf.startswith('y')

    props = parse_properties_config()
    app_title = props.get("TITLE", "ESD Suite Application")
    safe_name = "".join(c for c in app_title if c.isalnum() or c in " _-").strip()

    dist_dir = os.path.join("dist", "Web")
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)
    os.makedirs(dist_dir)

    if fmt == '1':
        _build_web_single_html(pages_dir, html_files, dist_dir, safe_name, do_obfuscate)
    else:
        _build_web_zip(pages_dir, dist_dir, safe_name, do_obfuscate)

def main():
    while True:
        print_header("ESD Suite - Distribution Build Manager")
        print(" 1. Installer         (Creates a Standalone app + generated Setup.exe script)")
        print(" 2. Sandbox/Standalone(Builds a portable folder with embedded Python - No setup required)")
        print(" 3. Regular           (Natively builds .exe - Local Dev Testing ONLY)")
        print(" 4. Web Publish       (Packages ui/pages as a single HTML or structured ZIP)")
        print(" 5. Exit")

        choice = input("\nSelect build type (1/2/3/4/5): ").strip()

        if choice == '1':
            build_installer()
            break
        elif choice == '2':
            build_standalone()
            break
        elif choice == '3':
            build_regular()
            break
        elif choice == '4':
            build_web()
            break
        elif choice == '5':
            sys.exit(0)
        else:
            print("Invalid selection. Please type a number.")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting builder.")
        sys.exit(0)
