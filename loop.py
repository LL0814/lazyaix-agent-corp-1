#!/usr/bin/env python3
"""Entry point that manages the agent REPL loop.

The loop is responsible for:
- Loading Context and Memory modules (with stub fallback).
- Keeping Context and Memory alive across turns so state can persist.
- Creating a fresh Agent instance on every turn with the current
  Context and Memory, demonstrating dynamic assembly.
- Running the synchronous CLI REPL loop.
"""

import asyncio

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


def run_loop() -> None:
    """Run the synchronous CLI REPL loop."""
    context = Context()
    memory = Memory()
    # Use a throw-away Agent just to read the display name from config.
    print(f"{Agent(context, memory).name} is ready. Type 'exit' or 'quit' to stop.")
    try:
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

            # Recreate the Agent each turn with the current Context and Memory.
            agent = Agent(context=context, memory=memory)
            response = agent.process_turn(user_input)
            print(response)
    finally:
        # Ensure any lingering asyncio tasks from event-driven turns are cleaned up.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.stop()
        except RuntimeError:
            pass


if __name__ == "__main__":
    run_loop()
