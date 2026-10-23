import functools
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
