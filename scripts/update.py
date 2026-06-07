import os
import urllib.request
import urllib.error
import json
import zipfile
import shutil
import tempfile

REPO_API_URL = "https://api.github.com/repos/ecxogames/esd-suite/releases/latest"

# Define what parts of the project are the "Framework" (safe to overwrite)
# vs "User Space" (ui/, server/, private/, public/, properties.config)
FRAMEWORK_DIRS = ["engine", "scripts", "documentation"]
FRAMEWORK_FILES = ["CMakeLists.txt"]

def print_header(title):
    print("\n" + "="*50)
    print(f"  {title}")
    print("="*50)

def main():
    # Ensure we are in the right directory (project root)
    if not os.path.exists("engine") or not os.path.exists("scripts"):
        print("[Error] Please run this script from the project root directory (e.g. 'python scripts/update.py').")
        return

    print_header("ESD Suite Framework Updater")
    print("Checking for the latest release on GitHub...")
    
    try:
        req = urllib.request.Request(REPO_API_URL, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        latest_version = data.get("tag_name", "Unknown")
        zip_url = data.get("zipball_url")
        
        if not zip_url:
            print("[Error] No source code zip found for the latest release.")
            return
            
        print(f"Found latest stable version: {latest_version}")
        
        print("\n[WARNING] Updating will overwrite core framework directories (engine/, scripts/, CMakeLists.txt)")
        print("          Your ui/, server/, and properties.config will NOT be affected.")
        choice = input(f"Do you want to download and install {latest_version}? (y/n): ").strip().lower()
        
        if choice != 'y':
            print("Update cancelled.")
            return
            
        temp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(temp_dir, "update.zip")
        
        print(f"\n -> Downloading {latest_version} from GitHub...")
        req = urllib.request.Request(zip_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response, open(zip_path, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
            
        print(" -> Extracting files...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
            
        # Find the root extracted folder (GitHub adds the commit hash to the folder name)
        extracted_folders = [f for f in os.listdir(temp_dir) if os.path.isdir(os.path.join(temp_dir, f))]
        root_folder = os.path.join(temp_dir, extracted_folders[0])
        
        # In case the zip structure contains the 'main' directory directly (depends on how repo is structured)
        source_root = root_folder
        if os.path.exists(os.path.join(root_folder, "main")):
            source_root = os.path.join(root_folder, "main")
        
        print(" -> Applying framework patches...")
        
        # 1. Update Directories
        for d in FRAMEWORK_DIRS:
            src_dir = os.path.join(source_root, d)
            dst_dir = d
            if os.path.exists(src_dir):
                if os.path.exists(dst_dir):
                    print(f"    [Updating] Folder: {d}/")
                    # We no longer wipe the directory (rmtree) to prevent deleting the running update.py script.
                    # dirs_exist_ok=True gracefully overwrites existing files with the updated ones.
                shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
        
        # 2. Update Files
        for f in FRAMEWORK_FILES:
            src_file = os.path.join(source_root, f)
            dst_file = f
            if os.path.exists(src_file):
                print(f"    [Updating] File:   {f}")
                shutil.copy(src_file, dst_file)
                
        # 3. Merge properties.config seamlessly
        new_props_path = os.path.join(source_root, "properties.config")
        local_props_path = "properties.config"
        if os.path.exists(new_props_path) and os.path.exists(local_props_path):
            print(f"    [Updating] Merging properties.config...")
            local_keys = set()
            with open(local_props_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and "=" in line and not line.startswith("#"):
                        local_keys.add(line.split("=", 1)[0].strip())
            
            with open(new_props_path, "r", encoding="utf-8") as nf:
                new_lines = nf.readlines()
                
            with open(local_props_path, "a", encoding="utf-8") as f:
                for line in new_lines:
                    sline = line.strip()
                    if sline and "=" in sline and not sline.startswith("#"):
                        key = sline.split("=", 1)[0].strip()
                        if key not in local_keys:
                            print(f"      + Adding new property: {key}")
                            f.write(f"\n{sline}")
                            
        print(f"\n[Success] Framework architecture successfully updated to {latest_version}!\n")
        
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"[Error] No releases found in the repository yet (HTTP 404).")
            print("Make sure you publish a release on https://github.com/ecxogames/esd-suite/releases first.")
        else:
            print(f"[Error] Network error HTTP {e.code}: {e.reason}")
    except Exception as e:
        print(f"[Error] Update failed: {e}")
    finally:
        if 'temp_dir' in locals() and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except:
                pass

if __name__ == "__main__":
    main()