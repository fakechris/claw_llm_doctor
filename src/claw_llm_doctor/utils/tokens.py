"""Token counting utilities.

Supports two strategies:
- 'char': fast character-based estimation (~4 chars per token)
- 'tiktoken': accurate counting via tiktoken (requires optional dependency)
"""

from __future__ import annotations

import json
from typing import Any

CHARS_PER_TOKEN = 4  # rough estimate for English text


def estimate_tokens_char(text: str) -> int:
    """Fast character-based token estimate."""
    return max(1, len(text) // CHARS_PER_TOKEN)


def estimate_tokens_tiktoken(text: str, model: str = "gpt-4") -> int:
    """Accurate token count using tiktoken. Falls back to char estimate."""
    try:
        import tiktoken

        enc = tiktoken.encoding_for_model(model)
        return len(enc.encode(text))
    except Exception:
        return estimate_tokens_char(text)


def count_tokens(value: Any, method: str = "char") -> int:
    """Count tokens for an arbitrary value (string, list, dict, etc.).

    Serialises non-string values to JSON first.
    """
    if value is None:
        return 0
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False)

    if method == "tiktoken":
        return estimate_tokens_tiktoken(text)
    return estimate_tokens_char(text)


def format_tokens(n: int) -> str:
    """Human-friendly token count string."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)
