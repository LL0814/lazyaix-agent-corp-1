#!/usr/bin/env python3
"""Entry point that manages the agent REPL loop.

The loop is responsible for:
- Loading Context and Memory modules (with stub fallback).
- Keeping Context and Memory alive across turns so state can persist.
- Creating a fresh Agent instance on every turn with the current
  Context and Memory, demonstrating dynamic assembly.
- Running the synchronous CLI REPL loop.
"""

import os
import queue
import sys
import threading

from agent import Agent

try:
    from girlfriend import GirlfriendEngine, HumanizedRenderer, ProactiveScheduler
except ImportError:
    GirlfriendEngine = None
    HumanizedRenderer = None
    ProactiveScheduler = None


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
    renderer = HumanizedRenderer() if HumanizedRenderer is not None else None
    proactive_scheduler = None
    proactive_printer_stop = threading.Event()

    output_queue: queue.Queue[str] = queue.Queue()

    def girlfriend_enabled() -> bool:
        return os.environ.get("ENABLE_GIRLFRIEND_MODE", "true").lower() == "true"

    def print_text(text: str, emotional: bool = True) -> None:
        if renderer is None:
            print(text, end="", flush=True)
            return
        renderer.write(text, emotional=emotional)

    def proactive_printer() -> None:
        while not proactive_printer_stop.is_set():
            try:
                message = output_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            sys.stdout.write("\n[她] ")
            sys.stdout.flush()
            print_text(message, emotional=True)
            sys.stdout.write("\n> ")
            sys.stdout.flush()
            output_queue.task_done()

    if girlfriend_enabled() and GirlfriendEngine is not None and ProactiveScheduler is not None:
        proactive_scheduler = ProactiveScheduler(GirlfriendEngine(), output_queue)
        proactive_scheduler.start()
        threading.Thread(
            target=proactive_printer,
            name="girlfriend-proactive-printer",
            daemon=True,
        ).start()

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
            emotional = (
                agent.is_emotional_turn(user_input)
                if hasattr(agent, "is_emotional_turn")
                else False
            )
            if hasattr(agent, "process_turn_stream"):
                chunks = []
                for chunk in agent.process_turn_stream(user_input):
                    chunks.append(str(chunk))
                    print_text(chunk, emotional=emotional)
                print()
                response_text = "".join(chunks)
            else:
                response = agent.process_turn(user_input)
                response_text = str(response)
                print_text(response_text, emotional=emotional)
                sys.stdout.write("\n")
                sys.stdout.flush()
            follow_ups = (
                agent.girlfriend_follow_ups(user_input, response_text)
                if hasattr(agent, "girlfriend_follow_ups")
                else []
            )
            for message in follow_ups:
                sys.stdout.write("[她] ")
                sys.stdout.flush()
                print_text(message, emotional=True)
                sys.stdout.write("\n")
                sys.stdout.flush()
    finally:
        proactive_printer_stop.set()
        if proactive_scheduler is not None:
            proactive_scheduler.stop()
        shutdown = getattr(memory, "shutdown", None)
        if callable(shutdown):
            shutdown(wait=False)


if __name__ == "__main__":
    run_loop()
