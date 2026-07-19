import sys
sys.path.insert(0, ".")
from pathlib import Path

# Override sys.frozen so project_root acts like we are running the built exe
sys.frozen = True
sys.executable = r"D:\Laptrinh\SmartOfficeAI360\dist\SmartOfficeAI360\SmartOfficeAI360.exe"

from tools.qlvb_downloader.config import load_config
try:
    c = load_config()
    print("Success:", c.username)
except Exception as e:
    import traceback
    traceback.print_exc()
