#!/usr/bin/env python3
"""Context 模块四层渐进压缩演示。

每层用独立的 Context 实例，清晰展示触发条件和效果。
运行：uv run python demo_compression.py
"""

from context import Context


def show(ctx, label):
    """打印当前 context 状态快照。"""
    s = ctx.snapshot()
    st = s.token_stats
    c = s.compression
    flags = (
        f"snip={c.snip_triggered} micro={c.micro_triggered} "
        f"collapse={c.collapse_triggered} auto={c.auto_triggered}"
    )
    print(f"\n[{label}]")
    print(
        f"  turns={len(s.recent_turns)}  "
        f"tokens={st.estimated_tokens}/{st.context_limit}  "
        f"usage={st.usage_pct:.1f}%  level={st.warning_level}"
    )
    print(f"  flags: {flags}")
    if c.compact_history:
        events = [
            (
                e.layer,
                f"{e.usage_before:.0f}->{e.usage_after:.0f}",
                f"removed={e.turns_removed}",
            )
            for e in c.compact_history
        ]
        print(f"  events: {events}")
    # 展示最近 6 条 turn 的角色和 full_content 状态
    for t in s.recent_turns[-6:]:
        if t.full_content is None:
            full_state = "(cleared)"
        elif len(t.full_content) > 30:
            full_state = f"(full: {len(t.full_content)} chars)"
        else:
            full_state = t.full_content
        preview = (t.content_preview or "")[:30]
        print(f"    [{t.turn_id}] {t.role:9} preview={preview!r:32} full={full_state}")


def demo_snip():
    print("\n" + "=" * 70)
    print("Demo 1: SnipCompact (阈值 50%) - 删除安全旧 turn")
    print("=" * 70)
    ctx = Context(config={"CONTEXT_LIMIT": 100, "MAX_RECENT_TURNS": 50})
    show(ctx, "初始")
    print("\n→ 加 4 条 100 字符 user turn (各 25 tokens, 第 2 条达 50%)")
    for _ in range(4):
        ctx.update("a" * 100)
    show(ctx, "4 条 turn 后 (期望: snip 触发, 删除最旧的非保护 turn)")


def demo_snip_protects_keywords():
    print("\n" + "=" * 70)
    print("Demo 2: SnipCompact 保护关键词 (write_file/error 等)")
    print("=" * 70)
    # 禁用 collapse/auto, 只观察 snip 的保护行为
    ctx = Context(
        config={
            "CONTEXT_LIMIT": 100,
            "MAX_RECENT_TURNS": 50,
            "COLLAPSE_THRESHOLD": 99999.0,
            "AUTO_THRESHOLD": 99999.0,
        }
    )
    print("→ 先加 3 条普通 100 字符 turn")
    for _ in range(3):
        ctx.update("a" * 100)
    print("→ 加 1 条含 'write_file' 的 turn (受保护, 在中间)")
    ctx.update("write_file test.txt hello")
    print("→ 再加 4 条普通 100 字符 turn 触发 snip")
    for _ in range(4):
        ctx.update("a" * 100)
    show(ctx, "结果 (期望: write_file turn 仍保留在 recent_turns 中)")


def demo_micro():
    print("\n" + "=" * 70)
    print("Demo 3: MicroCompact (阈值 65%) - 清空旧 tool turn 的 full_content")
    print("=" * 70)
    # 禁用其他层，只观察 micro
    ctx = Context(
        config={
            "CONTEXT_LIMIT": 50,
            "MAX_RECENT_TURNS": 50,
            "SNIP_THRESHOLD": 99999.0,
            "MICRO_THRESHOLD": 50.0,
            "COLLAPSE_THRESHOLD": 99999.0,
            "AUTO_THRESHOLD": 99999.0,
        }
    )
    print("→ 加 1 条 user turn")
    ctx.update("hello")
    print("→ 加 1 条长 full_content 的 tool turn (100 字符)")
    ctx.update_with_result(
        {
            "tool_name": "weather",
            "params": {"city": "Beijing"},
            "result_preview": "sunny" + "x" * 95,
        }
    )
    print("→ 再加 4 条 user turn, 让 tool turn 移出 safe 区 (最近 3 条外)")
    for _ in range(4):
        ctx.update("b" * 50)
    show(ctx, "结果 (期望: tool turn 的 full_content 被清空 → (cleared))")


def demo_collapse():
    print("\n" + "=" * 70)
    print("Demo 4: ContextCollapse (阈值 80%) - 旧 turn 合并为 summary")
    print("=" * 70)
    ctx = Context(
        config={
            "CONTEXT_LIMIT": 100,
            "MAX_RECENT_TURNS": 50,
            "SNIP_THRESHOLD": 99999.0,
            "MICRO_THRESHOLD": 99999.0,
            "COLLAPSE_THRESHOLD": 50.0,
            "AUTO_THRESHOLD": 99999.0,
        }
    )
    print("→ 加 8 条 user turn, 内容含 topic 关键词和引号实体")
    ctx.update("北京天气怎么样 'Beijing'")
    ctx.update("calculate 1+1 'result'")
    for i in range(6):
        ctx.update(f"普通消息 number {i} " + "y" * 80)
    show(ctx, "结果 (期望: 出现 role=system 的 summary turn, 含 topics/entities)")


def demo_auto():
    print("\n" + "=" * 70)
    print("Demo 5: AutoCompact (阈值 90%, stub 模式)")
    print("=" * 70)
    ctx = Context(
        config={
            "CONTEXT_LIMIT": 50,
            "MAX_RECENT_TURNS": 50,
            "SNIP_THRESHOLD": 99999.0,
            "MICRO_THRESHOLD": 99999.0,
            "COLLAPSE_THRESHOLD": 99999.0,
            "AUTO_THRESHOLD": 50.0,
        }
    )
    print("→ 加 10 条 100 字符 turn")
    for _ in range(10):
        ctx.update("a" * 100)
    show(ctx, "结果 (期望: auto_triggered=True, notes 含 'not available')")
    auto_events = [e for e in ctx._state.compression.compact_history if e.layer == "auto"]
    if auto_events:
        print(f"  auto 事件 notes: {auto_events[0].notes!r}")


def demo_force():
    print("\n" + "=" * 70)
    print("Demo 6: 手动 compact(force=True) - 强制触发所有层")
    print("=" * 70)
    ctx = Context(
        config={
            "CONTEXT_LIMIT": 100,
            "MAX_RECENT_TURNS": 50,
            "SNIP_THRESHOLD": 99999.0,
            "MICRO_THRESHOLD": 99999.0,
            "COLLAPSE_THRESHOLD": 99999.0,
            "AUTO_THRESHOLD": 99999.0,
        }
    )
    print("→ 加 4 条 100 字符 turn (阈值设极大值, 不会自动触发)")
    for _ in range(4):
        ctx.update("a" * 100)
    show(ctx, "自动触发前 (期望: 所有 flag 为 False)")
    print("\n→ 调用 ctx.compact(force=True)")
    ctx.compact(force=True)
    show(ctx, "force 后 (期望: snip/micro/collapse/auto 都触发)")


def demo_all_layers():
    print("\n" + "=" * 70)
    print("Demo 7: 综合演示 - 默认配置下逐条加 turn, 观察四层依次触发")
    print("=" * 70)
    ctx = Context(config={"CONTEXT_LIMIT": 100, "MAX_RECENT_TURNS": 50})
    show(ctx, "初始")
    print("\n→ 逐条加 turn, 交替 user/tool, 每次报告新触发的压缩事件")
    last_event_count = 0
    for i in range(15):
        if i % 3 == 1:
            ctx.update_with_result(
                {
                    "tool_name": "weather",
                    "params": {"city": "Beijing"},
                    "result_preview": "sunny and warm with light rain in the evening" + "x" * 50,
                }
            )
        else:
            ctx.update(f"message {i} " + "x" * 80)
        s = ctx.snapshot()
        new_events = s.compression.compact_history[last_event_count:]
        if new_events:
            for e in new_events:
                print(
                    f"  turn {i+1}: usage={s.token_stats.usage_pct:5.1f}%  "
                    f"→ 触发 {e.layer}! (before={e.usage_before:.0f}% after={e.usage_after:.0f}%)"
                )
            last_event_count = len(s.compression.compact_history)
    show(ctx, "15 条 turn 后最终状态")


def main():
    print("=" * 70)
    print("Context 模块四层渐进压缩演示")
    print("=" * 70)
    print("默认阈值: snip=50%  micro=65%  collapse=80%  auto=90%")
    print("token 估算: ceil(字符数 / 4)")
    print("SAFE_TURNS=3 (每层保护最近 3 条 turn 不被压缩)")

    demo_snip()
    demo_snip_protects_keywords()
    demo_micro()
    demo_collapse()
    demo_auto()
    demo_force()
    demo_all_layers()


if __name__ == "__main__":
    main()
