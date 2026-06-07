import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main():
    print("Template plugin root:", ROOT)
    print("Building a .dgtkplgn package...")
    subprocess.check_call([sys.executable, os.path.join(ROOT, "scripts", "build.py")])


if __name__ == "__main__":
    main()
