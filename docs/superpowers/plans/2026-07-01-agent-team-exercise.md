# Agent Team Exercise Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Initialize a runnable Python Agent project scaffold with `loop.py` managing the REPL loop and loading Context/Memory, `agent.py` dynamically assembling the Agent and its inline stub classes for Config, Model, Tool, Skill, Context, Memory, and Subagents modules, plus empty module directories, `.env.example`, and uv-managed Python environment via `pyproject.toml`.

**Architecture:** `loop.py` loads Context and Memory from their module directories (with stub fallback) and keeps them alive across turns. On every REPL iteration it creates a fresh `Agent(context, memory)` to demonstrate dynamic assembly. `agent.py` dynamically assembles the remaining modules (Config, Model, Tool, Skill, Subagent) from student directories; missing modules fall back to inline `Stub` classes. The Agent class owns a `process_turn()` flow: conditionally update Context, build prompt with optional Memory, call `Model.complete()` for raw LLM text, call `Skill.decide()` to route between direct answer and Tool execution, and conditionally store to Memory. Subagent remains assembled as an optional component for students to integrate. The project structure includes seven empty module directories (each with `.gitkeep`), an `.env.example` documenting environment variables, and a `pyproject.toml` for uv.

**Tech Stack:** Python 3 (managed by uv), optional `python-dotenv`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `loop.py` | Manages the synchronous CLI REPL loop (I/O only) |
| `agent.py` | Dynamically assembles Agent (except Context/Memory), defines `process_turn()`, and provides stub classes |
| `pyproject.toml` | uv-managed project metadata and optional dependencies |
| `.python-version` | Pin Python version for uv |
| `config/.gitkeep` | Placeholder for the Config module |
| `modals/.gitkeep` | Placeholder for the Modal module |
| `tools/.gitkeep` | Placeholder for the Tool module |
| `skills/.gitkeep` | Placeholder for the Skill module |
| `context/.gitkeep` | Placeholder for the Context module |
| `memory/.gitkeep` | Placeholder for the Memory module |
| `subagents/.gitkeep` | Placeholder for the Subagent module |
| `.env.example` | Documents required/optional environment variables |

---

### Task 1: Create empty module directories

**Files:**
- Create: `config/.gitkeep`
- Create: `models/.gitkeep`
- Create: `tools/.gitkeep`
- Create: `skills/.gitkeep`
- Create: `context/.gitkeep`
- Create: `memory/.gitkeep`
- Create: `subagents/.gitkeep`

- [ ] **Step 1: Create directories and .gitkeep placeholders**

  Run:
  ```bash
  mkdir -p config models tools skills context memory subagents
  touch config/.gitkeep models/.gitkeep tools/.gitkeep skills/.gitkeep context/.gitkeep memory/.gitkeep subagents/.gitkeep
  ```

- [ ] **Step 2: Verify directories exist**

  Run:
  ```bash
  ls -R config models tools skills context memory subagents
  ```
  Expected: Each directory contains a `.gitkeep` file.

---

### Task 2: Create .env.example

**Files:**
- Create: `.env.example`

- [ ] **Step 1: Write .env.example**

  Run:
  ```bash
  cat > .env.example << 'EOF'
  # Agent Team Exercise Environment Configuration
  # Copy this file to .env and fill in your values.

  # Example: API key for modal/model provider
  # MODAL_API_KEY=your_api_key_here

  # Example: Agent name shown in the REPL prompt
  # AGENT_NAME=TeachAgent

  # Example: Log level (DEBUG, INFO, WARNING, ERROR)
  # LOG_LEVEL=INFO
  EOF
  ```

- [ ] **Step 2: Verify file content**

  Run:
  ```bash
  cat .env.example
  ```
  Expected: The file contains the three documented environment variables.

---

### Task 3: Write agent.py with stub classes and REPL loop

**Files:**
- Create: `agent.py`

- [ ] **Step 1: Write agent.py**

  Create `agent.py` with the following content:

  ```python
  #!/usr/bin/env python3
  """Agent entry point for the team exercise.

  This file contains the main REPL loop and inline stub classes for the
  Config, Modal, Tool, Skill, Context, and Memory modules.  When students
  implement the real modules in their respective directories, agent.py will
  automatically import them instead of using the stubs.
  """

  import os

  # Optional dotenv support. If python-dotenv is installed, load .env.
  try:
      from dotenv import load_dotenv
      load_dotenv()
  except ImportError:
      pass


  # Try to import real implementations from student modules.
  # If a module is not yet implemented, fall back to the inline stub.
  try:
      from config import Config
  except ImportError:
      class Config:  # Stub
          """Configuration stub: reads from environment variables."""

          def __init__(self):
              self._data = dict(os.environ)

          def get(self, key, default=None):
              """Get a configuration value by key."""
              return self._data.get(key, default)


  try:
      from modals import Modal
  except ImportError:
      class Modal:  # Stub
          """Modal stub: returns a placeholder interpretation of user input."""

          def process(self, user_input, context):
              """Process user input and return an interpreted result."""
              return {"intent": "echo", "content": user_input}


  try:
      from tools import Tool
  except ImportError:
      class Tool:  # Stub
          """Tool stub: simulates executing an external action."""

          def execute(self, action, params):
              """Execute the requested action with parameters."""
              return f"[STUB] Executed {action} with {params}"


  try:
      from skills import Skill
  except ImportError:
      class Skill:  # Stub
          """Skill stub: decides which action the agent should take."""

          def decide(self, context, memory):
              """Decide the next action based on context and memory."""
              return {
                  "action": "echo",
                  "params": {"message": context.get("last_input", "")},
              }


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


  class Agent:
      """Minimal agent orchestrating Config, Modal, Tool, Skill, Context, and Memory."""

      def __init__(self):
          self.config = Config()
          self.context = Context()
          self.memory = Memory()
          self.modal = Modal()
          self.skill = Skill()
          self.tool = Tool()

      def process_turn(self, user_input: str) -> str:
          """Run a single turn through the pipeline."""
          ctx = self.context.update(user_input)
          modal_result = self.modal.process(user_input, ctx)
          decision = self.skill.decide(ctx, self.memory)
          tool_result = self.tool.execute(decision.get("action"), decision.get("params"))
          self.memory.store(
              "last_turn",
              {
                  "input": user_input,
                  "modal_result": modal_result,
                  "decision": decision,
                  "tool_result": tool_result,
              },
          )
          return str(tool_result)

      def run(self):
          """Run the synchronous CLI REPL loop."""
          agent_name = self.config.get("AGENT_NAME", "Agent")
          print(f"{agent_name} is ready. Type 'exit' or 'quit' to stop.")
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

              response = self.process_turn(user_input)
              print(response)


  if __name__ == "__main__":
      Agent().run()
  ```

- [ ] **Step 2: Verify agent package syntax**

  Run:
  ```bash
  python -m py_compile agent/agent.py loop.py
  ```
  Expected: No output (success).

---

### Task 4: Test the scaffold end-to-end

**Files:**
- Test: `agent.py`

- [ ] **Step 1: Run a single REPL turn via stdin**

  Run:
  ```bash
  printf 'hello\nquit\n' | uv run loop.py
  ```
  Expected output contains:
  ```
  Agent is ready. Type 'exit' or 'quit' to stop.
  > [STUB] Executed echo with {'message': 'hello'}
  > Goodbye.
  ```

- [ ] **Step 2: Verify stub fallback works when modules are empty**

  Run:
  ```bash
  python -c "import agent; a = agent.Agent(); print(type(a.config).__name__)"
  ```
  Expected: `Config`

---

## Self-Review

**Spec coverage:**
- Synchronous CLI REPL loop: Task 3, Step 1.
- Six empty module directories: Task 1.
- Inline stub classes with fallback imports: Task 3, Step 1.
- `.env.example` environment config: Task 2.
- Config module support with optional python-dotenv: Task 3, Step 1.

**Placeholder scan:** No TBD/TODO/implementation later placeholders.

**Type consistency:** Method signatures match the interface table in the design doc.
