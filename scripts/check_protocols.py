#!/usr/bin/env python3
"""Sentinel Working Protocol checker.

Verifies, per PLAN.md §3.5 and Task 0.6:
  (a) ``TODO(review)`` markers == ``KNOWN_LIMITATIONS.md`` entries, exactly one per entry;
  (b) every ``LEARN[NN]`` in code has a ``LEARN_INDEX.md`` row and vice versa;
  (c) LEARN numbering is gapless and starts at ``01``;
  (d) QS-1 structural lint: every ``LEARN`` block has all four mandatory fields.

Exits non-zero on any violation. Wired as a pre-commit ``local`` hook
(always_run, pass_filenames=false).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_REQUIRED_FIELDS = ("Why this way:", "Good sides:", "Drawbacks:", "Concept:")
_SKIP_DIRS = {
    ".git",
    ".venv",
    ".uv-cache",
    ".uv-python",
    ".pre-commit-cache",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".cache",
    "__pycache__",
    "node_modules",
    ".idea",
    ".vscode",
    ".hg",
    ".svn",
}
_LEARN_HEADER_RE = re.compile(r"^#\s*LEARN\[(\d{2})\]:\s*(.*)$")
_FIELD_RE = re.compile(r"^#\s*(Why this way:|Good sides:|Drawbacks:|Concept:|See also:)\s*")
_LEARN_SUFFIXES = (".py", ".yaml", ".yml", ".toml")
_LEARN_NAMES = (".gitignore",)
_TODO_SUFFIXES = (".py", ".yaml", ".yml")
_KNOWN_HEAD_RE = re.compile(r"^##\s*L(\d+)\b", flags=re.MULTILINE)
_CODE_TODO_RE = re.compile(r"^\s*#.*TODO\(review\):")


def _iter_files() -> list[Path]:
    """Yield every file under ROOT, skipping version-control and tool caches."""
    out: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        out.append(path)
    return out


def _is_learn_file(path: Path) -> bool:
    return path.name in _LEARN_NAMES or path.suffix in _LEARN_SUFFIXES


def _scan_learn_blocks() -> list[dict[str, object]]:
    """Return one entry per ``# LEARN[NN]:`` block found in code/config files."""
    blocks: list[dict[str, object]] = []
    for path in _iter_files():
        if not _is_learn_file(path):
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        i = 0
        while i < len(lines):
            match = _LEARN_HEADER_RE.match(lines[i])
            if not match:
                i += 1
                continue
            num = match.group(1)
            title = match.group(2)
            fields: set[str] = set()
            i += 1
            while i < len(lines) and lines[i].startswith("#"):
                fm = _FIELD_RE.match(lines[i])
                if fm:
                    fields.add(fm.group(1))
                i += 1
            blocks.append(
                {
                    "num": num,
                    "title": title,
                    "path": str(path.relative_to(ROOT)),
                    "fields": fields,
                }
            )
    return blocks


def _index_learn_nums() -> set[str]:
    idx = ROOT / "LEARN_INDEX.md"
    if not idx.exists():
        return set()
    nums: set[str] = set()
    for line in idx.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("|"):
            m = re.search(r"LEARN\[(\d{2})\]", line)
            if m:
                nums.add(m.group(1))
    return nums


def _known_limitations() -> tuple[int, int, list[int]] | None:
    """Return (entry_count, inline_marker_count, markers_per_block), or None if file missing."""
    kl = ROOT / "KNOWN_LIMITATIONS.md"
    if not kl.exists():
        return None
    text = kl.read_text(encoding="utf-8")
    entries = _KNOWN_HEAD_RE.findall(text)
    minus_preamble = re.split(r"^##\s*L\d+\b", text, flags=re.MULTILINE)[1:]
    per_block = [block.count("TODO(review)") for block in minus_preamble]
    return len(entries), sum(per_block), per_block


def _code_todo_count() -> int:
    """Count comment-form review markers in code (*.py/*.yaml/*.yml).

    Only a line that is a real ``# TODO(review): ...`` comment counts; prose/doco references
    to the marker syntax do not (this file itself documents the rules in prose).
    """
    total = 0
    for path in _iter_files():
        if path.suffix in _TODO_SUFFIXES:
            for line in path.read_text(encoding="utf-8").splitlines():
                if _CODE_TODO_RE.match(line):
                    total += 1
    return total


def _fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)


def main() -> int:
    ok = True

    # ---- LEARN / QS-1 ----
    blocks = _scan_learn_blocks()
    code_nums = [str(b["num"]) for b in blocks]

    if len(code_nums) != len(set(code_nums)):
        _fail(f"duplicate LEARN numbers in code: {code_nums}")
        ok = False

    int_nums = sorted(int(n) for n in code_nums)
    expected = list(range(1, len(int_nums) + 1))
    if int_nums != expected:
        _fail(f"LEARN numbering not gapless from 01: got {int_nums}, expected {expected}")
        ok = False

    for block in blocks:
        fields = block["fields"]
        missing = [f for f in _REQUIRED_FIELDS if f not in fields]
        if missing:
            _fail(f"LEARN[{block['num']}] @ {block['path']} missing QS-1 field(s): {missing}")
            ok = False

    index_nums = _index_learn_nums()
    if set(code_nums) != index_nums:
        _fail(
            f"LEARN code/index mismatch: code={sorted(set(code_nums))} index={sorted(index_nums)}"
        )
        ok = False

    # ---- KNOWN_LIMITATIONS / deferred-work ----
    known = _known_limitations()
    if known is None:
        _fail("KNOWN_LIMITATIONS.md not found")
        ok = False
    else:
        entries, inline, per_block = known
        code_todo = _code_todo_count()
        if entries == 0:
            _fail("no KNOWN_LIMITATIONS.md entries found")
            ok = False
        if code_todo + inline != entries:
            _fail(
                "TODO(review) marker count mismatch: "
                f"entries={entries}, code={code_todo}, inline={inline}"
            )
            ok = False
        over = [i for i, c in enumerate(per_block) if c > 1]
        if over:
            _fail(f"KNOWN_LIMITATIONS entry block(s) with more than one review marker: {over}")
            ok = False

    if ok:
        print(
            f"protocol checker: PASS "
            f"(learn_blocks={len(code_nums)}, entries={known[0] if known else 0})"
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
