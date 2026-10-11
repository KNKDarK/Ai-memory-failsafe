import json

from backend.agent.environment import SimulatedEnvironment
from backend.agent.tools import TOOL_REGISTRY, invoke_tool


def main():
    print("Initializing Simulated Environment...")
    # Pre-load some dummy data to play with
    env = SimulatedEnvironment(
        id="dev-env",
        config={"DEBUG": "true"},
        registry={"requests": "2.31.0"},
        secrets={"API_KEY": "secret-123"},
    )

    print("\n--- Agent Terminal ---")
    print(f"Available tools: {', '.join(TOOL_REGISTRY.keys())}")
    print("Type 'exit' or 'quit' to stop.")
    print("Usage: <tool_name> [json_arguments]")
    print('Example: write_file {"path": "test.txt", "content": "hello"}')

    while True:
        try:
            user_input = input("\nagent> ").strip()
            if user_input.lower() in ["exit", "quit"]:
                break
            if not user_input:
                continue

            parts = user_input.split(" ", 1)
            tool_name = parts[0]
            args_str = parts[1] if len(parts) > 1 else "{}"

            try:
                args = json.loads(args_str)
            except json.JSONDecodeError:
                print("Error: Arguments must be valid JSON.")
                continue

            result = invoke_tool(env, tool_name, args)

            if result.ok:
                print(f"✅ SUCCESS:\n{json.dumps(result.output, indent=2)}")
            else:
                print(f"❌ FAILED [{result.error_code}]: {result.error}")
                if result.metadata:
                    print(f"Metadata: {json.dumps(result.metadata, indent=2)}")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
