import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
subprocess.check_call([sys.executable, os.path.join(ROOT, "scripts", "build.py")])
