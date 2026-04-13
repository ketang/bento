#!/usr/bin/env python3
"""Compare char/4 token estimate vs tiktoken for markdown files.

Usage:
    scripts/token-count-compare.py FILE [FILE ...]
    scripts/token-count-compare.py $(find ~/project -name '*.md')

Output (wc-style, right-aligned):
    char/4  tiktoken    delta    pct%  filename
"""
from __future__ import annotations

import sys
from pathlib import Path

ENCODING_NAME = "cl100k_base"
CHARS_PER_TOKEN_ESTIMATE = 4  # Anthropic's rough proxy: 1 token ≈ 4 characters
TIKTOKEN_MISSING_EXIT_CODE = 2
NO_ARGS_EXIT_CODE = 2


def load_tiktoken():
    try:
        import tiktoken
    except ImportError:
        sys.stderr.write(
            "error: tiktoken not installed\n"
            "  install with: pip install tiktoken  (or: pipx install tiktoken)\n"
        )
        sys.exit(TIKTOKEN_MISSING_EXIT_CODE)
    return tiktoken


def measure(path: Path, enc) -> tuple[int, int]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError) as err:
        sys.stderr.write(f"skip: {path}: {err}\n")
        return -1, -1
    return len(text) // CHARS_PER_TOKEN_ESTIMATE, len(enc.encode(text))


def fmt_row(char4: int, tik: int, name: str) -> str:
    delta = tik - char4
    pct = (delta / tik * 100) if tik else 0.0
    return f"{char4:>8d} {tik:>9d} {delta:>+8d} {pct:>+7.1f}%  {name}"


def main(argv: list[str]) -> int:
    if not argv:
        sys.stderr.write(__doc__ or "")
        return NO_ARGS_EXIT_CODE

    tiktoken = load_tiktoken()
    enc = tiktoken.get_encoding(ENCODING_NAME)
    header = f"{'char/4':>8s} {'tiktoken':>9s} {'delta':>8s} {'pct%':>8s}  filename"
    print(header)
    print("-" * len(header))

    rows: list[tuple[int, int, str]] = []
    for arg in argv:
        path = Path(arg)
        char4, tik = measure(path, enc)
        if char4 < 0:
            continue
        rows.append((char4, tik, str(path)))

    rows.sort(key=lambda r: r[0])

    for char4, tik, name in rows:
        print(fmt_row(char4, tik, name))

    if len(rows) > 1:
        total_char4 = sum(r[0] for r in rows)
        total_tik = sum(r[1] for r in rows)
        print("-" * len(header))
        print(fmt_row(total_char4, total_tik, f"total ({len(rows)} files)"))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
