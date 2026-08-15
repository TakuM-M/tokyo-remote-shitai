"""processed/municipalities.json の検証

スキーマ・値域（スコアは0〜100）・欠損表現（value: null と status: "no_data" の対応）が
崩れていないかを確認する。
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from analysis._report import heading, print_list
from core import municipalities as muni
from core.config import DEMO_JSON, OUTPUT_JSON, SCHEMA_VERSION, setup_logging
from defs.indicators import AXES, AXIS_KEYS, INDICATOR_BY_KEY, INDICATORS, Indicator

logger = logging.getLogger(__name__)

ERROR = "エラー"
WARN = "警告"

# 軸スコアは指標スコア（小数第1位）の平均なので、丸めの分だけずれ得る
AXIS_TOLERANCE = 0.1
# 「◯◯あたり」の検算。面積・人口も丸めて出力されているため緩めに見る
PER_TOLERANCE = 1e-3

ITEM_KEYS = {"value", "score", "source", "status", "unit", "per_10k", "per_km2"}


@dataclass(frozen=True)
class Issue:
    level: str
    code: str  # 同種の指摘をまとめる見出し
    detail: str


class Report:
    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def error(self, code: str, detail: str = "") -> None:
        self.issues.append(Issue(ERROR, code, detail))

    def warn(self, code: str, detail: str = "") -> None:
        self.issues.append(Issue(WARN, code, detail))

    def count(self, level: str) -> int:
        return sum(1 for i in self.issues if i.level == level)


def is_number(value: object) -> bool:
    """JSON の数値。真偽値と NaN/Infinity は数値として認めない。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def in_score_range(value: object) -> bool:
    return is_number(value) and 0.0 <= float(value) <= 100.0


def close(a: float, b: float, tolerance: float) -> bool:
    # 許容差ちょうどの比較（丸め由来のずれ）が浮動小数の誤差で外れないよう少し余裕をみる
    return abs(a - b) <= tolerance + 1e-9


# ---------------------------------------------------------------- meta


def only_dicts(values: object, rep: Report, where: str) -> list[dict]:
    """配列からオブジェクトでない要素を落とす。壊れた入力でも検証を最後まで進めるため。"""
    items = list(values) if isinstance(values, (list, tuple)) else []
    if bad := [v for v in items if not isinstance(v, dict)]:
        rep.error("配列にオブジェクトでない要素がある", f"{where}: {len(bad)}件")
    return [v for v in items if isinstance(v, dict)]


def check_meta(doc: dict, rep: Report) -> None:
    meta = doc.get("meta")
    if not isinstance(meta, dict):
        rep.error("meta が無い", "トップレベルに meta オブジェクトが必要")
        return

    if meta.get("version") != SCHEMA_VERSION:
        rep.warn(
            "スキーマバージョンが config と違う",
            f"出力 {meta.get('version')!r} / config.SCHEMA_VERSION {SCHEMA_VERSION!r}",
        )
    try:
        date.fromisoformat(str(meta.get("generated_at")))
    except ValueError:
        rep.error("generated_at が日付として読めない", repr(meta.get("generated_at")))

    check_axes(meta, rep)
    check_weights(meta, rep)
    check_sources(meta, rep)


def check_axes(meta: dict, rep: Report) -> None:
    if not isinstance(meta.get("axes"), list):
        rep.error("meta.axes が配列でない")
        return
    axes = only_dicts(meta["axes"], rep, "meta.axes")
    if [a.get("key") for a in axes] != list(AXIS_KEYS):
        rep.error(
            "meta.axes が定義と一致しない",
            f"出力 {[a.get('key') for a in axes]} / 定義 {list(AXIS_KEYS)}",
        )
        return

    for axis, defined in zip(axes, AXES, strict=True):
        if axis.get("label") != defined.label:
            rep.warn("軸ラベルが定義と違う", f"{defined.key}: {axis.get('label')!r}")
        items = only_dicts(axis.get("indicators"), rep, f"meta.axes.{defined.key}.indicators")
        keys = [i.get("key") for i in items]
        expected = [i.key for i in INDICATORS if i.axis == defined.key]
        if keys != expected:
            rep.error("軸の指標一覧が定義と一致しない", f"{defined.key}: {keys} / 定義 {expected}")
            continue
        for item in items:
            check_indicator_meta(item, rep)


def check_indicator_meta(item: dict, rep: Report) -> None:
    ind = INDICATOR_BY_KEY[item["key"]]
    where = f"meta.{ind.key}"
    if item.get("direction") != ind.direction:
        rep.error("指標の向きが定義と違う", f"{where}: {item.get('direction')!r}")
    if item.get("source") != ind.dataset_id:
        rep.error("指標の出典が定義と違う", f"{where}: {item.get('source')!r}")
    if bool(item.get("reference_only")) is ind.include_in_axis:
        rep.error("reference_only が定義と逆", f"{where}: {item.get('reference_only')!r}")
    if item.get("unit") != ind.unit:
        rep.warn("指標の単位が定義と違う", f"{where}: {item.get('unit')!r} / 定義 {ind.unit!r}")
    if not item.get("definition"):
        rep.warn("指標の説明が空", where)


def check_weights(meta: dict, rep: Report) -> None:
    weights = meta.get("default_weights")
    if not isinstance(weights, dict) or set(weights) != set(AXIS_KEYS):
        rep.error("default_weights の軸がそろっていない", str(weights))
    elif not all(is_number(v) and v >= 0 for v in weights.values()):
        rep.error("default_weights に数値でない値がある", str(weights))

    if not isinstance(meta.get("presets"), list) or not meta["presets"]:
        rep.error("presets が無い")
        return
    for preset in only_dicts(meta["presets"], rep, "meta.presets"):
        key = preset.get("key", "?")
        if not preset.get("label"):
            rep.warn("プリセットのラベルが空", str(key))
        w = preset.get("weights")
        if not isinstance(w, dict) or set(w) != set(AXIS_KEYS):
            rep.error("プリセットの重みの軸がそろっていない", f"{key}: {w}")
        elif not all(is_number(v) and v >= 0 for v in w.values()):
            rep.error("プリセットの重みに数値でない値がある", f"{key}: {w}")


def check_sources(meta: dict, rep: Report) -> None:
    if not isinstance(meta.get("sources"), list):
        rep.error("meta.sources が配列でない")
        return
    sources = only_dicts(meta["sources"], rep, "meta.sources")
    listed = {s.get("id") for s in sources}
    for missing in sorted({i.dataset_id for i in INDICATORS} - listed):
        rep.error("使用した出典が sources に無い", missing)
    for src in sources:
        where = str(src.get("id"))
        for field in ("name", "org", "url"):
            if not src.get(field):
                rep.error("出典の必須項目が空", f"{where}.{field}")
        if not str(src.get("url", "")).startswith("http"):
            rep.error("出典のURLがURLでない", f"{where}: {src.get('url')!r}")
        if not src.get("license"):
            rep.warn("出典のライセンスが未記入", where)


# ---------------------------------------------------------------- municipalities


def check_municipalities(doc: dict, rep: Report) -> list[dict]:
    if not isinstance(doc.get("municipalities"), list):
        rep.error("municipalities が配列でない")
        return []
    entries = only_dicts(doc["municipalities"], rep, "municipalities")

    codes = [e.get("code") for e in entries]
    if len(codes) != len(set(codes)):
        dup = sorted({c for c in codes if codes.count(c) > 1})
        rep.error("自治体コードが重複している", ", ".join(map(str, dup)))
    for extra in sorted(set(codes) - set(muni.CODES)):
        rep.error("対象外の自治体が含まれている", str(extra))
    for lack in sorted(set(muni.CODES) - set(codes)):
        rep.error("自治体が足りない", f"{lack} {muni.BY_CODE[lack].name}")

    for entry in entries:
        check_entry(entry, rep)
    check_all_missing_indicators(entries, rep)
    return entries


def check_entry(entry: dict, rep: Report) -> None:
    code = str(entry.get("code"))
    m = muni.BY_CODE.get(code)
    if m is None:
        return
    where = f"{code} {m.name}"

    for field, expected in (("name", m.name), ("kind", m.kind), ("region", m.region)):
        if entry.get(field) != expected:
            rep.error("自治体の属性がマスタと違う", f"{where}.{field}: {entry.get(field)!r}")
    for field in ("area_km2", "population"):
        value = entry.get(field)
        if value is None:
            rep.warn("面積・人口が欠けている", f"{where}.{field}")
        elif not is_number(value) or value <= 0:
            rep.error("面積・人口が正の数でない", f"{where}.{field}: {value!r}")

    scores = entry.get("scores")
    if not isinstance(scores, dict) or set(scores) != set(AXIS_KEYS):
        rep.error("scores の軸がそろっていない", where)
    else:
        for axis, value in scores.items():
            if value is not None and not in_score_range(value):
                rep.error("軸スコアが0〜100の外", f"{where}.{axis}: {value!r}")

    indicators = entry.get("indicators")
    if not isinstance(indicators, dict):
        rep.error("indicators がオブジェクトでない", where)
        return
    if set(indicators) != set(INDICATOR_BY_KEY):
        lacking = sorted(set(INDICATOR_BY_KEY) - set(indicators))
        extra = sorted(set(indicators) - set(INDICATOR_BY_KEY))
        rep.error("指標がそろっていない", f"{where}: 不足 {lacking} / 余分 {extra}")
    for key, item in indicators.items():
        if key in INDICATOR_BY_KEY:
            check_item(where, INDICATOR_BY_KEY[key], item, entry, rep)

    if isinstance(scores, dict):
        check_axis_scores(where, scores, indicators, rep)


def check_item(where: str, ind: Indicator, item: dict, entry: dict, rep: Report) -> None:
    at = f"{where}.{ind.key}"
    if not isinstance(item, dict):
        rep.error("指標がオブジェクトでない", at)
        return
    for field in ("value", "score", "source", "status"):
        if field not in item:
            rep.error("指標の必須項目が無い", f"{at}.{field}")
    if extra := sorted(set(item) - ITEM_KEYS):
        rep.warn("スキーマに無いキーがある", f"{at}: {extra}")

    value, status = item.get("value"), item.get("status")
    if status not in ("ok", "no_data"):
        rep.error("status が ok / no_data でない", f"{at}: {status!r}")
    # 欠損を0で埋めない規約の要。value と status は必ず対応する。
    elif (value is None) != (status == "no_data"):
        rep.error("value と status が対応していない", f"{at}: value={value!r} status={status!r}")
    if value is not None and not is_number(value):
        rep.error("value が数値でない", f"{at}: {value!r}")

    score = item.get("score")
    if score is not None and not in_score_range(score):
        rep.error("指標スコアが0〜100の外", f"{at}: {score!r}")
    if value is not None and score is None:
        rep.warn("値はあるのにスコアが無い", at)
    if value is None and score is not None:
        rep.error("値が無いのにスコアがある", f"{at}: {score!r}")
    if item.get("source") != ind.dataset_id:
        rep.error("指標の出典が定義と違う", f"{at}: {item.get('source')!r}")

    check_per_value(at, ind, item, entry, rep)


def check_per_value(at: str, ind: Indicator, item: dict, entry: dict, rep: Report) -> None:
    """「◯◯あたり」の換算値が定義どおり入っているかと、その値を検算する。"""
    unexpected = {"per_10k", "per_km2"} - {ind.per_key}
    for key in sorted(unexpected & set(item)):
        rep.error("換算値が定義に無いのに入っている", f"{at}.{key}")
    if ind.per_key is None:
        return
    if ind.per_key not in item:
        rep.error("換算値が入っていない", f"{at}.{ind.per_key}")
        return

    per, value = item[ind.per_key], item.get("value")
    if per is None or value is None:
        if (per is None) != (value is None):
            rep.warn("値と換算値のどちらか一方だけがある", at)
        return
    denom = (
        entry.get("area_km2")
        if ind.denominator == "area_km2"
        else (entry.get("population") or 0) / 10_000.0
    )
    if not is_number(denom) or denom <= 0 or not is_number(per):
        return
    expected = float(value) / float(denom)
    if not close(float(per), expected, max(abs(expected) * PER_TOLERANCE, PER_TOLERANCE)):
        rep.warn("換算値が 値÷分母 と合わない", f"{at}: {per} / 計算 {expected:.4f}")


def check_axis_scores(where: str, scores: dict, indicators: dict, rep: Report) -> None:
    """軸スコア = 軸内の指標スコアの単純平均（参考指標は除く）を検算する。"""
    for axis in AXES:
        keys = [i.key for i in INDICATORS if i.axis == axis.key and i.include_in_axis]
        got = [
            indicators[k]["score"]
            for k in keys
            if isinstance(indicators.get(k), dict) and in_score_range(indicators[k].get("score"))
        ]
        actual = scores.get(axis.key)
        if not got:
            if actual is not None:
                rep.error("指標が全欠損なのに軸スコアがある", f"{where}.{axis.key}: {actual!r}")
            continue
        expected = round(sum(got) / len(got), 1)
        if actual is None:
            rep.error("指標はあるのに軸スコアが null", f"{where}.{axis.key}")
        elif not close(float(actual), expected, AXIS_TOLERANCE):
            rep.error(
                "軸スコアが指標スコアの平均と合わない",
                f"{where}.{axis.key}: 出力 {actual} / 平均 {expected}",
            )


def check_all_missing_indicators(entries: list[dict], rep: Report) -> None:
    """全自治体で値が無い指標。スキーマ上は正しいが、画面には何も出ない。"""
    for key in INDICATOR_BY_KEY:
        values = [
            e.get("indicators", {}).get(key, {}).get("value")
            for e in entries
            if isinstance(e.get("indicators"), dict)
        ]
        if values and all(v is None for v in values):
            rep.warn("全自治体で値が欠損している指標", key)


# ---------------------------------------------------------------- 出力


def print_issues(rep: Report, level: str, limit: int) -> None:
    grouped: dict[str, list[str]] = defaultdict(list)
    for issue in rep.issues:
        if issue.level == level:
            grouped[issue.code].append(issue.detail)
    heading(f"{level} {rep.count(level)} 件")
    if not grouped:
        print("  （なし）")
        return
    for code, details in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        print(f"[{level}] {code}（{len(details)}件）")
        if described := [d for d in details if d]:
            print_list(described, limit=limit, indent="    - ")


def load_document(path: Path) -> dict | None:
    """出力JSONを読む。読めない理由はログに出して None を返す。"""
    if not path.exists():
        logger.error("%s がありません。先に make score を実行してください。", path)
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error("JSON として読めません: %s (%s)", path, e)
        return None
    if not isinstance(doc, dict):
        logger.error("トップレベルがオブジェクトではありません: %s", path)
        return None
    return doc


def validate(doc: dict) -> Report:
    """検証をひと通り走らせて指摘を集める。"""
    rep = Report()
    if extra := sorted(set(doc) - {"meta", "municipalities"}):
        rep.warn("トップレベルに余分なキーがある", ", ".join(extra))
    check_meta(doc, rep)
    check_municipalities(doc, rep)
    return rep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="出力JSONのスキーマ・値域・欠損表現を検証する")
    parser.add_argument(
        "--file", type=str, help="検証するJSON（既定: processed/municipalities.json）"
    )
    parser.add_argument("--demo", action="store_true", help="ダミーデータの出力を検証する")
    parser.add_argument("--strict", action="store_true", help="警告も失敗として扱う")
    parser.add_argument("--limit", type=int, default=8, help="1項目あたりの表示件数（既定8）")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    path = Path(args.file) if args.file else (DEMO_JSON if args.demo else OUTPUT_JSON)
    doc = load_document(path)
    if doc is None:
        return 1

    rep = validate(doc)
    entries = doc.get("municipalities") or []
    meta = doc.get("meta", {}) if isinstance(doc.get("meta"), dict) else {}
    print(f"検証: {path}")
    print(
        f"  スキーマ {meta.get('version')} / 生成 {meta.get('generated_at')} / "
        f"{len(entries)}自治体 / {len(INDICATOR_BY_KEY)}指標 / {len(AXES)}軸"
        + ("  ※ダミーデータ" if meta.get("demo") else "")
    )

    print_issues(rep, ERROR, args.limit)
    print_issues(rep, WARN, args.limit)

    errors, warns = rep.count(ERROR), rep.count(WARN)
    failed = errors > 0 or (args.strict and warns > 0)
    print()
    print(f"判定: {'NG' if failed else 'OK'}（エラー {errors} 件 / 警告 {warns} 件）")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
