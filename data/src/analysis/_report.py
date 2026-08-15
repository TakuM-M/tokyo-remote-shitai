"""レポート表示の共通処理（analysis 内部用）。

日本語は端末上で半角の2倍の幅を占めるため、文字数で桁を揃えると列がずれる。
ここでは文字数ではなく表示幅で揃える。
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Iterable, Sequence

# East Asian Width が W（全角）/ F（全角形）の文字を2幅として数える
_WIDE = ("W", "F")


def width(text: str) -> int:
    """端末上の表示幅（半角=1, 全角=2）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in _WIDE else 1 for ch in text)


def pad(text: str, size: int, align: str = "left") -> str:
    space = " " * max(size - width(text), 0)
    return space + text if align == "right" else text + space


def truncate(text: str, size: int) -> str:
    """表示幅が size に収まるよう末尾を詰める。"""
    if width(text) <= size:
        return text
    out = ""
    for ch in text:
        if width(out) + width(ch) > size - 1:
            break
        out += ch
    return out + "…"


def truncate_left(text: str, size: int) -> str:
    """表示幅が size に収まるよう先頭を詰める。末尾（ファイル名）を残したいとき用。"""
    if width(text) <= size:
        return text
    out = ""
    for ch in reversed(text):
        if width(out) + width(ch) > size - 1:
            break
        out = ch + out
    return "…" + out


def heading(title: str) -> None:
    print()
    print(title)
    print("-" * width(title))


def print_table(
    headers: Sequence[str],
    rows: Iterable[Sequence[str]],
    aligns: Sequence[str] | None = None,
    empty: str = "（該当なし）",
) -> None:
    """表示幅を揃えて表を出す。セルはすべて文字列で渡す。"""
    body = [list(r) for r in rows]
    if not body:
        print(f"  {empty}")
        return
    align_list = list(aligns or ["left"] * len(headers))
    sizes = [max([width(h)] + [width(r[i]) for r in body]) for i, h in enumerate(headers)]

    def line(cells: Sequence[str]) -> str:
        pairs = zip(cells, sizes, align_list, strict=True)
        return "  ".join(pad(c, s, a) for c, s, a in pairs).rstrip()

    print(line(headers))
    print("  ".join("-" * s for s in sizes))
    for row in body:
        print(line(row))


def print_list(items: Iterable[str], limit: int | None = None, indent: str = "  - ") -> None:
    """箇条書き。limit を超える分は件数だけ示す。"""
    items = list(items)
    if not items:
        print("  （該当なし）")
        return
    shown = items if limit is None else items[:limit]
    for item in shown:
        print(f"{indent}{item}")
    if len(items) > len(shown):
        print(f"{indent}ほか {len(items) - len(shown)} 件")


def join_names(names: Iterable[str], limit: int = 6) -> str:
    """名前の並びを1行に収める。多いときは「ほかN件」で丸める。"""
    names = list(names)
    if not names:
        return "-"
    if len(names) <= limit:
        return "、".join(names)
    return "、".join(names[:limit]) + f" ほか{len(names) - limit}件"


def format_bytes(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def format_number(value: float | None) -> str:
    """桁数に応じて小数を調整する。欠損は '-'。"""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "-"
    a = abs(value)
    if a >= 1000:
        return f"{value:,.0f}"
    if a >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"


def format_pct(ratio: float) -> str:
    """0〜1 の割合をパーセント表記にする。"""
    return f"{ratio * 100:.1f}%"
