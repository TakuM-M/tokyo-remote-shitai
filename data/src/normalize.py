"""[2] raw/ → interim/（文字コード変換・自治体コード付与・単位統一）

データセットごとの読み方は下部のハンドラに書く。ハンドラは
`dict[指標キー, DataFrame(code, value)]` を返し、共通処理が
`interim/indicators/<指標キー>.csv` に書き出す。D16 だけは分母（面積・人口）を
作るため `interim/municipal_base.csv` を返す。

実ファイルの列名は入手後に確定するため、`pick_column()` で候補名から推測する
方式にしてある。推測が外れたらハンドラ側で列名を直接指定すればよい。

使い方:
    uv run python src/normalize.py            # 実装済みハンドラをすべて実行
    uv run python src/normalize.py --only D8
    uv run python src/normalize.py --status   # 実装状況の一覧
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from pathlib import Path

import pandas as pd

import municipalities as muni
from config import BASE_CSV, INDICATOR_DIR, RAW_DIR, ensure_dirs, setup_logging
from io_utils import ha_to_km2, parse_number, read_csv, write_interim_csv

logger = logging.getLogger(__name__)

# ハンドラの戻り値: {指標キー: DataFrame[code, value]}
IndicatorFrames = dict[str, pd.DataFrame]
Handler = Callable[[], IndicatorFrames]

HANDLERS: dict[str, Handler] = {}


def handler(dataset_id: str) -> Callable[[Handler], Handler]:
    """データセットIDに対する正規化処理を登録する。"""

    def deco(fn: Handler) -> Handler:
        HANDLERS[dataset_id] = fn
        return fn

    return deco


# ---------------------------------------------------------------- 共通ユーティリティ

# 実ファイルで使われがちな列名の候補。前方一致で探す。
COLUMN_CANDIDATES: dict[str, tuple[str, ...]] = {
    "address": ("住所", "所在地", "所在地住所", "施設所在地", "address", "所在"),
    "municipality": ("市区町村", "区市町村", "自治体", "市区町村名", "区市町村名", "地域", "地区"),
    "code": ("団体コード", "全国地方公共団体コード", "市区町村コード", "自治体コード", "code"),
    "name": ("名称", "施設名", "施設名称", "事業所名", "法人名称", "name"),
    "area": ("面積", "総面積", "行政区域面積"),
    "population": ("人口", "総人口", "住民基本台帳人口"),
    "price": ("価格", "公示価格", "価格（円/m2）", "地価"),
    "usage": ("用途", "用途区分", "利用現況", "地域区分"),
    "lat": ("緯度", "lat", "latitude"),
    "lon": ("経度", "lon", "lng", "longitude"),
}


def pick_column(df: pd.DataFrame, kind: str, required: bool = True) -> str | None:
    """候補名から列を1つ選ぶ。見つからなければ（required なら）例外。"""
    candidates = COLUMN_CANDIDATES[kind]
    for cand in candidates:
        for col in df.columns:
            if str(col).strip() == cand:
                return str(col)
    for cand in candidates:
        for col in df.columns:
            if cand in str(col):
                return str(col)
    if required:
        raise KeyError(
            f"{kind} に相当する列が見つかりません。候補={candidates} / 実際の列={list(df.columns)}"
        )
    return None


def resolve_codes(df: pd.DataFrame) -> pd.DataFrame:
    """コード列・自治体名列・住所列のいずれかから `code` 列を作る。

    住所文字列（例: 東京都新宿区西新宿2-8-1）からでも自治体名の前方一致で解決できる。
    """
    code_col = pick_column(df, "code", required=False)
    name_col = pick_column(df, "municipality", required=False) or pick_column(
        df, "address", required=False
    )
    if code_col is None and name_col is None:
        raise KeyError(f"自治体を特定できる列がありません: {list(df.columns)}")
    return muni.attach_code(df, name_col=name_col, code_col=code_col)


def count_by_municipality(df: pd.DataFrame) -> pd.DataFrame:
    """1行1施設のデータを自治体ごとの件数にする。"""
    resolved = resolve_codes(df)
    counts = resolved.groupby("code").size().rename("value").reset_index()
    muni.check_coverage(counts["code"], "件数集計")
    return counts


def mean_by_municipality(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """1行1地点のデータを自治体ごとの平均にする（欠損は平均から除外する）。"""
    resolved = resolve_codes(df)
    resolved["_v"] = resolved[value_col].map(parse_number)
    agg = resolved.groupby("code")["_v"].mean().rename("value").reset_index()
    agg = agg.dropna(subset=["value"])
    muni.check_coverage(agg["code"], f"{value_col} 平均")
    return agg


def indicator_frame(values: dict[str, float]) -> pd.DataFrame:
    """{コード: 値} を指標フレームにする。"""
    return pd.DataFrame({"code": list(values.keys()), "value": list(values.values())})


def write_indicators(frames: IndicatorFrames) -> None:
    """指標ごとに interim/indicators/<key>.csv を書く。"""
    INDICATOR_DIR.mkdir(parents=True, exist_ok=True)
    for key, frame in frames.items():
        out = frame.loc[:, ["code", "value"]].copy()
        out["code"] = out["code"].astype(str)
        # 欠損行は書かない。score 側で「値が無い＝no_data」として扱う（0で埋めない）。
        out = out.dropna(subset=["value"])
        write_interim_csv(out, INDICATOR_DIR / f"{key}.csv")


def raw_dir_for(dataset_id: str) -> Path:
    return RAW_DIR / dataset_id


def find_raw_file(dataset_id: str, pattern: str = "*.csv") -> Path:
    """raw/<ID>/ から対象ファイルを1つ探す（zip展開後のサブディレクトリも見る）。"""
    base = raw_dir_for(dataset_id)
    if not base.exists():
        raise FileNotFoundError(f"{base} がありません。先に ingest を実行してください。")
    hits = sorted(base.rglob(pattern))
    if not hits:
        raise FileNotFoundError(f"{base} に {pattern} が見つかりません。")
    if len(hits) > 1:
        logger.info("[%s] %d件ヒット。先頭を使用: %s", dataset_id, len(hits), hits[0].name)
    return hits[0]


# ---------------------------------------------------------------- ハンドラ


@handler("D16")
def normalize_base() -> IndicatorFrames:
    """統計年鑑から面積・人口（全指標の分母）を作り、municipal_base.csv に書く。

    面積は ha 表記のことがあるため km2 に統一する。
    """
    df = read_csv(find_raw_file("D16"))
    df = resolve_codes(df)
    area_col = pick_column(df, "area")
    pop_col = pick_column(df, "population")

    base = pd.DataFrame({"code": df["code"]})
    area = df[area_col].map(parse_number)
    # 東京都で最大の自治体（大田区）でも約61km2。1000超なら ha 表記とみなす。
    base["area_km2"] = area.map(ha_to_km2) if area.median() > 1000 else area
    base["population"] = df[pop_col].map(parse_number)

    base = base.groupby("code", as_index=False).agg({"area_km2": "max", "population": "max"})
    base["name"] = base["code"].map(lambda c: muni.BY_CODE[c].name)
    base = base.loc[:, ["code", "name", "area_km2", "population"]]

    muni.check_coverage(base["code"], "municipal_base")
    write_interim_csv(base, BASE_CSV)
    return {}


@handler("D8")
def normalize_satellite_offices() -> IndicatorFrames:
    """TOKYOテレワークアプリ掲載サテライトオフィスを自治体ごとに数える。"""
    df = read_csv(find_raw_file("D8"))
    return {"satellite_office_count": count_by_municipality(df)}


@handler("D9")
def normalize_culture_facilities() -> IndicatorFrames:
    """生涯学習センター・文化施設の件数。"""
    df = read_csv(find_raw_file("D9"))
    return {"culture_facility_count": count_by_municipality(df)}


@handler("D14")
def normalize_npo() -> IndicatorFrames:
    """認証NPO法人を主たる事務所の所在地で数える。"""
    df = read_csv(find_raw_file("D14"))
    return {"npo_count": count_by_municipality(df)}


# 公共施設一覧（D7）は1ファイルに複数種別が混在するため、名称のキーワードで分類する
FACILITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "library_count": ("図書館", "図書室"),
    "park_count": ("公園", "緑地", "庭園"),
    "community_facility_count": (
        "集会",
        "コミュニティ",
        "地区センター",
        "区民館",
        "公民館",
        "会館",
    ),
}


@handler("D7")
def normalize_public_facilities() -> IndicatorFrames:
    """公共施設一覧を種別ごとに分類して件数化する。"""
    df = read_csv(find_raw_file("D7"))
    name_col = pick_column(df, "name")
    frames: IndicatorFrames = {}
    for key, keywords in FACILITY_KEYWORDS.items():
        matched = df[df[name_col].astype(str).str.contains("|".join(keywords), na=False)]
        logger.info("[D7] %s: %d件", key, len(matched))
        if len(matched):
            frames[key] = count_by_municipality(matched)
    return frames


@handler("D11")
def normalize_land_price() -> IndicatorFrames:
    """地価公示のうち用途「住宅地」を自治体内で平均する。"""
    df = read_csv(find_raw_file("D11"))
    usage_col = pick_column(df, "usage", required=False)
    if usage_col:
        before = len(df)
        df = df[df[usage_col].astype(str).str.contains("住宅", na=False)]
        logger.info("[D11] 用途『住宅地』で絞込み: %d → %d件", before, len(df))
    price_col = pick_column(df, "price")
    return {"land_price_residential": mean_by_municipality(df, price_col)}


@handler("D15")
def normalize_day_night_ratio() -> IndicatorFrames:
    """昼夜間人口比率（参考指標）。"""
    df = read_csv(find_raw_file("D15", "*.csv"))
    df = resolve_codes(df)
    ratio_col = pick_column(df, "population")  # 実ファイル確認後に比率列へ差し替える
    return {"day_night_population_ratio": mean_by_municipality(df, ratio_col)}


# ---------------------------------------------------------------- エントリポイント


def run(dataset_id: str) -> IndicatorFrames:
    fn = HANDLERS[dataset_id]
    logger.info("[%s] 正規化: %s", dataset_id, fn.__doc__.splitlines()[0] if fn.__doc__ else "")
    frames = fn()
    write_indicators(frames)
    return frames


def print_status() -> None:
    import datasets
    from spatial_join import SPATIAL_HANDLERS

    print(f"{'ID':<5} {'処理':<12} {'raw/':<6} データセット")
    print("-" * 84)
    for ds in datasets.DATASETS.values():
        if ds.id in HANDLERS:
            impl = "normalize"
        elif ds.id in SPATIAL_HANDLERS:
            impl = "空間結合"
        else:
            impl = "未実装"
        fetched = "あり" if raw_dir_for(ds.id).exists() else "なし"
        print(f"{ds.id:<5} {impl:<12} {fetched:<6} {ds.name}")
    print()
    print("※「空間結合」は spatial_join.py 側で処理する（座標を伴うデータ）。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="raw/ を interim/ に正規化する")
    parser.add_argument("--only", nargs="+", metavar="ID", help="対象データセットID")
    parser.add_argument("--status", action="store_true", help="実装状況を一覧表示して終了")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    ensure_dirs()

    if args.status:
        print_status()
        return 0

    targets = args.only or list(HANDLERS)
    ok, failed = 0, 0
    for dataset_id in targets:
        if dataset_id not in HANDLERS:
            logger.warning("[%s] ハンドラ未実装のためスキップ", dataset_id)
            continue
        try:
            run(dataset_id)
            ok += 1
        except (FileNotFoundError, KeyError) as e:
            # 原データ未取得・列名の想定違いはこの段階では想定内。止めずに次へ進む。
            logger.warning("[%s] スキップ: %s", dataset_id, e)
            failed += 1
        except Exception:
            logger.exception("[%s] 正規化に失敗", dataset_id)
            failed += 1

    logger.info("完了: 成功 %d / スキップ・失敗 %d", ok, failed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
