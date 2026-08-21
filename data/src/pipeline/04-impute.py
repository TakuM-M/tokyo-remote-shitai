"""interim/indicators/ → interim/indicators_imputed/（欠損の補完）

原データに調査地点が無いだけで、周辺自治体と実態が変わらない欠損がある。
defs/imputation.py に列挙した規則にかぎり、参照自治体の値で埋める。

この段でやること:
    1. 指標CSVをそのまま indicators_imputed/ に複製する（規則の無い指標も含む）
    2. 規則のある指標だけ、対象自治体の行を参照自治体の値から作って足す
    3. 埋めたセルを interim/imputation_log.csv に残す

全指標を複製するのは、後段が「補完済みのディレクトリを1つ見れば全部揃う」状態に
なるようにするため。指標ごとにどちらのディレクトリを見るかを判断させない。

埋めるのはあくまで規則のある例外だけで、規則の無い欠損は欠損のまま残す。
補完値と実測値の区別は imputation_log.csv 経由で後段が付ける（0では埋めない）。

実行モジュール名にハイフンを含み import できないため、他の段と共有したい処理は
pipeline/common.py 側に置くこと。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from core import municipalities as muni
from core.config import (
    IMPUTATION_LOG_CSV,
    IMPUTED_INDICATOR_DIR,
    INDICATOR_DIR,
    ensure_dirs,
    setup_logging,
)
from core.io_utils import parse_numeric_column, read_csv, write_interim_csv
from defs.imputation import IMPUTATION_BY_INDICATOR, Imputation
from pipeline.common import IMPUTATION_LOG_COLUMNS, join_references

logger = logging.getLogger(__name__)


def _name(code: str) -> str:
    return muni.BY_CODE[code].name


def _fmt(value: float) -> str:
    """ログ用の数値表記。地価（10万円台）も割合（数%）も読める桁数に揃える。"""
    return f"{value:,.2f}"


def indicator_key_of(path: Path) -> str:
    """ファイル名 <データセットID>_<指標キー>.csv から指標キーを取り出す。

    データセットIDにアンダースコアは使わない（D-cost-01 のような形）ので、
    最初の1個で切れば指標キーが残る。
    """
    _, _, key = path.stem.partition("_")
    return key


# ---------------------------------------------------------------- 補完


def reference_values(values: pd.Series, rule: Imputation) -> dict[str, float]:
    """参照自治体のうち、実際に値を持っているものを集める。"""
    return {
        code: float(values[code])
        for code in rule.reference
        if code in values.index and pd.notna(values[code])
    }


def imputed_value(refs: dict[str, float], rule: Imputation) -> float:
    if rule.method == "mean":
        return sum(refs.values()) / len(refs)
    raise ValueError(f"未対応の補完方法: {rule.method}")


def apply_rule(df: pd.DataFrame, values: pd.Series, rule: Imputation) -> list[dict]:
    """1つの規則を指標CSVに適用する。`df` を直接書き換え、埋めたセルを返す。

    参照値は補完前のスナップショット `values` から採る。補完値をさらに別の
    補完の参照に使うと、根拠が1段ずつ薄まって追えなくなるため。
    """
    refs = reference_values(values, rule)
    if not refs:
        logger.warning(
            "[%s] 参照自治体（%s）に値が無いため補完しません。%s は欠損のままです。",
            rule.indicator,
            "、".join(_name(c) for c in rule.reference),
            "、".join(_name(c) for c in rule.targets),
        )
        return []

    missing_refs = [c for c in rule.reference if c not in refs]
    if missing_refs:
        logger.warning(
            "[%s] 参照自治体のうち %s に値が無いため、残りだけで補完します",
            rule.indicator,
            "、".join(_name(c) for c in missing_refs),
        )

    filled = imputed_value(refs, rule)
    logger.info("[%s] %s", rule.indicator, rule.reason)
    logger.info(
        "[%s] 参照値 %s の%s → %s",
        rule.indicator,
        " / ".join(f"{_name(c)} {_fmt(v)}" for c, v in refs.items()),
        {"mean": "平均"}[rule.method],
        _fmt(filled),
    )

    entries: list[dict] = []
    for code in rule.targets:
        if code in values.index and pd.notna(values[code]):
            logger.info(
                "[%s] %s(%s) は既に値 %s があるため上書きしません",
                rule.indicator,
                _name(code),
                code,
                _fmt(float(values[code])),
            )
            continue

        # CSVは全列を文字列のまま扱う（既存行の表記を触らないため）。
        # 追記する値も str() で入れる。float の str() は往復で桁を落とさない。
        text = str(filled)
        rows = df.index[df["_code"] == code]
        if len(rows):
            # 値だけが空の行がある場合。行を増やさずその場を埋める
            df.loc[rows, "value"] = text
        else:
            df.loc[len(df), ["code", "value", "_code"]] = [code, text, code]
        logger.info(
            "[%s] %s(%s) を %s で補完（%s / 参照 %s）",
            rule.indicator,
            _name(code),
            code,
            _fmt(filled),
            rule.method,
            "、".join(_name(c) for c in refs),
        )
        entries.append(
            {
                "indicator": rule.indicator,
                "code": code,
                "value": filled,
                "method": rule.method,
                # 実際に値が採れた参照先だけを残す。出力JSONの imputed_from になる
                "reference": join_references(refs),
            }
        )
    return entries


def impute_file(path: Path) -> list[dict]:
    """指標CSVを1本読み、補完してから indicators_imputed/ に書く。"""
    key = indicator_key_of(path)
    df = read_csv(path)
    if not {"code", "value"} <= set(df.columns):
        logger.warning("%s: code,value 列が無いためそのまま複製する", path.name)
        write_interim_csv(df, IMPUTED_INDICATOR_DIR / path.name)
        return []

    # 補完対象の照合用。表記ゆれ（6桁コード等）を吸収した5桁コードを一時列に持つ
    df["_code"] = df["code"].map(muni.normalize_code)
    numeric = parse_numeric_column(df["value"])
    values = pd.Series(numeric.to_numpy(), index=df["_code"], dtype=float)
    values = values[values.index.notna()].groupby(level=0).mean()

    entries: list[dict] = []
    for rule in IMPUTATION_BY_INDICATOR.get(key, ()):
        entries += apply_rule(df, values, rule)

    write_interim_csv(df.drop(columns="_code"), IMPUTED_INDICATOR_DIR / path.name)
    return entries


def drop_stale_outputs(source_names: set[str]) -> None:
    """元が消えた出力を残さない。古い値が後段に混ざるのを防ぐ。"""
    for path in sorted(IMPUTED_INDICATOR_DIR.glob("*.csv")):
        if path.name not in source_names:
            logger.info("元ファイルが無くなったため削除: %s", path.name)
            path.unlink()


def write_log(entries: list[dict]) -> None:
    """埋めたセルの一覧を書く。空でもヘッダだけは書いて「実行済み」を示す。"""
    frame = pd.DataFrame(entries, columns=list(IMPUTATION_LOG_COLUMNS))
    write_interim_csv(frame, IMPUTATION_LOG_CSV)


# ---------------------------------------------------------------- エントリポイント


def main() -> int:
    setup_logging()
    ensure_dirs()

    sources = sorted(INDICATOR_DIR.glob("*.csv"))
    if not sources:
        logger.warning(
            "%s に指標CSVがありません。先に normalize → spatial_join を実行してください。",
            INDICATOR_DIR,
        )

    logger.info("---- 欠損補完 ----")
    entries: list[dict] = []
    for path in sources:
        entries += impute_file(path)

    drop_stale_outputs({p.name for p in sources})
    write_log(entries)

    planned = sum(len(r.targets) for rules in IMPUTATION_BY_INDICATOR.values() for r in rules)
    logger.info(
        "完了: 指標 %d 本を %s に複製 / 補完 %d セル（規則上の対象 %d セル）",
        len(sources),
        IMPUTED_INDICATOR_DIR.name,
        len(entries),
        planned,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
