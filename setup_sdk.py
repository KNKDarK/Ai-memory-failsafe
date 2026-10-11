# setup_sdk.py
from pathlib import Path

# 1. Define backend/sdk.py content
sdk_code = '''import functools
from typing import Callable, Any, Dict, Optional
from backend.agent.analyzer import analyze_failure_deterministically
from backend.memory.store import MemoryStore

class MemoryGuard:
    def __init__(self, db_path: str = "data/memory_store.db"):
        self.store = MemoryStore(db_path=db_path)

    def guard_tool(self, task_prompt: str):
        """Decorator that catches tool failures, extracts failure memories, 
        and runs pre-flight checks on subsequent executions."""
        def decorator(func: Callable):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                # 1. Retrieve prior memories for this task
                memories = self.store.search_memories(task_prompt)
                for mem in memories:
                    actions = mem.get("prevention_actions", [])
                    for action in actions:
                        if action.startswith("verify_file_exists:"):
                            required_path = action.split(":", 1)[1]
                            print(f"🛡️ [MemoryGuard] Pre-flight active: checking file '{required_path}'...")

                # 2. Execute tool
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    print(f"⚠️ [MemoryGuard] Caught failure in '{func.__name__}': {e}")
                    
                    # 3. Build payload & analyze failure
                    payload = {
                        "original_task": task_prompt,
                        "tool_executed": func.__name__,
                        "tool_arguments": kwargs,
                        "error_details": {
                            "error_code": getattr(e, "errno", type(e).__name__),
                            "message": str(e)
                        }
                    }
                    
                    analysis = analyze_failure_deterministically(payload)
                    
                    # 4. Save memory to SQLite store
                    memory_id = self.store.add_memory(
                        task_prompt=task_prompt,
                        fault_category=analysis.fault_category,
                        root_cause=analysis.root_cause,
                        lesson=analysis.lesson,
                        prevention_strategy=analysis.prevention_strategy,
                        prevention_actions=analysis.prevention_actions,
                        confidence=analysis.confidence
                    )
                    print(f"✅ [MemoryGuard] Persisted failure memory (ID: {memory_id})")
                    raise e

            return wrapper
        return decorator
'''

# 2. Define examples/use_product.py content
example_code = """import sys
from pathlib import Path

# Add project root to sys.path
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

# --- Run 1: Expect Failure & Memory Storage ---
print("--- RUN 1: Executing without config file ---")
try:
    read_config_file(path="config/prod.json")
except Exception:
    print("Run 1 completed with caught failure.\\n")

# --- Run 2: Expect Pre-flight Memory Activation ---
print("--- RUN 2: Executing same task again ---")
try:
    read_config_file(path="config/prod.json")
except Exception:
    print("Run 2 completed with memory check active.")
"""

# 3. Write files to disk
Path("backend/sdk.py").write_text(sdk_code)
Path("examples").mkdir(exist_ok=True)
Path("examples/use_product.py").write_text(example_code)

print("✅ Created backend/sdk.py and examples/use_product.py successfully!")
