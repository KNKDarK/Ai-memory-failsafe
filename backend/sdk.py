import functools
import uuid
from collections.abc import Callable

from backend.agent.analyzer import analyze_failure_deterministically
from backend.memory.models import FailureMemory
from backend.memory.store import MemoryStore


class MemoryGuard:
    def __init__(self):
        self.store = MemoryStore()

    def guard_tool(self, task_prompt: str):
        def decorator(func: Callable):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                # 1. Retrieve active failure memories
                try:
                    memories = self.store.all_active()
                    for mem in memories:
                        actions = getattr(mem, "prevention_actions", None)
                        if actions is None and hasattr(mem, "prevention"):
                            prev = mem.prevention
                            actions = getattr(prev, "prevention_actions", None) or getattr(
                                prev, "actions", []
                            )

                        for action in actions or []:
                            if action.startswith("verify_file_exists:"):
                                required_path = action.split(":", 1)[1]
                                print(
                                    f"🛡️ [MemoryGuard] Pre-flight active: checking file '{required_path}'..."
                                )
                except Exception as search_err:
                    print(f"⚠️ [MemoryGuard] Search notice: {search_err}")

                # 2. Execute target function
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    print(f"⚠️ [MemoryGuard] Caught failure in '{func.__name__}': {e}")

                    payload = {
                        "original_task": task_prompt,
                        "tool_executed": func.__name__,
                        "tool_arguments": kwargs,
                        "error_details": {
                            "error_code": getattr(e, "errno", type(e).__name__),
                            "message": str(e),
                        },
                    }

                    analysis = analyze_failure_deterministically(payload)

                    # 3. Build dictionary matching FailureMemory fields
                    mem_dict = {
                        "id": f"mem_{uuid.uuid4().hex[:8]}",
                        "task": task_prompt,
                        "failure": f"{analysis.fault_category}: {analysis.root_cause}",
                        "fault_category": analysis.fault_category,
                        "root_cause": analysis.root_cause,
                        "lesson": analysis.lesson,
                        "prevention": analysis.prevention_strategy,
                        "prevention_strategy": analysis.prevention_strategy,
                        "prevention_actions": analysis.prevention_actions,
                        "confidence": analysis.confidence,
                    }

                    # Filter keys to match model fields
                    valid_keys = set(FailureMemory.model_fields.keys())
                    filtered_dict = {k: v for k, v in mem_dict.items() if k in valid_keys}

                    try:
                        mem_obj = FailureMemory.model_validate(filtered_dict)
                        saved_mem, _ = self.store.merge_or_store(mem_obj)
                        print(f"✅ [MemoryGuard] Persisted failure memory (ID: {saved_mem.id})")
                    except Exception as store_err:
                        print(f"⚠️ [MemoryGuard] Store error: {store_err}")

                    raise e

            return wrapper

        return decorator
