
#!/usr/bin/env python3
"""Entry point that manages the agent REPL loop.

The loop is responsible for:
- Loading Context and Memory modules (with stub fallback).
- Keeping Context and Memory alive across turns so state can persist.
- Creating a fresh Agent instance on every turn with the current
  Context and Memory, demonstrating dynamic assembly.
- Running the synchronous CLI REPL loop.
"""

from agent import Agent


try:
    from context import Context
except ImportError:
    class Context:  # Stub
        """Context stub: maintains the current conversation context."""

        def __init__(self):
            self._state = {}

        def update(self, user_input):
            """Update context with new user input."""
            self._state["last_input"] = user_input
            return self._state

        def get(self):
            """Return the current context state."""
            return self._state


try:
    from memory import Memory
except ImportError:
    class Memory:  # Stub
        """Memory stub: simple key-value storage for the agent."""

        def __init__(self):
            self._store = {}

        def store(self, key, value):
            """Store a value under the given key."""
            self._store[key] = value

        def retrieve(self, key):
            """Retrieve a value by key."""
            return self._store.get(key)


def _handle_model_command(user_input: str, model) -> bool:
    """Handle the /model command. Return True if handled, False otherwise."""
    if not user_input.startswith("/model"):
        return False

    parts = user_input.split(maxsplit=1)
    if len(parts) == 1:
        new_spec = input("请输入模型，格式 provider:model：").strip()
    else:
        new_spec = parts[1].strip()

    if not new_spec:
        print("[loop] 未提供模型标识，保持当前模型不变。")
        return True

    if model.switch(new_spec):
        print(f"[loop] 已切换至模型：{model.provider_name}:{model.model_name}")
    else:
        print("[loop] 模型切换失败，保持当前模型不变。")
    return True


def run_loop() -> None:
    """Run the synchronous CLI REPL loop."""
    context = Context()
    memory = Memory()
    # Create a single Model instance so runtime switches persist across turns.
    from models import Model

    model = Model()
    # Diagnostic: show which .env was loaded and the current key status.
    try:
        from dotenv import find_dotenv

        env_path = find_dotenv()
    except Exception:
        env_path = ""
    if not env_path:
        from pathlib import Path

        env_path = str(Path(".env").resolve())
    key_status = "已配置" if model.api_key else "未配置"

    # Use a throw-away Agent just to read the display name from config.
    print(f"{Agent(context, memory, model=model).name} is ready.")
    print(f"[loop] .env 路径：{env_path}")
    print(f"[loop] 当前模型：{model.provider_name}:{model.model_name}，Key 状态：{key_status}")
    print("输入 /model provider:model 可切换模型，'exit' 或 'quit' 退出。")
    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break

        # Handle meta commands before sending to the agent.
        if _handle_model_command(user_input, model):
            continue

        # Recreate the Agent each turn with the current Context and Memory,
        # but reuse the same Model instance to preserve runtime switches.
        agent = Agent(context=context, memory=memory, model=model)
        response = agent.process_turn(user_input)
        print(response)


if __name__ == "__main__":
    run_loop()
