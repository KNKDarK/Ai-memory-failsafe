import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.sdk import MemoryGuard

guard = MemoryGuard()
TASK_NAME = "Read production configuration"


@guard.guard_tool(task_prompt=TASK_NAME)
def read_config_file(path: str):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found. The path '{path}' does not exist in CWD.")
    return p.read_text()


print("--- RUN 1: Executing without config file ---")
try:
    read_config_file(path="config/prod.json")
except Exception:
    print("Run 1 completed with caught failure.")
    print()

print("--- RUN 2: Executing same task again ---")
try:
    read_config_file(path="config/prod.json")
except Exception:
    print("Run 2 completed with memory check active.")
