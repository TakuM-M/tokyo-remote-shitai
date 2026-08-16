"""raw/ → interim/（文字コード変換・自治体コード付与・単位統一）"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from core import municipalities as muni
from core.config import BASE_CSV, RAW_DIR, ensure_dirs, setup_logging
from core.io_utils import ha_to_km2, parse_number, read_csv, write_interim_csv
from defs import datasets
from defs.datasets import PM25_MONTHS, pm25_resource_key
from pipeline.common import IndicatorFrames, iter_zip_members, raw_path, write_indicators

logger = logging.getLogger(__name__)

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
    "address": ("住所", "所在地", "所在地住所", "施設所在地", "主たる事務所", "所在"),
    "municipality": ("市区町村", "区市町村", "自治体", "市区町村名", "区市町村名", "地域", "地区"),
    "code": (
        "団体コード",
        "全国地方公共団体コード",
        "市区町村コード",
        "区市町村コード",
        "自治体コード",
        "地域コード",
        "都道府県市区町村コード",
    ),
    "area": ("面積", "総面積", "行政区域面積"),
    "population": ("人口", "総人口", "住民基本台帳人口"),
    "price": ("当年価格", "価格", "公示価格", "地価"),
    # 地価公示の用途区分は「標準地番号（用途）」に入る。
    # 「用途区分」列は用途地域（２住居など）で別物なので候補に入れない。
    "land_use": ("標準地番号（用途）",),
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
    D-community-01 のようにコード列も自治体名列も持たないデータは、
    住所文字列（例: 東京都港区南麻布5-7-13）から解決することになる。
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


# ---------------------------------------------------------------- しずけさ

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

# 1分値は zip の中を直接読むため、Path 前提の文字コード自動判定（io_utils.read_csv）は
# 使えない。中身は数字と「欠測」だけで、配布は CP932 固定。
PM25_ENCODING = "cp932"

# 月内の有効分数がこれを下回る局は、その月は動いていなかったとみなして年平均から外す。
# 1か月は約4.3万分（=フル稼働）で、実データは 2万分以下 と 3.2万分以上 にはっきり割れる。
# その谷にしきい値を置いているので、多少ずらしても結果は動かない。
PM25_MIN_MINUTES_PER_MONTH = 30_000

# 年平均として認める最低月数。PM2.5は月平均で 3.4〜7.1μg/m3 と2倍動くため、
# 欠測月が多い局の平均は「どの季節が欠けたか」で上下してしまう。
# 実データでは 2か月欠けで +0.15μg/m3 程度、4か月（冬まるごと）欠けで +0.21μg/m3 ずれる。
# 自治体間の開きが 4.2〜5.7μg/m3 なので、2か月欠けまでを許容範囲としている。
PM25_MIN_MONTHS = 10


def pm25_monthly_station_means() -> pd.DataFrame:
    """月別ZIPを 局コード × 月 の平均濃度(μg/m3)にする。

    - 値が「欠測」の行は平均から除く（0では埋めない）。
    - 1分値は器差でわずかに負に振れることがあるが、平均すれば打ち消し合うので残す。
    - 1か月あたり8ファイル・約350万行あるため、ファイルごとに局別の合計・件数まで
      畳んでから足し合わせる。展開すると12か月で1GBを超えるので zip のまま読む。
    """
    months = []
    for month in PM25_MONTHS:
        totals: pd.DataFrame | None = None
        for fh in iter_zip_members("D-quiet-01", pm25_resource_key(month)):
            raw = pd.read_csv(
                fh,
                header=None,
                names=PM25_COLUMNS,
                usecols=["局コード", "値"],
                dtype=str,
                keep_default_na=False,
                encoding=PM25_ENCODING,
            )
            # 機械出力で表記ゆれが無く、欠損は「欠測」の1種類だけなので to_numeric で足りる
            raw["_v"] = pd.to_numeric(raw["値"], errors="coerce")
            part = raw.dropna(subset=["_v"]).groupby("局コード")["_v"].agg(["sum", "count"])
            totals = part if totals is None else totals.add(part, fill_value=0)
        # zip が空なら iter_zip_members が投げるので、ここに来た時点で totals は埋まっている
        assert totals is not None
        frame = totals.rename(columns={"count": "minutes"}).reset_index()
        frame["month"] = month
        frame["pm25"] = frame["sum"] / frame["minutes"]
        months.append(frame[["局コード", "month", "pm25", "minutes"]])
        logger.info(
            "[D-quiet-01] %s: %d局 / 有効 %.1f万分",
            month,
            len(frame),
            frame["minutes"].sum() / 10_000,
        )
    return pd.concat(months, ignore_index=True)


def pm25_station_annual_means() -> pd.DataFrame:
    """測定局ごとの年平均濃度(μg/m3)を出す。

    月平均を出してから月を等重みで平均する。1分値をまとめて通期平均すると、
    欠測の多い月ほど重みが軽くなり、季節変動の入り方が局ごとにばらつくため。
    測っていた月が `PM25_MIN_MONTHS` に満たない局は、年平均とは呼べないので落とす
    （その結果どの局も無くなった自治体は、0で埋めずに no_data とする）。
    """
    monthly = pm25_monthly_station_means()
    measured = monthly[monthly["minutes"] >= PM25_MIN_MINUTES_PER_MONTH]
    by_station = measured.groupby("局コード")["pm25"].agg(["mean", "count"])
    enough = by_station[by_station["count"] >= PM25_MIN_MONTHS]
    logger.info(
        "[D-quiet-01] 局別の年平均: %d局中 %d局が%dか月以上そろった",
        len(by_station),
        len(enough),
        PM25_MIN_MONTHS,
    )
    return enough["mean"].rename("pm25").reset_index()


@handler("D-quiet-01")
def normalize_pm25() -> IndicatorFrames:
    """大気測定局の1分値を局ごとに年平均し、さらに自治体ごとに平均する。"""
    master = read_csv(raw_path("D-quiet-01", "stations"), header=None, names=STATION_COLUMNS)
    stations = master.merge(pm25_station_annual_means(), on="局コード", how="inner")
    logger.info("[D-quiet-01] 測定局 %d局のうち年平均値を作れた局: %d", len(master), len(stations))
    return {"pm25_annual_avg": mean_by_municipality(stations, "pm25")}


# 自動車交通騒音調査（D-quiet-02）は1年度1CSV。年度によって列名が揺れる
# （「測定地点の住所」/「測定地点住所」、「昼間等価騒音レベル(Leq)(dB)」/
# 「昼間等価騒音レベル(dB)」）ため、いずれも部分一致で拾う。
NOISE_DAY = ("昼間",)
NOISE_NIGHT = ("夜間",)


def read_noise_year(path: Path, year: int) -> pd.DataFrame:
    """1年度分のCSVを 自治体コード × 昼間Leq の地点表にする。

    昼間の値が数値の行だけを採る（「欠測」「-」の行は落とす）。
    夜間が「-」の地点は昼間しか測っていないだけなので残す。
    """
    df = read_csv(path)
    address = pick_column(df, "address")
    day = pick_from(df, NOISE_DAY, label="昼間等価騒音レベル")
    night = pick_from(df, NOISE_NIGHT, label="夜間等価騒音レベル")

    points = muni.attach_code(df, name_col=address)
    points["leq_day"] = points[day].map(parse_number)

    # 列が1つ足りない行が混じる（平成25年度に2件）。pandas が末尾を空で埋めるため、
    # 昼間・夜間の値が1列ずれて入り、夜間の欄だけが空になる。昼間の値も信用できない。
    # 夜間を「-」と書いた地点は空欄ではないので、この条件では落ちない。
    shifted = points[night].fillna("").astype(str).str.strip() == ""
    valid = points.loc[~shifted].dropna(subset=["leq_day"])
    logger.info(
        "[D-quiet-02] %d年度: 地点 %d件（うち有効 %d件） / %d自治体",
        year,
        len(points),
        len(valid),
        valid["code"].nunique(),
    )
    return valid.loc[:, ["code", "leq_day"]].assign(year=year)


def load_noise_points() -> pd.DataFrame:
    """取得済みの年度をすべて読んで1つの地点表にする。"""
    resources = sorted(
        datasets.get("D-quiet-02").resources, key=lambda r: r.year or 0, reverse=True
    )
    frames = []
    for res in resources:
        try:
            path = raw_path("D-quiet-02", res.key)
        except FileNotFoundError:
            logger.warning("[D-quiet-02] 未取得のためスキップ: %s", res.filename)
            continue
        frames.append(read_noise_year(path, int(res.year)))
    if not frames:
        raise FileNotFoundError(
            f"{RAW_DIR / 'D-quiet-02'} にCSVがありません。先に ingest を実行してください。"
        )
    return pd.concat(frames, ignore_index=True)


def aggregate_noise(points: pd.DataFrame) -> pd.DataFrame:
    """自治体ごとに、値のある最も新しい年度の平均を採る。

    dB は対数量なので、音響的には地点をエネルギー合成するのが正しい。ただしそれだと
    自治体内で最も大きい1地点にほぼ支配される。ここで見たいのは「幹線道路沿いの地点は
    平均してどのくらいうるさいか」なので、地点を等しく扱う算術平均にする。
    """
    per_year = (
        points.groupby(["code", "year"])["leq_day"].agg(value="mean", points="size").reset_index()
    )
    latest = (
        per_year.sort_values(["code", "year"], ascending=[True, False])
        .drop_duplicates("code", keep="first")
        .reset_index(drop=True)
    )
    latest["value"] = latest["value"].round(1)
    return latest.loc[:, ["code", "value", "year", "points"]]


def log_noise_fallbacks(points: pd.DataFrame, result: pd.DataFrame) -> None:
    """古い年度で埋めた自治体をログに残す（黙って混ぜない）。"""
    newest = int(points["year"].max())
    older = result[result["year"] != newest]
    logger.info(
        "[D-quiet-02] %d/53 自治体。うち %d 自治体は %d年度に測定が無く過去の年度で補完",
        len(result),
        len(older),
        newest,
    )
    for row in older.itertuples():
        logger.info("  %s ← %d年度（%d地点）", muni.BY_CODE[row.code].name, row.year, row.points)
    muni.check_coverage(result["code"], "road_noise_leq")


@handler("D-quiet-02")
def normalize_road_noise() -> IndicatorFrames:
    """自動車交通騒音調査の昼間等価騒音レベルを自治体ごとに平均する。

    調査地点は年度ごとに入れ替わるため、単年では測定のない自治体が出る
    （平成25年度は檜原村が欠測）。平成20〜25年度の6年分を合わせると53自治体
    すべてが埋まるので、以下の手順で埋める:

        1. 年度ごとに、測定地点を住所から自治体に割り当てて昼間Leqを平均する
        2. 自治体ごとに、値のある最も新しい年度の平均値を採る
        3. どの年度にも値が無い自治体は欠損のまま残す（0では埋めない）

    参照した年度と地点数も値に並べて書き、古い年度で埋めた自治体を後から追えるようにする。
    """
    points = load_noise_points()
    result = aggregate_noise(points)
    log_noise_fallbacks(points, result)
    return {"road_noise_leq": result}


# ---------------------------------------------------------------- しごとば


@handler("D-workspace-01")
def normalize_satellite_offices() -> IndicatorFrames:
    """TOKYOテレワークアプリ掲載サテライトオフィスを自治体ごとに数える。

    「区市町村コード」は検査数字つきの6桁（例: 132063）。都外の施設も混ざるが、
    5桁に詰めた時点で対象外として落ちる。
    """
    df = read_csv(raw_path("D-workspace-01", "offices"))
    return {"satellite_office_count": count_by_municipality(df)}


# ---------------------------------------------------------------- くらしのコスト

# 標準地の番号に入る用途区分。住宅地だけを地価水準の指標に使う（商業地=5 / 工業地=9）。
LAND_USE_RESIDENTIAL = 0


@handler("D-cost-01")
def normalize_land_price() -> IndicatorFrames:
    """地価公示のCSVから用途『住宅地』の㎡単価を自治体内で平均する。

    1行目が表題でヘッダは2行目。価格は当年の1㎡当たり価格を採る。
    住宅地の標準地は51/53自治体にしかなく、奥多摩町と檜原村には地点が無い。
    この2自治体は no_data のまま残す（0でも他の調査の値でも埋めない）。
    """
    df = read_csv(raw_path("D-cost-01", "points"), header=1)
    usage_col = pick_column(df, "land_use")
    before = len(df)
    df = df[df[usage_col].map(parse_number) == LAND_USE_RESIDENTIAL]
    logger.info("[D-cost-01] 用途『住宅地』で絞込み: %d → %d地点", before, len(df))
    return {"land_price_residential": mean_by_municipality(df, pick_column(df, "price"))}


# ---------------------------------------------------------------- つながり


@handler("D-community-01")
def normalize_npo() -> IndicatorFrames:
    """認証NPO法人を「主たる事務所」の所在地で数える。

    1行目が表題で、ヘッダは2行目にある。自治体名の列は無く、住所文字列から解決する。
    """
    df = read_csv(raw_path("D-community-01", "ninsyou"), header=1)
    return {"npo_count": count_by_municipality(df)}


# ---------------------------------------------------------------- 共通


@handler("D-common-01")
def normalize_base() -> IndicatorFrames:
    """人口推計から面積・人口（全指標の分母）を作り、municipal_base.csv に書く。

    区部・市部・総数といった集計行が同じ表に混ざるが、地域コードが 13000/13100 など
    自治体コードでないため `resolve_codes` の段階で落ちる。
    面積は ha 表記のことがあるため km2 に統一する。
    """
    df = resolve_codes(read_csv(raw_path("D-common-01", "population")))
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


# ---------------------------------------------------------------- エントリポイント


def run(dataset_id: str) -> IndicatorFrames:
    fn = HANDLERS[dataset_id]
    logger.info("[%s] 正規化: %s", dataset_id, fn.__doc__.splitlines()[0] if fn.__doc__ else "")
    frames = fn()
    write_indicators(dataset_id, frames)
    return frames


def main() -> int:
    setup_logging()
    ensure_dirs()

    ok, skipped, failed = 0, 0, 0
    for dataset_id in list(HANDLERS):
        if dataset_id not in HANDLERS:
            logger.warning(
                "[%s] 正規化の対象外のためスキップ",
                dataset_id,
            )
            skipped += 1
            continue
        try:
            run(dataset_id)
            ok += 1
        except FileNotFoundError as e:
            logger.warning("[%s] 未取得のためスキップ: %s", dataset_id, e)
            skipped += 1
        except Exception:
            logger.exception("[%s] 正規化に失敗", dataset_id)
            failed += 1

    logger.info("完了: 成功 %d / スキップ %d / 失敗 %d", ok, skipped, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
