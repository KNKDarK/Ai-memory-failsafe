# scripts/test_payload.py
import json

from backend.agent.analyzer import analyze_failure_deterministically

payload = {
    "original_task": "Deploy the web service by reading the production configuration file to extract the database URI.",
    "tool_executed": "read_file",
    "tool_arguments": {"path": "config/prod.json"},
    "error_details": {
        "error_code": "ENOENT",
        "message": "File not found. The path 'config/prod.json' does not exist in the current working directory.",
    },
}

result = analyze_failure_deterministically(payload)
print(json.dumps(result.model_dump(), indent=2))
