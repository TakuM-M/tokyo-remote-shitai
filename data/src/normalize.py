""" raw/ → interim/（文字コード変換・自治体コード付与・単位統一）


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

# 実ファイルで使われがちな列名の候補。完全一致を優先し、無ければ部分一致で探す。
COLUMN_CANDIDATES: dict[str, tuple[str, ...]] = {
    "address": ("住所", "所在地", "所在地住所", "施設所在地", "主たる事務所", "address", "所在"),
    "municipality": ("市区町村", "区市町村", "自治体", "市区町村名", "区市町村名", "地域", "地区"),
    "code": (
        "団体コード",
        "全国地方公共団体コード",
        "市区町村コード",
        "区市町村コード",
        "自治体コード",
        "地域コード",
        "都道府県市区町村コード",
        "code",
    ),
    "name": ("名称", "施設名", "施設名称", "事業所名", "法人名称", "name"),
    "area": ("面積", "総面積", "行政区域面積"),
    "population": ("人口", "総人口", "住民基本台帳人口"),
    "price": ("当年価格", "価格", "公示価格", "価格（円/m2）", "地価"),
    "usage": ("標準地番号（用途）", "用途区分", "用途", "利用現況", "地域区分"),
    "lat": ("緯度", "lat", "latitude"),
    "lon": ("経度", "lon", "lng", "longitude"),
}


def pick_from(
    df: pd.DataFrame, candidates: tuple[str, ...], required: bool = True, label: str = ""
) -> str | None:
    """候補名から列を1つ選ぶ。完全一致を全候補について試してから部分一致に落とす。

    「価格」で「当年価格（円）」と「前年価格（円）」の両方が引っかかるような場合は、
    候補の並び順が優先度になる（先に書いたものが勝つ）。
    """
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
            f"{label or '対象'} に相当する列が見つかりません。"
            f"候補={candidates} / 実際の列={list(df.columns)}"
        )
    return None


def pick_column(df: pd.DataFrame, kind: str, required: bool = True) -> str | None:
    """`COLUMN_CANDIDATES` に登録した種別から列を1つ選ぶ。"""
    return pick_from(df, COLUMN_CANDIDATES[kind], required, kind)


def resolve_codes(df: pd.DataFrame) -> pd.DataFrame:
    """コード列・自治体名列・住所列から `code` 列を作る。

    コード列を最優先し、埋まらなかった行を自治体名 → 住所の順で補う。
    D7 のように自治体名列が空でコード列にも都のコードしか入らないデータは、
    住所文字列（例: 東京都新宿区西新宿2-8-1）から前方一致で解決することになる。
    """
    code_col = pick_column(df, "code", required=False)
    name_cols = [
        c
        for c in (
            pick_column(df, "municipality", required=False),
            pick_column(df, "address", required=False),
        )
        if c
    ]
    if code_col is None and not name_cols:
        raise KeyError(f"自治体を特定できる列がありません: {list(df.columns)}")
    return muni.attach_code(df, name_col=name_cols, code_col=code_col)


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


def find_raw_files(dataset_id: str, pattern: str = "*.csv") -> list[Path]:
    """raw/<ID>/ から対象ファイルを探す（zip展開後のサブディレクトリも見る）。"""
    base = raw_dir_for(dataset_id)
    if not base.exists():
        raise FileNotFoundError(f"{base} がありません。先に ingest を実行してください。")
    hits = sorted(base.rglob(pattern))
    if not hits:
        raise FileNotFoundError(f"{base} に {pattern} が見つかりません。")
    return hits


def find_raw_file(dataset_id: str, pattern: str = "*.csv") -> Path:
    """raw/<ID>/ から対象ファイルを1つ探す。複数ヒットしたら先頭を使う。"""
    hits = find_raw_files(dataset_id, pattern)
    if len(hits) > 1:
        logger.info("[%s] %d件ヒット。先頭を使用: %s", dataset_id, len(hits), hits[0].name)
    return hits[0]


# ---------------------------------------------------------------- ハンドラ


@handler("D16")
def normalize_base() -> IndicatorFrames:
    """人口推計から面積・人口（全指標の分母）を作り、municipal_base.csv に書く。

    区部・市部・総数といった集計行が同じ表に混ざるが、地域コードが 13000/13100 など
    自治体コードでないため `resolve_codes` の段階で落ちる。
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


# 大気測定局マスタ・1分値CSVはどちらもヘッダ行を持たないため列名を与える。
# 局マスタが市区町村コードを持つので、緯度経度はあっても空間結合は要らない。
# むしろ区境に建つ局は座標だけだと隣の自治体に落ちる（甲州街道大原局は
# 渋谷区笹塚だが、座標は杉並区側に出る）ため、登録上のコードを正とする。
STATION_COLUMNS = (
    "局コード",
    "局名",
    "都道府県コード",
    "都道府県名",
    "市区町村コード",
    "測定局コード",
    "カナ",
    "住所",
    "緯度",
    "経度",
)
PM25_COLUMNS = ("局コード", "項目コード", "年", "月", "日", "時", "分", "値")


def pm25_station_means() -> pd.DataFrame:
    """1分値CSVから測定局ごとの平均濃度(μg/m3)を出す。

    - 公開されているのは直近50日分の速報値だけなので、年平均ではなく期間平均になる。
    - 値が「欠測」の行は平均から除く（0では埋めない）。
    - 1分値は器差でわずかに負に振れることがあるが、平均すれば打ち消し合うので残す。
    """
    frames = [
        read_csv(path, header=None, names=PM25_COLUMNS, usecols=["局コード", "値"])
        for path in find_raw_files("D1", "*PM2.5*.csv")
    ]
    raw = pd.concat(frames, ignore_index=True)
    raw["_v"] = raw["値"].map(parse_number)
    valid = raw.dropna(subset=["_v"])
    logger.info(
        "[D1] 1分値 %d件のうち有効 %d件（欠測 %d件）", len(raw), len(valid), len(raw) - len(valid)
    )
    return valid.groupby("局コード")["_v"].mean().rename("pm25").reset_index()


@handler("D1")
def normalize_pm25() -> IndicatorFrames:
    """大気測定局の1分値を局ごとに平均し、さらに自治体ごとに平均する。

    局のない自治体は欠損のままにする（近傍局での補完を入れる場合は、
    補完した旨を指標側の status に残せるようにしてから行う）。
    """
    master = read_csv(find_raw_file("D1", "stations.csv"), header=None, names=STATION_COLUMNS)
    stations = master.merge(pm25_station_means(), on="局コード", how="inner")
    logger.info("[D1] 測定局 %d局のうち PM2.5 の値がある局: %d", len(master), len(stations))
    return {"pm25_annual_avg": mean_by_municipality(stations, "pm25")}


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
    """認証NPO法人を主たる事務所の所在地で数える。

    1行目が表題で、ヘッダは2行目にある。自治体名の列は無く、住所文字列から解決する。
    """
    df = read_csv(find_raw_file("D14"), header=1)
    return {"npo_count": count_by_municipality(df)}


# 公共施設一覧（D7）は1ファイルに複数種別が混在する。推奨データセットの POIコードで
# 分類できるため、こちらを主に使う。1512a=図書館 / 1002a=自然公園 / 1003a=都市公園 /
# 1004a=庭園 / 0801a=博物館 / 0802a=美術館 / 1012a=文化会館。
FACILITY_POI_CODES: dict[str, tuple[str, ...]] = {
    "library_count": ("1512a",),
    "park_count": ("1002a", "1003a", "1004a"),
    # 集会所・コミュニティ施設に当たる POIコードは、都立施設だけの本データには入らない
    "community_facility_count": ("1301a", "1302a"),
}

# POIコード列が無いファイルに差し替わったときの保険。名称のキーワードで拾う。
FACILITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "library_count": ("図書館", "図書室"),
    "park_count": ("公園", "緑地", "庭園"),
    "community_facility_count": ("集会", "コミュニティ", "地区センター", "区民館", "公民館"),
}


@handler("D7")
def normalize_public_facilities() -> IndicatorFrames:
    """公共施設一覧を種別ごとに分類して件数化する。

    収録は都立施設のみで、自治体名列は空・コード列も都のコード（13100…）しか入らない。
    自治体の判定は住所文字列から行う（`resolve_codes` が住所まで見る）。
    """
    df = read_csv(find_raw_file("D7"))
    poi_col = pick_from(df, ("POIコード",), required=False, label="POIコード")
    name_col = pick_column(df, "name")

    frames: IndicatorFrames = {}
    for key in FACILITY_POI_CODES:
        if poi_col:
            matched = df[df[poi_col].astype(str).str.strip().isin(FACILITY_POI_CODES[key])]
        else:
            pattern = "|".join(FACILITY_KEYWORDS[key])
            matched = df[df[name_col].astype(str).str.contains(pattern, na=False)]
        if not len(matched):
            # 0件を0で埋めると「施設が無い自治体」と区別できなくなるので、指標ごと出さない
            logger.warning("[D7] %s: 該当する施設が0件。この指標は no_data のままになる", key)
            continue
        logger.info("[D7] %s: %d件", key, len(matched))
        frames[key] = count_by_municipality(matched)
    return frames


# 地価公示の「標準地番号（用途）」の区分。住宅地だけを地価水準の指標に使う。
LAND_USE_RESIDENTIAL = 0


@handler("D11")
def normalize_land_price() -> IndicatorFrames:
    """地価公示のうち用途「住宅地」の㎡単価を自治体内で平均する。

    1行目が表題で、ヘッダは2行目にある。用途は「用途区分」（＝用途地域）ではなく
    「標準地番号（用途）」の数字で判別する（住宅地=0 / 商業地=5 / 工業地=9）。
    価格は当年の1㎡当たり価格を採る。
    """
    df = read_csv(find_raw_file("D11"), header=1)
    usage_col = pick_column(df, "usage")
    before = len(df)
    df = df[df[usage_col].map(parse_number) == LAND_USE_RESIDENTIAL]
    logger.info("[D11] 用途『住宅地』で絞込み: %d → %d件", before, len(df))
    price_col = pick_column(df, "price")
    return {"land_price_residential": mean_by_municipality(df, price_col)}


@handler("D15")
def normalize_day_night_ratio() -> IndicatorFrames:
    """昼夜間人口比率（参考指標）。

    第1表は1自治体1行で、比率が算出済みの列として入っている。
    昼間人口・常住人口の列と紛らわしいため列名を明示して取る。
    """
    df = read_csv(find_raw_file("D15"))
    ratio_col = pick_from(df, ("昼夜間人口比率／総数", "昼夜間人口比率"), label="昼夜間人口比率")
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
    parser.add_argument("--status", action="store_true", help="実装状況を一覧表示して終了")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    ensure_dirs()

    if args.status:
        print_status()
        return 0

    targets = list(HANDLERS)
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
