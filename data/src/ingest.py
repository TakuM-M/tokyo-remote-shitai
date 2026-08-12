"""[1] 原データの取得 → raw/

datasets.py の定義に従ってダウンロードし、`raw/<データセットID>/` に原形のまま置く。
取得結果は raw/manifest.json に記録する（いつ・どのURLから・どのハッシュのものを
取ったかが残らないと、スコアの再現ができないため）。

使い方:
    uv run python src/ingest.py              # URL確定分をすべて取得
    uv run python src/ingest.py --only D10 D13
    uv run python src/ingest.py --list       # 定義と取得状況の一覧
"""

from __future__ import annotations

import argparse
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

import datasets
from config import MANIFEST_JSON, RAW_DIR, ensure_dirs, setup_logging
from datasets import Dataset
from io_utils import read_json, sha256_of, write_json

logger = logging.getLogger(__name__)

USER_AGENT = "RemoteLifeTokyo-DataPipeline/0.1 (Tokyo OpenData Hackathon 2026)"
TIMEOUT = 60
CHUNK = 1024 * 256


def _filename_for(ds: Dataset) -> str:
    if ds.filename:
        return ds.filename
    name = Path(unquote(urlparse(ds.download_url or "").path)).name
    return name or f"{ds.id}.dat"


def target_path(ds: Dataset) -> Path:
    return RAW_DIR / ds.id / _filename_for(ds)


def _load_manifest() -> dict:
    if MANIFEST_JSON.exists():
        return read_json(MANIFEST_JSON)
    return {}


def download(ds: Dataset, force: bool = False, extract: bool = True) -> Path | None:
    """1データセットを取得する。取得済みなら再取得しない（--force で上書き）。"""
    if not ds.is_resolved:
        logger.warning("[%s] download_url が未確定のためスキップ: %s", ds.id, ds.name)
        return None

    dest = target_path(ds)
    if dest.exists() and not force:
        logger.info("[%s] 取得済みのためスキップ: %s", ds.id, dest.name)
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("[%s] 取得開始: %s", ds.id, ds.download_url)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(
        ds.download_url, stream=True, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as res:
        res.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in res.iter_content(CHUNK):
                f.write(chunk)
    tmp.replace(dest)
    logger.info("[%s] 取得完了: %s (%.1f KB)", ds.id, dest.name, dest.stat().st_size / 1024)

    if extract and zipfile.is_zipfile(dest):
        _extract_zip(ds, dest)

    _record(ds, dest)
    return dest


def _extract_zip(ds: Dataset, path: Path) -> None:
    """GIS データは zip 配布が多いので展開まで済ませる。"""
    out_dir = path.parent / path.stem
    out_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(path) as z:
        z.extractall(out_dir)
    logger.info("[%s] 展開: %s/", ds.id, out_dir.name)


def _record(ds: Dataset, path: Path) -> None:
    manifest = _load_manifest()
    manifest[ds.id] = {
        "name": ds.name,
        "url": ds.download_url,
        "path": str(path.relative_to(RAW_DIR)),
        "bytes": path.stat().st_size,
        "sha256": sha256_of(path),
        "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    write_json(MANIFEST_JSON, manifest)


def print_list() -> None:
    """定義済みデータセットと取得状況を表示する。"""
    manifest = _load_manifest()
    print(f"{'ID':<5} {'状況':<10} {'軸':<22} データセット")
    print("-" * 96)
    for ds in datasets.DATASETS.values():
        if ds.id in manifest:
            status = "取得済み"
        elif ds.is_resolved:
            status = "未取得"
        else:
            status = "URL未確定"
        print(f"{ds.id:<5} {status:<10} {','.join(ds.axes):<22} {ds.name}")

    pending = datasets.unresolved()
    if pending:
        print()
        print(f"URL未確定が {len(pending)} 件あります（仕様書12章のデータ実査で埋める対象）:")
        for ds in pending:
            print(f"  - {ds.id} {ds.name} … {ds.catalog_url or 'カタログURLも未確認'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="原データを raw/ に取得する")
    parser.add_argument("--only", nargs="+", metavar="ID", help="対象データセットID（例: D10 D13）")
    parser.add_argument("--force", action="store_true", help="取得済みでも再取得する")
    parser.add_argument("--no-extract", action="store_true", help="zip を展開しない")
    parser.add_argument("--list", action="store_true", help="定義と取得状況を一覧表示して終了")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    ensure_dirs()

    if args.list:
        print_list()
        return 0

    targets = (
        [datasets.get(i) for i in args.only] if args.only else list(datasets.DATASETS.values())
    )

    ok, skipped, failed = 0, 0, 0
    for ds in targets:
        try:
            path = download(ds, force=args.force, extract=not args.no_extract)
        except requests.RequestException as e:
            logger.error("[%s] 取得失敗: %s", ds.id, e)
            failed += 1
            continue
        if path is None:
            skipped += 1
        else:
            ok += 1

    logger.info("完了: 取得 %d / スキップ %d / 失敗 %d", ok, skipped, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
