"""raw/ の棚卸し

raw/ 配下のファイル一覧・サイズ・文字コード・行数を出し、
manifest.json の記録（取得元URL・取得日時・SHA256）と突き合わせる。
"""

from __future__ import annotations

import argparse
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path

from analysis._report import format_bytes, heading, print_list, print_table, truncate_left
from core.config import MANIFEST_JSON, RAW_DIR, setup_logging
from core.io_utils import detect_encoding, read_json, sha256_of
from defs import datasets

logger = logging.getLogger(__name__)

# 文字コード判定と行数カウントの対象。それ以外（zip・SHP・画像）は中身を見ない。
TEXT_SUFFIXES = {".csv", ".tsv", ".txt", ".json", ".geojson", ".xml"}

# manifest との突き合わせ結果
RECORDED = "記録あり"
EXTRACTED = "展開物"  # zip の展開先。manifest には zip 自体しか載らない
UNRECORDED = "記録なし"  # ingest を通さず置かれたファイル

# 直下に置かれたファイル（manifest.json 以外）をまとめる見出し
LOOSE = "(raw/ 直下)"


@dataclass
class FileRow:
    rel: Path  # RAW_DIR からの相対パス
    size: int
    encoding: str | None
    lines: int | None  # テキストの行数
    entries: int | None  # zip の格納ファイル数
    state: str


def count_lines(path: Path) -> int:
    """改行の数を数える。

    cp932・euc_jp・utf-8 のいずれも 0x0A が改行以外に現れないため、
    文字コードを決めずにバイト列のまま数えてよい。
    """
    total = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            total += chunk.count(b"\n")
    return total


def zip_entries(path: Path) -> int | None:
    if not zipfile.is_zipfile(path):
        return None
    try:
        with zipfile.ZipFile(path) as z:
            return len(z.namelist())
    except zipfile.BadZipFile:
        return None


def _recorded_paths(manifest: dict) -> dict[str, dict]:
    """manifest の記録を「RAW_DIR からの相対パス」で引けるようにする。"""
    out = {}
    for ds_id, entry in manifest.items():
        for key, rec in entry.get("files", {}).items():
            out[str(rec["path"])] = {**rec, "dataset_id": ds_id, "key": key}
    return out


def _extracted_roots(recorded: dict[str, dict]) -> set[Path]:
    """zip の展開先ディレクトリ。ingest は zip と同名のディレクトリに展開する。"""
    return {Path(p).parent / Path(p).stem for p in recorded if Path(p).suffix.lower() == ".zip"}


def _state(rel: Path, recorded: dict[str, dict], roots: set[Path]) -> str:
    if rel.as_posix() in recorded:
        return RECORDED
    if any(root in rel.parents for root in roots):
        return EXTRACTED
    return UNRECORDED


def inspect(path: Path, rel: Path, recorded: dict[str, dict], roots: set[Path]) -> FileRow:
    suffix = path.suffix.lower()
    encoding: str | None = None
    lines: int | None = None
    if suffix in TEXT_SUFFIXES:
        try:
            encoding = detect_encoding(path)
        except UnicodeDecodeError:
            encoding = "判定不能"
        lines = count_lines(path)
    return FileRow(
        rel=rel,
        size=path.stat().st_size,
        encoding=encoding,
        lines=lines,
        entries=zip_entries(path) if suffix == ".zip" else None,
        state=_state(rel, recorded, roots),
    )


def scan(recorded: dict[str, dict]) -> dict[str, list[FileRow]]:
    """raw/ を走査してデータセットID（＝直下のディレクトリ名）ごとにまとめる。"""
    roots = _extracted_roots(recorded)
    grouped: dict[str, list[FileRow]] = {}
    for path in sorted(RAW_DIR.rglob("*")):
        if not path.is_file() or path == MANIFEST_JSON or path.name.startswith("."):
            continue
        rel = path.relative_to(RAW_DIR)
        group = rel.parts[0] if len(rel.parts) > 1 else LOOSE
        grouped.setdefault(group, []).append(inspect(path, rel, recorded, roots))
    return grouped


def _row_cells(row: FileRow, group: str) -> list[str]:
    """データセットディレクトリからの相対で見せる（同じIDの繰り返しを省く）。"""
    name = row.rel.relative_to(group).as_posix() if group != LOOSE else row.rel.as_posix()
    if row.lines is not None:
        count = f"{row.lines:,}行"
    elif row.entries is not None:
        count = f"{row.entries:,}件"
    else:
        count = "-"
    # 深い階層に展開された zip があるため、頭ではなくファイル名側を残す
    return [truncate_left(name, 46), format_bytes(row.size), row.encoding or "-", count, row.state]


def print_inventory(grouped: dict[str, list[FileRow]], limit: int) -> None:
    known = list(datasets.DATASETS)
    order = [g for g in known if g in grouped] + sorted(set(grouped) - set(known))
    for group in order:
        rows = grouped[group]
        ds = datasets.DATASETS.get(group)
        title = f"{group}  {ds.name}" if ds else f"{group}  （datasets.py に定義なし）"
        total = sum(r.size for r in rows)
        heading(f"{title}   [{len(rows)}ファイル / {format_bytes(total)}]")
        shown = rows[:limit]
        print_table(
            ["ファイル", "サイズ", "文字コード", "行数/件数", "manifest"],
            [_row_cells(r, group) for r in shown],
            aligns=["left", "right", "left", "right", "left"],
        )
        if len(rows) > len(shown):
            print(f"  … ほか {len(rows) - len(shown)} ファイル（--limit で表示数を変更）")


def print_crosscheck(
    grouped: dict[str, list[FileRow]], recorded: dict[str, dict], verify: bool
) -> None:
    found = {r.rel.as_posix() for rows in grouped.values() for r in rows}

    heading("manifest に記録があるのに raw/ に無いファイル")
    print_list(
        f"{rec['dataset_id']}/{rec['key']}  {path}"
        for path, rec in sorted(recorded.items())
        if path not in found
    )

    heading("定義済みなのに raw/ にディレクトリが無いデータセット")
    print_list(f"{ds.id}  {ds.name}" for ds in datasets.resolved() if ds.id not in grouped)
    if pending := datasets.pending():
        print(f"  ※ 取得先が未確定のデータセットが別に {len(pending)} 件あります（make datasets）")

    heading("datasets.py に定義の無いディレクトリ")
    print_list(g for g in sorted(grouped) if g != LOOSE and g not in datasets.DATASETS)

    unrecorded = [r for rows in grouped.values() for r in rows if r.state == UNRECORDED]
    heading("ingest を通さず置かれたと思われるファイル")
    print_list((r.rel.as_posix() for r in unrecorded), limit=20)

    if verify:
        heading("SHA256 の照合")
        mismatched = []
        for path, rec in sorted(recorded.items()):
            target = RAW_DIR / path
            if not target.exists():
                continue
            if sha256_of(target) != rec.get("sha256"):
                mismatched.append(f"{path}（取得後に中身が変わっています）")
        if mismatched:
            print_list(mismatched)
        else:
            print("  記録のあるファイルはすべて取得時と同一です")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="raw/ の棚卸しと manifest との突き合わせ")
    parser.add_argument(
        "--limit", type=int, default=12, help="データセットごとの表示ファイル数（既定12）"
    )
    parser.add_argument("--verify", action="store_true", help="SHA256 を再計算して照合する")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    if not RAW_DIR.exists():
        logger.error("%s がありません。先に make ingest を実行してください。", RAW_DIR)
        return 1

    manifest = read_json(MANIFEST_JSON) if MANIFEST_JSON.exists() else {}
    if not manifest:
        logger.warning("%s がありません。ファイル一覧のみ表示します。", MANIFEST_JSON)
    recorded = _recorded_paths(manifest)

    grouped = scan(recorded)
    files = sum(len(rows) for rows in grouped.values())
    total = sum(r.size for rows in grouped.values() for r in rows)
    print(f"raw/ の棚卸し: {len(grouped)} ディレクトリ / {files} ファイル / {format_bytes(total)}")
    print(f"manifest の記録: {len(recorded)} ファイル")

    print_inventory(grouped, args.limit)
    print_crosscheck(grouped, recorded, args.verify)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
