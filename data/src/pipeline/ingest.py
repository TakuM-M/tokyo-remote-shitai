"""rawデータの取得

datasets.py の定義に従ってダウンロード、`raw/<データセットID>/` に配置

基本的に取得済みなら再取得しない
再取得する場合は `raw/<データセットID>/` を消してから実行
（全件再取得 `make clean-all`）
--heavy オプションで大容量ファイルも取得する
    
取得結果は raw/manifest.json に記録（いつ・どのURLから・どのハッシュのものを取ったか）
"""

from __future__ import annotations

import argparse
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

from core.config import MANIFEST_JSON, RAW_DIR, ensure_dirs, setup_logging
from core.io_utils import read_json, sha256_of, write_json
from defs import datasets
from defs.datasets import Dataset, Resource

logger = logging.getLogger(__name__)

USER_AGENT = "RemoteLifeTokyo-DataPipeline/0.1 (Tokyo OpenData Hackathon 2026)"
TIMEOUT = 60
CHUNK = 1024 * 256


def target_path(ds: Dataset, res: Resource) -> Path:
    return RAW_DIR / ds.id / res.filename


def _load_manifest() -> dict:
    if MANIFEST_JSON.exists():
        return read_json(MANIFEST_JSON)
    return {}


def fetch(ds: Dataset, res: Resource) -> Path:
    """1ファイルを取得する。zip なら展開まで済ませる。"""
    dest = target_path(ds, res)
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("[%s/%s] 取得開始: %s", ds.id, res.key, res.url)

    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(
        res.url, stream=True, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as response:
        response.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in response.iter_content(CHUNK):
                f.write(chunk)
    tmp.replace(dest)
    logger.info(
        "[%s/%s] 取得完了: %s (%.1f KB)", ds.id, res.key, dest.name, dest.stat().st_size / 1024
    )

    # xlsx なども zip なので、拡張子で本当の配布形式を見分ける
    if dest.suffix.lower() == ".zip" and zipfile.is_zipfile(dest):
        _extract_zip(ds, dest)
    return dest


def download(ds: Dataset, include_heavy: bool = False) -> tuple[int, int]:
    """1データセットの全ファイルを取得し、（取得数, スキップ数）を返す"""
    if not ds.is_resolved:
        logger.warning("[%s] %s のためスキップ: %s", ds.id, _status_label(ds), ds.name)
        return 0, len(ds.resources)

    fetched, skipped = 0, 0
    for res in ds.resources:
        if res.heavy and not include_heavy:
            logger.info("[%s/%s] 大容量のためスキップ（--heavy で取得）", ds.id, res.key)
            skipped += 1
            continue
        dest = target_path(ds, res)
        if dest.exists():
            logger.info("[%s/%s] 取得済みのためスキップ: %s", ds.id, res.key, dest.name)
            skipped += 1
            continue
        _record(ds, res, fetch(ds, res))
        fetched += 1
    return fetched, skipped


def _extract_zip(ds: Dataset, path: Path) -> None:
    """GIS データは zip 配布が多いので展開まで済ませる。

    国内配布の zip は格納名が CP932 のことがあり、zipfile はそれを CP437 として
    読むため化ける。UTF-8 フラグが立っていないものは読み直してから展開する。
    """
    out_dir = path.parent / path.stem
    out_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if not info.flag_bits & 0x800:
                info.filename = info.filename.encode("cp437").decode("cp932", "replace")
            z.extract(info, out_dir)
    logger.info("[%s] 展開: %s/", ds.id, out_dir.name)


def _record(ds: Dataset, res: Resource, path: Path) -> None:
    manifest = _load_manifest()
    entry = manifest.setdefault(ds.id, {"name": ds.name, "files": {}})
    entry["name"] = ds.name
    entry.setdefault("files", {})[res.key] = {
        "url": res.url,
        "path": str(path.relative_to(RAW_DIR)),
        "bytes": path.stat().st_size,
        "sha256": sha256_of(path),
        "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    write_json(MANIFEST_JSON, manifest)


def _status_label(ds: Dataset) -> str:
    return {"ok": "URL未確定", "pending": "利用条件確認中"}[ds.status]


def print_list() -> None:
    """定義済みデータセットと取得状況を表示する。"""
    manifest = _load_manifest()
    print(f"{'ID':<5} {'状況':<14} {'軸':<22} データセット")
    print("-" * 96)
    for ds in datasets.DATASETS.values():
        got = set(manifest.get(ds.id, {}).get("files", {}))
        if not ds.is_resolved:
            status = _status_label(ds)
        elif got >= {r.key for r in ds.resources}:
            status = "取得済み"
        elif got:
            status = f"一部取得 {len(got)}/{len(ds.resources)}"
        else:
            status = "未取得"
        print(f"{ds.id:<5} {status:<14} {','.join(ds.axes):<22} {ds.name}")

    if pending := datasets.pending():
        print()
        print(f"利用条件の確認待ちが {len(pending)} 件あります:")
        for ds in pending:
            print(f"  - {ds.id} {ds.name}")
            print(f"      {ds.notes}")

    heavy = [(d, r) for d in datasets.resolved() for r in d.resources if r.heavy]
    if heavy:
        print()
        print(f"既定では取得しない大容量ファイルが {len(heavy)} 件あります（--heavy で取得）:")
        for ds, res in heavy:
            print(f"  - {ds.id}/{res.key} {res.notes or res.filename}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="原データを raw/ に取得する")
    parser.add_argument("--only", nargs="+", metavar="ID", help="対象データセットID（例: D8 D11）")
    parser.add_argument("--heavy", action="store_true", help="大容量ファイルもあわせて取得する")
    parser.add_argument("--list", action="store_true", help="定義と取得状況を一覧表示して終了")
    args = parser.parse_args(argv)

    setup_logging()
    ensure_dirs()

    if args.list:
        print_list()
        return 0

    targets = (
        [datasets.get(i) for i in args.only] if args.only else list(datasets.DATASETS.values())
    )
    include_heavy = args.heavy or bool(args.only)

    ok, skipped, failed = 0, 0, 0
    for ds in targets:
        try:
            fetched, passed = download(ds, include_heavy)
        except requests.RequestException as e:
            logger.error("[%s] 取得失敗: %s", ds.id, e)
            failed += 1
            continue
        ok += fetched
        skipped += passed

    logger.info("完了: 取得 %d / スキップ %d / 失敗 %d", ok, skipped, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
