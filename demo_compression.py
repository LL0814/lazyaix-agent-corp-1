#!/usr/bin/env python3
"""Context four-layer compaction demo.

Run: uv run python demo_compression.py
"""

from context import Context
from context.compaction import reactive_compact
from context.utils import estimate_size


def show(ctx, label):
    s = ctx.snapshot()
    c = s.compression
    print(f"\n[{label}]")
    print(f"  turns={len(s.recent_turns)}  chars={sum(len(str(m)) for m in ctx.get_messages())}")
    print(
        f"  flags: budget={c.tool_result_budget_triggered} "
        f"snip={c.snip_triggered} micro={c.micro_triggered} "
        f"compact={c.compact_history_triggered}"
    )
    if c.compact_history:
        print(f"  events: {[(e.layer, e.usage_before, e.usage_after) for e in c.compact_history]}")
    for t in s.recent_turns[-6:]:
        preview = (t.content_preview or "")[:40]
        full = "(cleared)" if t.full_content is None else f"({len(t.full_content)} chars)"
        print(f"    [{t.turn_id}] {t.role:9} {preview!r:42} full={full}")


def demo_l3():
    print("\n=== Demo L3: tool_result_budget ===")
    ctx = Context(config={"TOOL_RESULT_BUDGET": 200_000})
    ctx.update_with_result({
        "tool_name": "bash",
        "params": {"cmd": "cat big.log"},
        "result_preview": "x" * 300_000,
    })
    show(ctx, "500KB tool result persisted")


def demo_l1():
    print("\n=== Demo L1: snip_compact ===")
    ctx = Context(config={"KEEP_RECENT_MESSAGES": 50})
    for i in range(100):
        ctx.update(f"message {i}")
    show(ctx, "100 messages snipped to ~50")


def demo_l2():
    print("\n=== Demo L2: micro_compact ===")
    ctx = Context(config={"KEEP_RECENT_TOOL_RESULTS": 3})
    for i in range(5):
        ctx.update_with_result({
            "tool_name": "weather",
            "params": {"city": "Beijing"},
            "result_preview": f"result {i}: " + "x" * 200,
        })
    show(ctx, "older tool results compacted")


def demo_l4():
    print("\n=== Demo L4: compact_history ===")
    ctx = Context(config={"CONTEXT_LIMIT": 1000})
    big = "x" * 500
    for i in range(50):
        ctx.update(f"turn {i} " + big)
    show(ctx, "history compacted to summary")


def demo_reactive():
    print("\n=== Demo reactive_compact ===")
    messages = [{"role": "user", "content": f"msg {i}"} for i in range(30)]
    result = reactive_compact(messages)
    print(f"  before: {len(messages)} messages, after: {len(result)} messages")


def main():
    demo_l3()
    demo_l1()
    demo_l2()
    demo_l4()
    demo_reactive()


if __name__ == "__main__":
    main()
