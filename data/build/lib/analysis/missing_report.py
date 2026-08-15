"""指標 × 自治体の欠損マトリクス。

`interim/indicators/` に出ている指標CSVを指標定義と突き合わせ、53自治体 × 全指標の
セルを3つの状態に分けて HTML と CSV に書き出す。

  ok         … 値がある
  no_data    … 指標CSVはあるが、その自治体の行が無い（または値が欠損）
  not_built  … 指標CSVそのものが無い（出典は定義済み。加工が未実装・未実行）
  no_source  … 出典データセットが defs/datasets.py に定義されていない

「欠損を0で埋めない」方針のため、no_data はスコア計算から外れて地図上もハッチングになる。
どの軸がどれだけ欠けたまま出ようとしているのかを、加工を進める前に把握するためのもの。

not_built と no_source は分けて数える。前者は加工を書けば埋まるが、後者は取得先すら
決まっていないので、指標定義を直すかデータセットを足さないと永久に埋まらない。
"""

from __future__ import annotations

import argparse
import logging
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from analysis import html
from core import municipalities as muni
from core.config import ANALYSIS_DIR, BASE_CSV, INDICATOR_DIR, indicator_csv, setup_logging
from core.io_utils import parse_numeric_column, read_csv
from defs import datasets
from defs.indicators import AXES, Axis, Indicator, indicators_for_axis

logger = logging.getLogger(__name__)

OK = "ok"
NO_DATA = "no_data"
NOT_BUILT = "not_built"
NO_SOURCE = "no_source"

STATUS_LABEL = {
    OK: "値あり",
    NO_DATA: "データなし",
    NOT_BUILT: "指標CSV未生成",
    NO_SOURCE: "出典が未定義",
}
# 色だけに頼らせないための記号。値があるセルは無印にして、欠けている側だけに印を置く。
STATUS_MARK = {OK: "", NO_DATA: "×", NOT_BUILT: "–", NO_SOURCE: "?"}

DEFAULT_HTML = ANALYSIS_DIR / "missing_report.html"
DEFAULT_CSV = ANALYSIS_DIR / "missing_matrix.csv"


# ---------------------------------------------------------------- 集計


@dataclass
class IndicatorCoverage:
    """1指標のカバー状況。"""

    indicator: Indicator
    built: bool  # 指標CSVが存在するか
    values: pd.Series  # index=自治体コード（53件）、欠損は NaN
    source_defined: bool = True  # 出典データセットが defs/datasets.py にあるか

    @property
    def covered(self) -> int:
        return int(self.values.notna().sum())

    @property
    def missing_codes(self) -> list[str]:
        return [c for c in muni.CODES if pd.isna(self.values.get(c))]

    def status(self, code: str) -> str:
        if not self.built:
            return NOT_BUILT if self.source_defined else NO_SOURCE
        return OK if pd.notna(self.values.get(code)) else NO_DATA

    def value(self, code: str) -> float | None:
        v = self.values.get(code)
        return None if v is None or pd.isna(v) else float(v)


def load_coverage(ind: Indicator) -> IndicatorCoverage:
    """指標CSVを読み、53自治体ぶんに揃えた値の並びを作る。"""
    path = indicator_csv(ind.dataset_id, ind.key)
    empty = pd.Series([float("nan")] * len(muni.CODES), index=list(muni.CODES), dtype=float)
    # 出典は defs/datasets.py が正。ここに無いIDを指標が指していたら、加工を書いても
    # 取得先が無いので埋まらない。未生成とは別扱いにする。
    known = ind.dataset_id in datasets.DATASETS
    if not path.exists():
        return IndicatorCoverage(ind, built=False, values=empty, source_defined=known)

    df = read_csv(path)
    if not {"code", "value"} <= set(df.columns):
        logger.warning("%s: code,value 列が見つからないため未生成として扱う", path.name)
        return IndicatorCoverage(ind, built=False, values=empty, source_defined=known)

    codes = df["code"].map(muni.normalize_code)
    values = pd.Series(parse_numeric_column(df["value"]).to_numpy(), index=codes, dtype=float)
    values = values[values.index.notna()]
    # 同じ自治体が複数行あれば平均。集約は本来 spatial_join 側で済んでいるが、
    # 取りこぼしがあってもここで黙って1行目を採らないようにする。
    values = values.groupby(level=0).mean().reindex(list(muni.CODES))
    if len(values.dropna()) == 0:
        logger.warning("%s: 対象53自治体に一致する値が1件も無い", path.name)
    return IndicatorCoverage(ind, built=True, values=values, source_defined=known)


def ordered_columns() -> list[tuple[Axis, list[Indicator]]]:
    """列の並び。軸の定義順にまとめる（参考指標も含めて全部出す）。"""
    return [(axis, indicators_for_axis(axis.key)) for axis in AXES]


def build() -> tuple[list[tuple[Axis, list[Indicator]]], dict[str, IndicatorCoverage]]:
    columns = ordered_columns()
    coverages = {ind.key: load_coverage(ind) for _, inds in columns for ind in inds}
    return columns, coverages


def base_gaps() -> dict[str, list[str]]:
    """`municipal_base.csv` の面積・人口が欠けている自治体。

    「◯◯あたり」の指標はここが欠けると値を出せないため、指標CSVが揃っていても
    最終的な欠損になる。別枠で見ておく。
    """
    if not BASE_CSV.exists():
        logger.warning("%s が無い（make normalize が未実行）", BASE_CSV.name)
        return {"area_km2": list(muni.CODES), "population": list(muni.CODES)}
    df = read_csv(BASE_CSV)
    df["code"] = df["code"].map(muni.normalize_code)
    df = df[df["code"].notna()].set_index("code")
    gaps: dict[str, list[str]] = {}
    for col in ("area_km2", "population"):
        s = parse_numeric_column(df[col]).reindex(list(muni.CODES)) if col in df else None
        gaps[col] = list(muni.CODES) if s is None else [c for c in muni.CODES if pd.isna(s[c])]
    return gaps


def axis_rows(
    columns: list[tuple[Axis, list[Indicator]]], cov: dict[str, IndicatorCoverage]
) -> list[dict]:
    """軸ごとのカバー率。軸スコアに算入される指標だけを見る。"""
    rows = []
    for axis, inds in columns:
        scored = [i for i in inds if i.include_in_axis]
        cells = len(scored) * len(muni.CODES)
        ok = sum(cov[i.key].covered for i in scored)
        rows.append(
            {
                "axis": axis,
                "indicators": len(scored),
                "built": sum(1 for i in scored if cov[i.key].built),
                "ok": ok,
                "cells": cells,
                "ratio": ok / cells if cells else 0.0,
            }
        )
    return rows


# ---------------------------------------------------------------- 整形


def format_value(v: float | None, unit: str | None = None) -> str:
    if v is None or math.isnan(v):
        return "—"
    if abs(v) >= 1000:
        s = f"{v:,.0f}"
    elif abs(v) >= 10:
        s = f"{v:,.1f}"
    else:
        s = f"{v:.2f}"
    return f"{s} {unit}" if unit else s


def _names(codes: list[str]) -> str:
    return "、".join(muni.BY_CODE[c].name for c in codes)


# ---------------------------------------------------------------- HTML

MATRIX_CSS = """
.legend { display: flex; flex-wrap: wrap; gap: 18px; align-items: center;
          font-size: 12px; color: var(--ink-2); margin: 0 0 10px; }
.legend .swatch { display: inline-block; width: 15px; height: 15px; border-radius: 3px;
                  margin-right: 6px; vertical-align: -3px; text-align: center;
                  line-height: 15px; font-size: 10px; color: var(--ink-2); }
.swatch.ok { background: var(--cell-ok); }
.swatch.no_data { background: var(--cell-no-data); }
.swatch.not_built { background: var(--cell-not-built); }
.swatch.no_source { background: var(--cell-no-source); }

/* 行=指標・列=自治体。18行なら全体が1画面に収まるので、内側でスクロールさせない。
   狭い窓に備えて横だけ overflow を残す */
.matrix-wrap { overflow-x: auto; background: var(--surface);
               border: 1px solid var(--border); border-radius: 10px; padding: 10px 14px 12px; }
table.matrix { border-collapse: separate; border-spacing: 2px; margin: 0 auto; }
.matrix th, .matrix td { background: var(--surface); }

/* 列見出し（自治体）。日本語は縦書きにすると列幅どおりの太さに収まる。
   縦書きでは line-height が字の太さ方向に効くので、1 にしないと列が広がる */
.matrix th.muni { writing-mode: vertical-rl; text-orientation: mixed; width: 14px; height: 74px;
                  vertical-align: bottom; padding: 6px 0 2px; font-weight: 400; font-size: 12px;
                  line-height: 1; color: var(--ink-2); white-space: nowrap; }
/* 地域ごとに1つの箱に見せる。セル間の2pxの隙間がそのまま地域の切れ目になる */
.matrix thead tr.regions th.rg { height: 22px; font-size: 11px; font-weight: 600;
                                 color: var(--ink-2); text-align: center;
                                 background: color-mix(in oklab, var(--ink) 6%, var(--surface));
                                 border-radius: 6px 6px 0 0; }
/* 地域の変わり目に隙間を空け、上の地域ヘッダの箱と切れ目を合わせる */
.matrix .region-start { border-left: 6px solid transparent; background-clip: padding-box; }

/* 行見出し（軸 → 指標）。軸は rowspan でまとめる */
.matrix th.ax { font-size: 11px; font-weight: 600; color: var(--ink-2); text-align: center;
                padding: 0 8px; white-space: nowrap; border-radius: 6px 0 0 6px;
                background: color-mix(in oklab, var(--ink) 6%, var(--surface)); }
.matrix th.ind { text-align: left; font-weight: 400; font-size: 12px; white-space: nowrap;
                 padding: 0 10px 0 6px; }
.matrix th.ind.ref { color: var(--ink-muted); }
/* 軸の変わり目に隙間を空け、左の軸ラベルの箱と切れ目を合わせる */
.matrix tbody tr.axis-start > * { border-top: 5px solid transparent;
                                  background-clip: padding-box; }
.matrix td.cell { width: 14px; height: 19px; border-radius: 3px; text-align: center;
                  font-size: 10px; line-height: 19px; color: var(--ink-2); cursor: default; }
.matrix td.ok { background: var(--cell-ok); }
.matrix td.no_data { background: var(--cell-no-data); }
.matrix td.not_built { background: var(--cell-not-built); }
.matrix td.no_source { background: var(--cell-no-source); }
tr.row-warn td, tr.row-warn th {
  background: color-mix(in oklab, var(--warning) 16%, var(--surface)); }
.matrix .sum { font-variant-numeric: tabular-nums; font-size: 11px; color: var(--ink-2);
               text-align: right; white-space: nowrap; padding-left: 10px; }
.matrix tfoot th { font-weight: 400; padding-top: 4px; }
.matrix tfoot th.foot-label { text-align: right; font-size: 11px; color: var(--ink-muted);
                              white-space: nowrap; padding-right: 8px; }
.matrix tfoot th.colsum { font-variant-numeric: tabular-nums; font-size: 10px;
                          color: var(--ink-2); text-align: center;
                          border-top: 1px solid var(--rule); background-clip: padding-box; }
.matrix tr.hl th.ind, .matrix .hl-col { outline: 2px solid var(--accent); outline-offset: -1px;
                                        border-radius: 3px; }

#tip { position: fixed; left: 0; top: 0; z-index: 20; pointer-events: none; opacity: 0;
       background: var(--surface); color: var(--ink); border: 1px solid var(--border);
       border-radius: 8px; padding: 8px 10px; font-size: 12px; max-width: 300px;
       box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16); transition: opacity 0.08s; }
#tip.on { opacity: 1; }
#tip .t { font-weight: 600; }
#tip .s { color: var(--ink-2); }
"""

MATRIX_JS = """
(function () {
  var wrap = document.getElementById('matrix-wrap');
  var tip = document.getElementById('tip');
  if (!wrap || !tip) return;
  var tT = tip.querySelector('.t'), tS = tip.querySelector('.s1'), tV = tip.querySelector('.s2');

  function clear() {
    wrap.querySelectorAll('.hl-col').forEach(function (el) { el.classList.remove('hl-col'); });
    wrap.querySelectorAll('tr.hl').forEach(function (el) { el.classList.remove('hl'); });
  }

  wrap.addEventListener('mouseover', function (e) {
    var cell = e.target.closest('td.cell');
    if (!cell) return;
    clear();
    cell.closest('tr').classList.add('hl');
    wrap.querySelectorAll('[data-col="' + cell.dataset.col + '"]').forEach(function (el) {
      el.classList.add('hl-col');
    });
    tT.textContent = cell.dataset.m + ' / ' + cell.dataset.i;
    tS.textContent = cell.dataset.s;
    tV.textContent = cell.dataset.v;
    tip.classList.add('on');
  });

  wrap.addEventListener('mousemove', function (e) {
    if (!tip.classList.contains('on')) return;
    var pad = 16, r = tip.getBoundingClientRect();
    var x = e.clientX + pad, y = e.clientY + pad;
    if (x + r.width > window.innerWidth - 8) x = e.clientX - r.width - pad;
    if (y + r.height > window.innerHeight - 8) y = e.clientY - r.height - pad;
    tip.style.transform = 'translate(' + x + 'px,' + y + 'px)';
  });

  wrap.addEventListener('mouseleave', function () { clear(); tip.classList.remove('on'); });
})();
"""


def render_summary(
    columns: list[tuple[Axis, list[Indicator]]],
    cov: dict[str, IndicatorCoverage],
    gaps: dict[str, list[str]],
) -> str:
    all_inds = [i for _, inds in columns for i in inds]
    built = [i for i in all_inds if cov[i.key].built]
    cells = len(built) * len(muni.CODES)
    ok = sum(cov[i.key].covered for i in built)
    full = [i for i in built if cov[i.key].covered == len(muni.CODES)]

    # 生成済み指標のうち、何個埋まっているかで自治体を並べる
    per_muni = {c: sum(1 for i in built if cov[i.key].status(c) == OK) for c in muni.CODES}
    worst_n = min(per_muni.values()) if per_muni else 0
    worst = [muni.BY_CODE[c].name for c, n in per_muni.items() if n == worst_n]

    base_note = "面積・人口はすべて揃っている"
    missing_base = sorted({c for v in gaps.values() for c in v})
    if missing_base:
        base_note = f"面積か人口が欠けている自治体 {len(missing_base)} 件（比率指標に影響）"

    orphans = [i for i in all_inds if not cov[i.key].source_defined]
    build_note = "残りは加工が未実装・未実行"
    if orphans:
        build_note = f"残りのうち {len(orphans)} 件は出典が未定義（取得先が無い）"

    return html.tiles(
        [
            html.tile(
                "指標CSVの生成状況",
                f"{len(built)}",
                f"/ {len(all_inds)}",
                build_note,
            ),
            html.tile(
                "生成済みセルの充足率",
                f"{ok / cells * 100:.0f}" if cells else "—",
                "%",
                f"{ok:,} / {cells:,} セル",
            ),
            html.tile(
                "53自治体そろった指標",
                f"{len(full)}",
                f"/ {len(built)}",
                "生成済みのうち欠損ゼロのもの",
            ),
            html.tile(
                "最も埋まっていない自治体",
                f"{worst_n}",
                f"/ {len(built)}",
                "、".join(worst[:3]) + ("ほか" if len(worst) > 3 else ""),
            ),
            html.tile("基礎データ", f"{len(muni.CODES) - len(missing_base)}", "/ 53", base_note),
        ]
    )


def render_axis_table(rows: list[dict]) -> str:
    body = []
    for r in rows:
        axis: Axis = r["axis"]
        body.append(
            "<tr>"
            f"<td>{html.esc(axis.label)}</td>"
            f'<td class="num">{r["built"]}/{r["indicators"]}</td>'
            f'<td style="width:40%">{html.bar(r["ratio"])}</td>'
            f'<td class="num">{r["ratio"] * 100:.0f}%</td>'
            f'<td class="num">{r["ok"]:,} / {r["cells"]:,}</td>'
            "</tr>"
        )
    return (
        '<div class="card scroll"><table class="data-table">'
        '<thead><tr><th>軸</th><th class="num">生成済み指標</th><th>値のあるセルの割合</th>'
        '<th class="num">割合</th><th class="num">セル</th></tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
        '<p class="note">参考指標（軸スコアに算入しないもの）は除いた集計。</p></div>'
    )


def render_matrix(
    columns: list[tuple[Axis, list[Indicator]]], cov: dict[str, IndicatorCoverage]
) -> str:
    flat = [ind for _, inds in columns for ind in inds]
    n = len(muni.CODES)
    col_index = {code: k for k, code in enumerate(muni.CODES)}
    built_count = sum(1 for i in flat if cov[i.key].built)

    # 地域（区部 / 多摩）ごとの連なり。2つ目以降の先頭列は左に隙間を入れて切れ目を見せる
    regions: list[tuple[str, list[str]]] = []
    for code in muni.CODES:
        r = muni.BY_CODE[code].region
        if not regions or regions[-1][0] != r:
            regions.append((r, []))
        regions[-1][1].append(code)
    starts = {codes[0] for _, codes in regions[1:]}

    def cls(code: str, *extra: str) -> str:
        return " ".join([*extra, *(["region-start"] if code in starts else [])])

    # ヘッダ2段（地域 → 自治体）
    regions_th = "".join(
        f'<th class="{cls(codes[0], "rg")}" colspan="{len(codes)}">{html.esc(name)}</th>'
        for name, codes in regions
    )
    munis_th = "".join(
        f'<th class="{cls(code, "muni")}" data-col="{col_index[code]}">'
        f"{html.esc(muni.BY_CODE[code].name)}</th>"
        for code in muni.CODES
    )

    rows: list[str] = []
    for a, (axis, inds) in enumerate(columns):
        for k, ind in enumerate(inds):
            c = cov[ind.key]
            cells = []
            for code in muni.CODES:
                st = c.status(code)
                cells.append(
                    f'<td class="{cls(code, "cell", st)}" data-col="{col_index[code]}"'
                    f' data-m="{html.esc(muni.BY_CODE[code].name)}"'
                    f' data-i="{html.esc(ind.label)}"'
                    f' data-s="{STATUS_LABEL[st]}"'
                    f' data-v="{html.esc(format_value(c.value(code), ind.unit))}">'
                    f"{STATUS_MARK[st]}</td>"
                )
            # 軸ラベルは軸の先頭行にだけ置き、その軸の指標数ぶん縦につなげる
            axis_th = (
                f'<th class="ax" rowspan="{len(inds)}">{html.esc(axis.label)}</th>' if not k else ""
            )
            rows.append(
                f'<tr class="{"axis-start" if a and not k else ""}">{axis_th}'
                f'<th class="ind{"" if ind.include_in_axis else " ref"}">'
                f"{html.esc(ind.label)}{'' if ind.include_in_axis else ' *'}</th>"
                f"{''.join(cells)}"
                f'<td class="sum">{f"{c.covered}/{n}" if c.built else "–"}</td></tr>'
            )

    foot = "".join(
        f'<th class="{cls(code, "colsum")}" data-col="{col_index[code]}">'
        f"{sum(1 for ind in flat if cov[ind.key].status(code) == OK)}</th>"
        for code in muni.CODES
    )

    return (
        '<div class="legend">'
        f'<span><span class="swatch ok"></span>{STATUS_LABEL[OK]}</span>'
        f'<span><span class="swatch no_data">{STATUS_MARK[NO_DATA]}</span>{STATUS_LABEL[NO_DATA]}'
        "（その自治体の行が無い）</span>"
        f'<span><span class="swatch not_built">{STATUS_MARK[NOT_BUILT]}</span>'
        f"{STATUS_LABEL[NOT_BUILT]}（加工が未実装・未実行）</span>"
        f'<span><span class="swatch no_source">{STATUS_MARK[NO_SOURCE]}</span>'
        f"{STATUS_LABEL[NO_SOURCE]}（datasets.py に出典が無い）</span>"
        "<span>* は参考指標（軸スコアに算入しない）</span>"
        "</div>"
        '<div class="matrix-wrap" id="matrix-wrap"><table class="matrix">'
        f'<thead><tr class="regions"><th></th><th></th>{regions_th}<th></th></tr>'
        f'<tr><th class="ax">軸</th><th class="ind">指標</th>{munis_th}'
        '<th class="sum">値あり</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody>"
        f'<tfoot><tr><th class="foot-label" colspan="2">値ありの指標数</th>{foot}'
        "<th></th></tr></tfoot>"
        "</table></div>"
        f'<p class="note">行の右端は値のある自治体数（分母は{n}）。列の下端はその自治体で値のある'
        f"指標数（分母は生成済みの {built_count} 指標）。セルにポインタを合わせると実際の値が"
        "出る。</p>"
        '<div id="tip"><div class="t"></div><div class="s s1"></div><div class="s s2"></div></div>'
    )


def render_indicator_table(
    columns: list[tuple[Axis, list[Indicator]]], cov: dict[str, IndicatorCoverage]
) -> str:
    rows = []
    for axis, inds in columns:
        for ind in inds:
            c = cov[ind.key]
            n = len(muni.CODES)
            if not c.built:
                st = c.status(muni.CODES[0])
                state = f'<span style="color:var(--ink-muted)">{STATUS_LABEL[st]}</span>'
                stats = '<td class="num">—</td><td class="num">—</td><td class="num">—</td>'
                bar_cell = '<td class="num">—</td>'
            else:
                state = f"{c.covered}/{n}"
                v = c.values.dropna()
                stats = (
                    f'<td class="num">{format_value(float(v.min()) if len(v) else None)}</td>'
                    f'<td class="num">{format_value(float(v.median()) if len(v) else None)}</td>'
                    f'<td class="num">{format_value(float(v.max()) if len(v) else None)}</td>'
                )
                bar_cell = f'<td style="min-width:130px">{html.bar(c.covered / n)}</td>'
            missing = c.missing_codes if c.built else []
            missing_html = (
                "—"
                if not missing
                else f"<details><summary>{len(missing)} 件</summary>{html.esc(_names(missing))}"
                "</details>"
            )
            rows.append(
                f'<tr class="{"" if c.source_defined else "row-warn"}">'
                f"<td>{html.esc(ind.label)}{'' if ind.include_in_axis else ' *'}</td>"
                f"<td>{html.esc(axis.label)}</td>"
                f"<td><code>{html.esc(ind.dataset_id)}</code></td>"
                f'<td class="num">{state}</td>{bar_cell}{stats}'
                f'<td class="wrap">{missing_html}</td>'
                "</tr>"
            )
    return (
        '<div class="card scroll"><table class="data-table">'
        '<thead><tr><th>指標</th><th>軸</th><th>出典</th><th class="num">カバー</th><th></th>'
        '<th class="num">最小</th><th class="num">中央</th><th class="num">最大</th>'
        "<th>欠損している自治体</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def orphan_files(columns: list[tuple[Axis, list[Indicator]]]) -> list[str]:
    """指標定義のどれにも対応しない、interim/indicators/ の置き去りファイル。"""
    expected = {indicator_csv(i.dataset_id, i.key).name for _, inds in columns for i in inds}
    if not INDICATOR_DIR.exists():
        return []
    return sorted(p.name for p in INDICATOR_DIR.glob("*.csv") if p.name not in expected)


def render_dataset_table(
    columns: list[tuple[Axis, list[Indicator]]], cov: dict[str, IndicatorCoverage]
) -> str:
    """出典データセットと指標の対応。defs/datasets.py と defs/indicators.py のずれを見る。"""
    used: dict[str, list[Indicator]] = {}
    for _, inds in columns:
        for ind in inds:
            used.setdefault(ind.dataset_id, []).append(ind)

    rows = []
    for dataset_id in sorted(set(datasets.DATASETS) | set(used)):
        ds = datasets.DATASETS.get(dataset_id)
        inds = used.get(dataset_id, [])
        if ds is None:
            name = "<strong>defs/datasets.py に定義が無い</strong>"
            fetch = "—"
        else:
            name = html.esc(ds.name)
            fetch = (
                "確定" if ds.is_resolved else ("確認中" if ds.status == "pending" else "URL未確定")
            )
        labels = (
            "、".join(html.esc(i.label) for i in inds)
            if inds
            else '<span style="color:var(--ink-muted)">指標の直接の出典ではない</span>'
        )
        built = sum(1 for i in inds if cov[i.key].built)
        rows.append(
            f'<tr class="{"" if ds else "row-warn"}">'
            f"<td><code>{html.esc(dataset_id)}</code></td>"
            f"<td>{name}</td>"
            f"<td>{fetch}</td>"
            f'<td class="wrap">{labels}</td>'
            f'<td class="num">{f"{built}/{len(inds)}" if inds else "—"}</td>'
            "</tr>"
        )

    orphans = orphan_files(columns)
    notes = [
        "出典は defs/datasets.py が正。指標がここに無いIDを指していると、加工を書いても"
        "取得先が無いので埋まらない。"
    ]
    if orphans:
        notes.append(
            "指標定義のどれにも対応しない置き去りファイル: " + html.esc("、".join(orphans))
        )
    return (
        '<div class="card scroll"><table class="data-table">'
        "<thead><tr><th>出典ID</th><th>データセット</th><th>取得先</th><th>使う指標</th>"
        '<th class="num">指標CSV</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
        + "".join(f'<p class="note">{t}</p>' for t in notes)
        + "</div>"
    )


def render_base_table(gaps: dict[str, list[str]]) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{html.esc(col)}</td>"
        f'<td class="num">{len(muni.CODES) - len(codes)}/{len(muni.CODES)}</td>'
        f'<td class="wrap">{html.esc(_names(codes)) if codes else "—"}</td>'
        "</tr>"
        for col, codes in gaps.items()
    )
    return (
        '<div class="card scroll"><table class="data-table">'
        '<thead><tr><th>列</th><th class="num">カバー</th><th>欠損している自治体</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
        '<p class="note">面積・人口は「◯◯あたり」の指標の分母。ここが欠けると、'
        "指標CSVに値があっても最終的な出力は欠損になる。</p></div>"
    )


def render(
    columns: list[tuple[Axis, list[Indicator]]],
    cov: dict[str, IndicatorCoverage],
    gaps: dict[str, list[str]],
) -> str:
    flat = [i for _, inds in columns for i in inds]
    body = "".join(
        [
            render_summary(columns, cov, gaps),
            "<h2>指標 × 自治体</h2>",
            render_matrix(columns, cov),
            "<h2>軸ごとの充足</h2>",
            render_axis_table(axis_rows(columns, cov)),
            "<h2>指標ごとの内訳</h2>",
            render_indicator_table(columns, cov),
            "<h2>出典データセットとの対応</h2>",
            render_dataset_table(columns, cov),
            "<h2>基礎データ（面積・人口）</h2>",
            render_base_table(gaps),
        ]
    )
    return html.page(
        "欠損レポート — 指標 × 自治体",
        f"対象 {len(muni.CODES)} 自治体（23区＋多摩26市3町1村）× {len(flat)} 指標。"
        "interim/indicators/ の中身をそのまま数えたもの。",
        body,
        command="make missing",
        extra_css=MATRIX_CSS,
        extra_js=MATRIX_JS,
    )


# ---------------------------------------------------------------- 出力


def write_matrix_csv(
    path: Path, columns: list[tuple[Axis, list[Indicator]]], cov: dict[str, IndicatorCoverage]
) -> Path:
    """状態を並べた行列をCSVでも残す（差分を追ったり grep したりする用）。"""
    flat = [i for _, inds in columns for i in inds]
    records = [
        {"code": code, "name": muni.BY_CODE[code].name}
        | {ind.key: cov[ind.key].status(code) for ind in flat}
        for code in muni.CODES
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_csv(path, index=False, encoding="utf-8")
    logger.info("書き出し: %s (%d行)", path, len(records))
    return path


def log_report(
    columns: list[tuple[Axis, list[Indicator]]],
    cov: dict[str, IndicatorCoverage],
    gaps: dict[str, list[str]],
) -> None:
    n = len(muni.CODES)
    flat = [i for _, inds in columns for i in inds]
    for axis, inds in columns:
        logger.info("[%s] %s", axis.key, axis.label)
        for ind in inds:
            c = cov[ind.key]
            if not c.source_defined:
                logger.warning(
                    "    %-28s 出典 %s が defs/datasets.py に無い", ind.key, ind.dataset_id
                )
                continue
            if not c.built:
                logger.info(
                    "    %-28s 未生成 (%s)", ind.key, indicator_csv(ind.dataset_id, ind.key).name
                )
                continue
            missing = c.missing_codes
            tail = f"  欠損{len(missing)}: {_names(missing)}" if missing else ""
            logger.info("    %-28s %2d/%d%s", ind.key, c.covered, n, tail)

    built = [i for i in flat if cov[i.key].built]
    cells = len(built) * n
    ok = sum(cov[i.key].covered for i in built)
    logger.info(
        "生成済み指標 %d/%d、値のあるセル %d/%d (%.1f%%)",
        len(built),
        len(flat),
        ok,
        cells,
        ok / cells * 100 if cells else 0.0,
    )
    for col, codes in gaps.items():
        if codes:
            logger.warning(
                "municipal_base.csv の %s が欠損 %d件: %s", col, len(codes), _names(codes)
            )

    orphans = orphan_files(columns)
    if orphans:
        logger.warning("指標定義に対応しない置き去りファイル: %s", "、".join(orphans))
    unused = sorted(set(datasets.DATASETS) - {i.dataset_id for i in flat})
    if unused:
        logger.info("指標の直接の出典ではないデータセット: %s", "、".join(unused))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="指標×自治体の欠損をHTMLとCSVに書き出す")
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_HTML, help=f"HTMLの出力先（既定: {DEFAULT_HTML}）"
    )
    parser.add_argument(
        "--csv", type=Path, default=DEFAULT_CSV, help=f"CSVの出力先（既定: {DEFAULT_CSV}）"
    )
    parser.add_argument("--no-csv", action="store_true", help="CSVを書き出さない")
    parser.add_argument("--open", action="store_true", help="書き出したHTMLをブラウザで開く")
    args = parser.parse_args(argv)

    setup_logging()
    columns, cov = build()
    gaps = base_gaps()
    log_report(columns, cov, gaps)

    out = html.write(args.out, render(columns, cov, gaps))
    if not args.no_csv:
        write_matrix_csv(args.csv, columns, cov)
    if args.open and sys.platform == "darwin":
        subprocess.run(["open", str(out)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
