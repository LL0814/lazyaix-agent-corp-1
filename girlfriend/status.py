"""Terminal status view for girlfriend mood values."""

from __future__ import annotations

from .state import GirlfriendStateStore


def progress_bar(value: int, minimum: int = -100, maximum: int = 100, width: int = 10) -> str:
    normalized = (value - minimum) / (maximum - minimum)
    normalized = max(0.0, min(1.0, normalized))
    filled = round(normalized * width)
    return "█" * filled + "░" * (width - filled)


def format_status(store: GirlfriendStateStore | None = None) -> str:
    store = store or GirlfriendStateStore()
    state = store.get_state()
    rows = [
        ("心情", state["mood"]),
        ("亲密度", state["affection"]),
        ("信任度", state["trust"]),
        ("吃醋值", state["jealousy"]),
    ]
    return "\n".join(
        f"{label:<4}    {progress_bar(value)}  {value}"
        for label, value in rows
    )


def main() -> None:
    print(format_status())


if __name__ == "__main__":
    main()
