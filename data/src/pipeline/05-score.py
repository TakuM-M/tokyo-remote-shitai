"""interim/ → processed/municipalities.json（スコア算出）

以下の手順を実装する:
    1. 面積あたり / 人口1万人あたりに換算して規模の差を除く
    2. 分母の小さい自治体で値が跳ねる指標は、全体の中央値に寄せて縮小する（`apply_shrinkage`）
    3. 値のある自治体の中での順位を 0〜100 に直す（`percentile_rank`）
    4. 「低いほど良い」指標は 100 - score で反転
    5. 軸スコア = 軸内の指標スコアの加重平均（重みは指標ごとに定義）

総合スコア:
- 重みはユーザーが動かすため、ここでは計算しない。
- Σ(軸スコア × 重み) / Σ(重み) はフロント側で計算する。

欠損は0で埋めず `value: null` + `status: "no_data"` として残す。
埋めてしまうと「データが無い自治体」が「悪い自治体」に化けるため。

例外として、原データに調査地点が無いだけの欠損を周辺自治体の値で代替することがある。
補完そのものは前段の 04-impute が行い、ここでは埋まった値を他と同じように
スコア化した上で `status: "imputed"` と `imputed_from`（参照した自治体コード）を
出力に付けるだけ。実測値と推定値が出力から見分けられる状態を保つ。
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from core import municipalities as muni
from core.config import (
    BASE_CSV,
    DEMO_JSON,
    IMPUTATION_LOG_CSV,
    IMPUTED_INDICATOR_DIR,
    OUTPUT_JSON,
    SCHEMA_VERSION,
    ensure_dirs,
    indicator_csv,
    setup_logging,
)
from core.io_utils import parse_numeric_column, read_csv, write_json
from defs import datasets
from defs.indicators import (
    AXES,
    DEFAULT_WEIGHTS,
    INDICATOR_BY_KEY,
    INDICATORS,
    PRESETS,
    Indicator,
)
from pipeline.common import split_references

logger = logging.getLogger(__name__)

N_MUNI = len(muni.CODES)

# 04-impute が埋めたセル: {指標キー: {自治体コード: [参照した自治体コード, ...]}}
ImputedCells = dict[str, dict[str, list[str]]]


# ---------------------------------------------------------------- 正規化の基本操作


def percentile_rank(s: pd.Series) -> pd.Series:
    """値のある自治体の中での順位を 0〜100 に直す。欠損はそのまま欠損で残す。

    値の大きさではなく順位を採るのは、指標ごとに分布の形が違いすぎるため。
    NPO密度やサテライトオフィス密度は上位数自治体だけが極端に大きい右裾の長い
    分布で、値をそのまま min-max にかけると残りの自治体が1桁点に潰れる。
    順位なら分布の形によらず中央値がほぼ50点に来るので、軸をまたいで比べられる。

    同値は平均順位を分け合う。順位から0.5を引くのは、上端だけが100点になる
    非対称を避けるため。値のある自治体が1つだけなら50点（比較相手がいない）、
    全自治体が同値でも全員50点になる。
    """
    n = int(s.notna().sum())
    if n == 0:
        return pd.Series(np.nan, index=s.index, dtype=float)
    return (s.rank(method="average") - 0.5) / n * 100.0


def apply_direction(scores: pd.Series, indicator: Indicator) -> pd.Series:
    """「低いほど良い」指標を反転する。"""
    return 100.0 - scores if indicator.direction == "lower_is_better" else scores


def score_indicator(values: pd.Series, indicator: Indicator) -> pd.Series:
    return apply_direction(percentile_rank(values), indicator).round(1)


# ---------------------------------------------------------------- 入力の読み込み


def load_base() -> pd.DataFrame:
    """面積・人口（分母）を読む。無ければ空の枠を返す"""
    frame = pd.DataFrame(
        np.nan, index=pd.Index(muni.CODES, name="code"), columns=["area_km2", "population"]
    )
    if not BASE_CSV.exists():
        logger.warning(
            "%s がありません。面積・人口が無いため『◯◯あたり』の指標は算出できません。", BASE_CSV
        )
        return frame

    df = read_csv(BASE_CSV)
    df["code"] = df["code"].map(muni.normalize_code)
    df = df[df["code"].notna()].set_index("code")
    for col in frame.columns:
        if col not in df.columns:
            logger.warning("%s に %s 列がありません", BASE_CSV.name, col)
            continue
        values = parse_numeric_column(df[col])
        frame[col] = values.groupby(level=0).first().reindex(muni.CODES)
    return frame


def has_imputed_indicators() -> bool:
    """04-impute の出力があるか。無ければ補完前の indicators/ にフォールバックする。

    補完はスコアの前提ではないので、04-impute 未実行でも従来どおり動かす。
    ただし黙って落ちると「補完したはずの自治体が no_data のまま」の原因が
    分からなくなるため警告を出す。
    """
    if IMPUTED_INDICATOR_DIR.is_dir() and any(IMPUTED_INDICATOR_DIR.glob("*.csv")):
        return True
    logger.warning(
        "%s が空のため補完前の指標を読みます（欠損補完は make impute で作られます）",
        IMPUTED_INDICATOR_DIR,
    )
    return False


def resolve_indicator_csv(indicator: Indicator, imputed: bool) -> Path | None:
    """読み込む指標CSVを決める。補完済みのものを優先する。"""
    candidates = [indicator_csv(indicator.dataset_id, indicator.key)]
    if imputed:
        candidates.insert(0, indicator_csv(indicator.dataset_id, indicator.key, imputed=True))
    return next((p for p in candidates if p.exists()), None)


def load_indicator_series(indicator: Indicator, imputed: bool = False) -> pd.Series:
    """指標CSVを1本読み、53自治体ぶんに揃えた値の並びにする。"""
    empty = pd.Series(np.nan, index=pd.Index(muni.CODES, name="code"), dtype=float)
    path = resolve_indicator_csv(indicator, imputed)
    if path is None:
        logger.warning(
            "%s がありません（加工が未実装・未実行）",
            indicator_csv(indicator.dataset_id, indicator.key).name,
        )
        return empty

    df = read_csv(path)
    if not {"code", "value"} <= set(df.columns):
        logger.warning("%s: code,value 列が無いため読み飛ばす", path.name)
        return empty

    codes = df["code"].map(muni.normalize_code)
    values = pd.Series(parse_numeric_column(df["value"]).to_numpy(), index=codes, dtype=float)
    values = values[values.index.notna()]
    # 集約は前段で済んでいるはずだが、取りこぼしがあっても黙って1行目を採らない
    return values.groupby(level=0).mean().reindex(muni.CODES)


def load_indicator_values() -> pd.DataFrame:
    """指標CSVを集めて 自治体 × 指標 の表にする（補完済みがあればそちらから）。"""
    imputed = has_imputed_indicators()
    frame = pd.DataFrame(index=pd.Index(muni.CODES, name="code"))
    for ind in INDICATORS:
        frame[ind.key] = load_indicator_series(ind, imputed)
        n = int(frame[ind.key].notna().sum())
        logger.info("読み込み: %-28s %2d/%d 自治体", ind.key, n, N_MUNI)
    return frame


def load_imputed_cells() -> ImputedCells:
    """04-impute が埋めたセルを読む。無ければ空（補完なしとして扱う）。

    値そのものは指標CSV側に入っているので、ここで読むのは「どのセルが推定値か」
    という出所の情報だけ。
    """
    if not IMPUTATION_LOG_CSV.exists():
        logger.info("%s がありません。補完値なしとして出力します。", IMPUTATION_LOG_CSV.name)
        return {}

    df = read_csv(IMPUTATION_LOG_CSV)
    cells: ImputedCells = {}
    for row in df.to_dict("records"):
        code = muni.normalize_code(row.get("code"))
        key = str(row.get("indicator", ""))
        if code is None or key not in INDICATOR_BY_KEY:
            logger.warning("補完ログの行を読み飛ばす: %s", row)
            continue
        cells.setdefault(key, {})[code] = split_references(row.get("reference"))
    total = sum(len(v) for v in cells.values())
    logger.info("補完ログ: %d セル（%s）", total, "、".join(cells) or "なし")
    return cells


def denominator_series(indicator: Indicator, base: pd.DataFrame) -> pd.Series | None:
    """指標の分母を取り出す。分母を取らない指標は None。0は欠損にする。"""
    if indicator.denominator == "area_km2":
        denom = base["area_km2"]
    elif indicator.denominator == "population_10k":
        denom = base["population"] / 10_000.0
    elif indicator.denominator == "population":
        denom = base["population"]
    else:
        return None
    return denom.replace(0, np.nan)


def apply_denominator(values: pd.Series, indicator: Indicator, base: pd.DataFrame) -> pd.Series:
    """面積あたり / 人口1万人あたりに換算する。分母が無い自治体は欠損にする。"""
    denom = denominator_series(indicator, base)
    if denom is None:
        return values
    if denom.isna().all():
        logger.warning(
            "[%s] 分母(%s)が空のため換算できません", indicator.key, indicator.denominator
        )
    return values / denom


def apply_shrinkage(per: pd.Series, indicator: Indicator, base: pd.DataFrame) -> pd.Series:
    """分母の小さい自治体で「◯◯あたり」の値が跳ねるのを抑える。

    分母が小さいほど、分子が1動いただけで値が大きく振れる。檜原村（人口1,747人）は
    NPOが1件増減するだけで密度が±5.7件/万人動き、これは下位40自治体が収まっている
    範囲より広い。生の値をそのまま順位に使うと、ほとんど情報の無い数字が上位を占める。

    そこで「全体の中央値どおりの密度で、分母を m だけ余計に観測した」という仮想データを
    足してから割り直す:

        (分子 + 中央値 × m) / (分母 + m)

    結果は実データと中央値を 分母 : m の比で混ぜた値になる。分母が m より十分大きい
    自治体はほぼ動かず、小さい自治体ほど中央値に寄る。閾値で切り捨てるのと違い、
    信頼できる度合いに比例して連続的に効く。

    寄せ先に平均でなく中央値を使うのは、密度の分布が右に裾を引いていて平均が
    「ふつう」の位置に無いため（NPO密度は平均6.49に対し中央値4.44で、平均は上位2割の
    位置にある）。判断材料の無い自治体は真ん中に置く、という percentile_rank の
    「値のある自治体が1つだけなら50点」と同じ扱いに揃える。
    """
    m = indicator.shrink_denominator
    denom = denominator_series(indicator, base) if m else None
    if denom is None:
        return per
    prior = per.median()
    if not np.isfinite(prior):
        logger.warning("[%s] 中央値が取れないため縮小を適用しません", indicator.key)
        return per
    logger.info(
        "[%s] 小標本の縮小: 分母 %g（%s）ぶんを中央値 %.2f で補う",
        indicator.key,
        m,
        indicator.denominator,
        prior,
    )
    # per * denom は分子そのもの。欠損は欠損のまま残る。
    return (per * denom + prior * m) / (denom + m)


# ---------------------------------------------------------------- スコア算出


def compute(values: pd.DataFrame, base: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """指標ごとに 生値 / 換算値 / スコア を作る。"""
    raw, normalized, scored = {}, {}, {}
    for ind in INDICATORS:
        series = (
            values[ind.key]
            if ind.key in values.columns
            else pd.Series(np.nan, index=values.index, dtype=float)
        )
        series = pd.to_numeric(series, errors="coerce")
        per = apply_denominator(series, ind, base)
        raw[ind.key] = series
        # 出力する per_10k / per_km2 は換算しただけの値を入れる。縮小をかけた値は
        # 順位づけにだけ使う（詳細パネルには実際の密度を出したいため）。
        normalized[ind.key] = per
        scored[ind.key] = score_indicator(apply_shrinkage(per, ind, base), ind)
    return {
        "raw": pd.DataFrame(raw, index=values.index),
        "normalized": pd.DataFrame(normalized, index=values.index),
        "score": pd.DataFrame(scored, index=values.index),
    }


def axis_scores(scores: pd.DataFrame) -> pd.DataFrame:
    """軸スコア = 軸内の指標スコアの加重平均。全指標が欠損なら NaN（0にはしない）。

    欠損した指標は重みごと外し、残った指標の重みの合計で割る。指標が1本しか
    埋まらない自治体では、その1本がそのまま軸スコアになる。
    """
    out = {}
    for axis in AXES:
        used = [
            i
            for i in INDICATORS
            if i.axis == axis.key and i.include_in_axis and i.key in scores.columns
        ]
        if not used:
            out[axis.key] = np.nan
            continue
        sub = scores[[i.key for i in used]]
        weights = pd.Series({i.key: i.weight for i in used})
        # 欠損セルの重みを0にしてから、残った重みで正規化する
        effective = sub.notna().mul(weights, axis=1)
        total = effective.sum(axis=1).replace(0, np.nan)
        out[axis.key] = (sub.mul(weights, axis=1).sum(axis=1, skipna=True) / total).round(1)
    return pd.DataFrame(out, index=scores.index)


# ---------------------------------------------------------------- 出力


def _clean(value: object) -> float | None:
    """NaN を JSON の null にする。"""
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    if isinstance(value, (np.floating, np.integer)):
        value = value.item()
    return round(value, 4) if isinstance(value, float) else value


def build_meta(demo: bool = False) -> dict:
    used_datasets = {i.dataset_id for i in INDICATORS}
    meta: dict = {
        "generated_at": date.today().isoformat(),
        "version": SCHEMA_VERSION,
        "axes": [
            {
                "key": a.key,
                "label": a.label,
                "description": a.description,
                "indicators": [
                    {
                        "key": i.key,
                        "label": i.label,
                        "unit": i.unit,
                        "direction": i.direction,
                        "definition": i.definition,
                        "source": i.dataset_id,
                        "weight": i.weight,
                        "reference_only": not i.include_in_axis,
                    }
                    for i in INDICATORS
                    if i.axis == a.key
                ],
            }
            for a in AXES
        ],
        "default_weights": DEFAULT_WEIGHTS,
        "presets": list(PRESETS),
        "sources": datasets.sources_for(used_datasets),
    }
    if demo:
        meta["demo"] = True
        meta["note"] = "スキーマ確認用のダミーデータです。実データではありません。"
    return meta


def build_document(
    computed: dict[str, pd.DataFrame],
    axes: pd.DataFrame,
    base: pd.DataFrame,
    imputed: ImputedCells | None = None,
    demo: bool = False,
) -> dict:
    doc: dict = {"meta": build_meta(demo), "municipalities": []}
    imputed = imputed or {}

    for m in muni.MUNICIPALITIES:
        entry: dict = {
            "code": m.code,
            "name": m.name,
            "kind": m.kind,
            "region": m.region,
            "area_km2": _clean(base.at[m.code, "area_km2"]),
            "population": _clean(base.at[m.code, "population"]),
            "scores": {a.key: _clean(axes.at[m.code, a.key]) for a in AXES},
            "indicators": {},
        }
        for ind in INDICATORS:
            value = _clean(computed["raw"].at[m.code, ind.key])
            item: dict = {
                "value": value,
                "score": _clean(computed["score"].at[m.code, ind.key]),
                "source": ind.dataset_id,
            }
            if ind.unit:
                item["unit"] = ind.unit
            if ind.per_key:
                item[ind.per_key] = _clean(computed["normalized"].at[m.code, ind.key])
            # フロントで分岐しやすいよう status は常に持たせる。
            # 補完値は "imputed" として実測値と区別し、参照元も添える。
            refs = imputed.get(ind.key, {}).get(m.code)
            if value is None:
                item["status"] = "no_data"
            elif refs:
                item["status"] = "imputed"
                item["imputed_from"] = refs
            else:
                item["status"] = "ok"
            entry["indicators"][ind.key] = item
        doc["municipalities"].append(entry)
    return doc


def report_coverage(
    computed: dict[str, pd.DataFrame], axes: pd.DataFrame, imputed: ImputedCells | None = None
) -> None:
    """どの指標がどれだけ埋まったかを出す（欠損の把握は品質管理そのもの）。

    補完で埋まったセルは別に数える。件数だけ見て「全自治体そろった」と
    読み違えないようにするため。
    """
    imputed = imputed or {}
    logger.info("---- カバレッジ（%d自治体中） ----", N_MUNI)
    for ind in INDICATORS:
        values = computed["raw"][ind.key]
        n = int(values.notna().sum())
        mark = "  " if n == N_MUNI else ("!!" if n == 0 else " ~")
        missing = [muni.BY_CODE[c].name for c in muni.CODES if pd.isna(values[c])]
        filled = [muni.BY_CODE[c].name for c in muni.CODES if c in imputed.get(ind.key, {})]
        logger.info(
            "%s %-28s %2d/%d%s%s",
            mark,
            ind.key,
            n,
            N_MUNI,
            "  うち補完: " + "、".join(filled) if filled else "",
            "  欠損: " + "、".join(missing) if missing else "",
        )

    logger.info("---- 軸スコア ----")
    for axis in AXES:
        s = axes[axis.key].dropna()
        if s.empty:
            logger.warning("   %-12s 算出できた自治体なし", axis.key)
            continue
        top = [f"{muni.BY_CODE[c].name} {s[c]:.0f}" for c in s.nlargest(3).index]
        bottom = [f"{muni.BY_CODE[c].name} {s[c]:.0f}" for c in s.nsmallest(3).index]
        logger.info(
            "   %-12s %2d/%d 自治体で算出  上位: %s / 下位: %s",
            axis.key,
            len(s),
            N_MUNI,
            "、".join(top),
            "、".join(bottom),
        )


# ---------------------------------------------------------------- ダミーデータ

# (区部の中心値, 多摩の中心値, ばらつき)。実データの平均・標準偏差をおおまかになぞる。
DEMO_PROFILE: dict[str, tuple[float, float, float]] = {
    "pm25_annual_avg": (5.2, 4.8, 0.4),
    "road_noise_leq": (68.0, 66.7, 1.8),
    "park_area": (1_660_000, 1_250_000, 900_000),
    "green_coverage_ratio": (2.5, 27.0, 10.0),
    "satellite_office_count": (21, 5, 12),
    "land_price_residential": (1_120_000, 260_000, 400_000),
    "npo_count": (323, 61, 150),
}


def demo_values(seed: int = 20260816) -> tuple[pd.DataFrame, pd.DataFrame]:
    """フロント開発を先に始めるためのダミー値。

    実データの傾向（区部＝サテライトオフィスと地価が高い / 多摩＝緑が多い）を
    ゆるく再現しつつ、欠損の表示確認のためにいくつか穴を空けておく。
    """
    rng = np.random.default_rng(seed)
    codes = list(muni.CODES)
    is_ward = np.array([muni.BY_CODE[c].region == "区部" for c in codes])
    n = len(codes)

    base = pd.DataFrame(
        {
            "area_km2": np.where(is_ward, rng.uniform(10, 62, n), rng.uniform(6, 226, n)),
            "population": np.where(
                is_ward,
                rng.uniform(66_000, 960_000, n),
                rng.uniform(1_700, 575_000, n),
            ).round(),
        },
        index=pd.Index(codes, name="code"),
    )

    data = {}
    for key, (ward_mu, tama_mu, sd) in DEMO_PROFILE.items():
        mu = np.where(is_ward, ward_mu, tama_mu)
        # 割合の指標が100%を超えないよう頭を押さえる
        upper = 100.0 if INDICATOR_BY_KEY[key].unit == "%" else None
        data[key] = np.clip(rng.normal(mu, sd), 0.1, upper)
    frame = pd.DataFrame(data, index=pd.Index(codes, name="code"))

    # 欠損の見え方を確認するための穴。実データで欠けている指標に合わせてある
    # （PM2.5は測定局の無い自治体、サテライトオフィスは掲載の無い自治体、
    #   公園は檜原村、地価は檜原村・奥多摩町に原データが無い）。
    # ダミーには補完ログが無いので、実データでは補完される地価もここでは
    # no_data のまま出る（ハッチング表示の確認用としてはこれで都合がよい）。
    frame.loc[rng.choice(codes, 10, replace=False), "pm25_annual_avg"] = np.nan
    frame.loc[rng.choice(codes, 12, replace=False), "satellite_office_count"] = np.nan
    frame.loc[["13307"], "park_area"] = np.nan
    frame.loc[["13307", "13308"], "land_price_residential"] = np.nan
    return frame, base


# ---------------------------------------------------------------- エントリポイント


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="指標をスコア化して municipalities.json を作る")
    parser.add_argument(
        "--demo", action="store_true", help="ダミーデータで municipalities.sample.json を生成"
    )
    args = parser.parse_args(argv)

    setup_logging()
    ensure_dirs()

    if args.demo:
        values, base = demo_values()
        imputed: ImputedCells = {}
    else:
        base = load_base()
        values = load_indicator_values()
        imputed = load_imputed_cells()

    computed = compute(values, base)
    axes = axis_scores(computed["score"])
    report_coverage(computed, axes, imputed)

    doc = build_document(computed, axes, base, imputed, demo=args.demo)
    write_json((DEMO_JSON if args.demo else OUTPUT_JSON), doc)

    if not args.demo and axes.notna().to_numpy().sum() == 0:
        logger.warning(
            "スコアが1件も算出されていません。ingest → normalize → spatial_join の順に実行し、"
            "interim/indicators/ にファイルが出ているか確認してください。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
