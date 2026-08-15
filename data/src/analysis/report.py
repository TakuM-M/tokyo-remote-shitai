"""調査結果の可視化

missing_report / indicator_stats / validate_output が集めた内容を1枚のHTMLにまとめ、
analysis/ に書き出す。ブラウザで開いて眺めるためのもので、成果物には関与しない。

外部ライブラリは使わず、図はHTML/CSSとインラインSVGで描く
（依存を増やさない。日本語ラベルがフォント設定に左右されないようにする）。
"""

from __future__ import annotations

import argparse
import html
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from analysis import indicator_stats, missing_report, validate_output
from analysis._report import format_number
from analysis.indicator_stats import Stats
from analysis.validate_output import ERROR, WARN, Report
from core import municipalities as muni
from core.config import ANALYSIS_DIR, DEMO_JSON, OUTPUT_JSON, setup_logging
from defs.indicators import AXES, AXIS_BY_KEY, INDICATORS

logger = logging.getLogger(__name__)

TOTAL = len(muni.CODES)

# 軸ごとの色。フロントの配色とは独立した、レポート内だけの色分け。
AXIS_COLOR: dict[str, str] = {
    "quiet": "#5b83b0",
    "refresh": "#5f9e72",
    "workspace": "#b08a4e",
    "commute": "#7f74b3",
    "cost": "#b06b7e",
    "community": "#4f9c9c",
}

# 箱ひげ図1本の描画領域
BOX_W, BOX_H, BOX_PAD = 460, 22, 7

CSS = """
:root { --ink:#22282e; --muted:#6b747d; --line:#dfe3e7; --bg:#fbfbfc; }
* { box-sizing:border-box; }
body { margin:0; padding:32px 28px 64px; background:var(--bg); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif;
  font-size:14px; line-height:1.7; }
h1 { font-size:22px; margin:0 0 4px; }
h2 { font-size:16px; margin:44px 0 12px; padding-bottom:6px; border-bottom:2px solid var(--ink); }
p.note { color:var(--muted); font-size:12.5px; margin:6px 0 16px; }
.wrap { max-width:1080px; margin:0 auto; }
.cards { display:flex; flex-wrap:wrap; gap:12px; margin:20px 0 8px; }
.card { flex:1 1 190px; background:#fff; border:1px solid var(--line); border-radius:8px;
  padding:12px 14px; }
.card .label { font-size:12px; color:var(--muted); }
.card .value { font-size:24px; font-weight:600; letter-spacing:-0.01em; }
.card .sub { font-size:12px; color:var(--muted); }
.ok { color:#2f7d4f; } .ng { color:#b3402f; }
table { border-collapse:collapse; font-size:12px; }
.scroll { overflow-x:auto; }
.grid td { width:17px; height:15px; border:1px solid #fff; }
.grid th.side { text-align:right; padding-right:8px; font-weight:400; white-space:nowrap;
  font-size:11.5px; }
.grid th.top { font-weight:400; font-size:11px; height:11em; vertical-align:bottom;
  padding-bottom:5px; }
.grid th.top span { writing-mode:vertical-rl; text-orientation:mixed; white-space:nowrap; }
.grid th.axis { font-size:11px; font-weight:600; color:#fff; padding:1px 4px; text-align:center; }
.grid tr.gap td { height:6px; border:0; }
.grid tr.gap th { border:0; font-size:11px; font-weight:600; color:var(--muted);
  text-align:right; padding:10px 8px 2px 0; white-space:nowrap; }
.grid td.miss { width:auto; border:0; padding-left:9px; text-align:right; font-size:11px;
  color:var(--muted); font-variant-numeric:tabular-nums; }
.nodata { background:repeating-linear-gradient(45deg,#eceef0,#eceef0 3px,#dcdfe3 3px,#dcdfe3 6px); }
.bars { width:100%; border-collapse:collapse; font-size:12.5px; }
.bars td { padding:3px 6px 3px 0; vertical-align:middle; white-space:nowrap; }
.bars td.track { width:100%; padding-right:10px; }
.track .rail { background:#eceef0; border-radius:3px; height:13px; display:flex;
  overflow:hidden; min-width:180px; }
.rail .seg { height:100%; }
.num { text-align:right; font-variant-numeric:tabular-nums; color:var(--muted); }
.key { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11.5px; }
.legend { font-size:12px; color:var(--muted); margin:10px 0 0; }
.legend i { display:inline-block; width:11px; height:11px; vertical-align:-1px;
  margin:0 4px 0 12px; border-radius:2px; }
.issues { list-style:none; padding:0; margin:0; }
.issues > li { background:#fff; border:1px solid var(--line); border-left-width:4px;
  border-radius:6px; padding:8px 12px; margin-bottom:8px; }
.issues > li.e { border-left-color:#b3402f; } .issues > li.w { border-left-color:#d19a2a; }
.issues .head { font-weight:600; }
.issues .detail { color:var(--muted); font-size:12px; font-family:ui-monospace,Menlo,monospace; }
.plain { border-collapse:collapse; font-size:12.5px; }
.plain th, .plain td { border-bottom:1px solid var(--line); padding:4px 12px 4px 0;
  text-align:left; white-space:nowrap; }
.plain td.n { text-align:right; font-variant-numeric:tabular-nums; }
footer { margin-top:48px; color:var(--muted); font-size:12px; }
"""


def e(text: object) -> str:
    return html.escape(str(text))


def bar(segments: list[tuple[float, str, str]]) -> str:
    """帯グラフ1本。(割合0〜1, 色, ツールチップ) を左から並べる。"""
    parts = "".join(
        f'<span class="seg" style="width:{ratio * 100:.2f}%;background:{color}" title="{e(tip)}">'
        f"</span>"
        for ratio, color, tip in segments
        if ratio > 0
    )
    return f'<div class="rail">{parts}</div>'


# ---------------------------------------------------------------- 各セクション


def section_summary(frame: pd.DataFrame, generated: set[str], rep: Report, path: Path) -> str:
    filled = int(frame.notna().sum().sum())
    cells = TOTAL * len(INDICATORS)
    files = len(generated & {i.key for i in INDICATORS})
    errors, warns = rep.count(ERROR), rep.count(WARN)
    axes_ok = sum(
        1
        for axis in AXES
        if frame[[i.key for i in INDICATORS if i.axis == axis.key and i.include_in_axis]]
        .notna()
        .any(axis=1)
        .all()
    )
    cards = [
        ("データの充足率", f"{filled / cells * 100:.1f}%", f"{filled} / {cells} セル", ""),
        ("生成済みの指標", f"{files} / {len(INDICATORS)}", "interim/indicators/", ""),
        (
            "全53自治体で揃った軸",
            f"{axes_ok} / {len(AXES)}",
            "軸スコアが全自治体で出る軸",
            "",
        ),
        (
            "出力JSONの検証",
            "OK" if errors == 0 else "NG",
            f"エラー {errors} / 警告 {warns}",
            "ok" if errors == 0 else "ng",
        ),
    ]
    body = "".join(
        f'<div class="card"><div class="label">{e(label)}</div>'
        f'<div class="value {cls}">{e(value)}</div>'
        f'<div class="sub">{e(sub)}</div></div>'
        for label, value, sub, cls in cards
    )
    return (
        f'<div class="cards">{body}</div>'
        f'<p class="note">検証対象: <span class="key">{e(path)}</span></p>'
    )


def section_missing_map(frame: pd.DataFrame) -> str:
    """自治体 × 指標 の欠損マップ。値があるセルを軸の色で塗る。"""
    groups = [(a, [i for i in INDICATORS if i.axis == a.key]) for a in AXES]

    axis_row = (
        "<tr><th></th>"
        + "".join(
            f'<th class="axis" colspan="{len(items)}" '
            f'style="background:{AXIS_COLOR[a.key]}">{e(a.label)}</th>'
            for a, items in groups
        )
        + "<th></th>"
    )
    head = (
        "<tr><th></th>"
        + "".join(
            f'<th class="top"><span>{e(i.label)}'
            f"{'' if i.include_in_axis else '（参考）'}</span></th>"
            for _, items in groups
            for i in items
        )
        + '<th class="top"><span>欠損数</span></th>'
    )

    # 区部を先に、多摩を後に並べる（マスタの定義順）。切り替わりで区分の見出しを挟む
    rows = []
    previous_region = None
    for m in muni.MUNICIPALITIES:
        if m.region != previous_region:
            rows.append(
                f'<tr class="gap"><th>{e(m.region)}</th>'
                f'<td colspan="{len(INDICATORS) + 1}"></td></tr>'
            )
        previous_region = m.region
        cells = []
        for axis, items in groups:
            for ind in items:
                value = frame.at[m.code, ind.key]
                tip = f"{m.name} / {ind.label}: "
                if pd.isna(value):
                    cells.append(f'<td class="nodata" title="{e(tip)}データなし"></td>')
                else:
                    tip += f"{format_number(float(value))}{ind.unit or ''}"
                    cells.append(
                        f'<td style="background:{AXIS_COLOR[axis.key]}" title="{e(tip)}"></td>'
                    )
        missing = int(frame.loc[m.code].isna().sum())
        rows.append(
            f'<tr><th class="side">{e(m.name)}</th>{"".join(cells)}'
            f'<td class="miss" title="欠損 {missing}指標">{missing or ""}</td></tr>'
        )

    return (
        '<div class="scroll"><table class="grid">'
        f"{axis_row}</tr>{head}</tr>{''.join(rows)}</table></div>"
        '<p class="legend">塗り = 値あり（軸の色）'
        '<i class="nodata"></i>データなし（0で埋めずに欠損のまま残している）</p>'
    )


def section_coverage(frame: pd.DataFrame, generated: set[str]) -> str:
    """指標ごとの充足率。区部と多摩の内訳が分かるように積み上げる。"""
    wards = [c for c in muni.CODES if muni.BY_CODE[c].region == "区部"]
    tama = [c for c in muni.CODES if muni.BY_CODE[c].region == "多摩"]

    rows = []
    for ind in INDICATORS:
        column = frame[ind.key]
        w = int(column[wards].notna().sum())
        t = int(column[tama].notna().sum())
        color = AXIS_COLOR[ind.axis]
        note = "" if ind.key in generated else "<span class='num'>（未生成）</span>"
        rows.append(
            f"<tr><td>{e(ind.label)}</td>"
            f'<td class="key">{e(ind.key)}</td>'
            f'<td class="track">'
            + bar(
                [
                    (w / TOTAL, color, f"区部 {w}/{len(wards)}"),
                    (t / TOTAL, color + "88", f"多摩 {t}/{len(tama)}"),
                ]
            )
            + f'</td><td class="num">{w + t}/{TOTAL}</td><td>{note}</td></tr>'
        )
    return (
        f'<table class="bars">{"".join(rows)}</table>'
        '<p class="legend">濃い部分が区部（23）、薄い部分が多摩（30）。'
        "多摩側だけが欠ける指標は、区市町村ごとの公開状況の差をそのまま映している。</p>"
    )


def section_axes(frame: pd.DataFrame) -> str:
    """軸ごとに、スコアを算出できた自治体の数。"""
    rows = []
    for axis in AXES:
        keys = [i.key for i in INDICATORS if i.axis == axis.key and i.include_in_axis]
        ok = int(frame[keys].notna().any(axis=1).sum())
        rows.append(
            f"<tr><td>{e(axis.label)}</td>"
            f'<td class="key">{e(axis.key)}</td>'
            f'<td class="track">'
            + bar([(ok / TOTAL, AXIS_COLOR[axis.key], f"{ok}/{TOTAL} 自治体")])
            + f'</td><td class="num">{ok}/{TOTAL}</td>'
            f'<td class="num">算入 {len(keys)}指標</td></tr>'
        )
    return f'<table class="bars">{"".join(rows)}</table>'


def box_plot(s: Stats) -> str:
    """1指標の分布。最小〜最大を横軸に、四分位とウィンザライズ範囲を重ねる。"""
    lo, hi = s.q(0.0), s.q(1.0)
    if s.n == 0:
        return f'<svg width="{BOX_W}" height="{BOX_H}"></svg>'
    span = hi - lo
    color = AXIS_COLOR[s.indicator.axis]

    def x(value: float) -> float:
        inner = BOX_W - 2 * BOX_PAD
        return BOX_PAD + (0.5 if span == 0 else (value - lo) / span) * inner

    wl, wu = s.bounds
    q1, q3 = s.q(0.25), s.q(0.75)
    mid = BOX_H / 2
    parts = [
        # ウィンザライズで残る範囲。この外側は上下限に丸められる
        f'<rect x="{x(wl):.1f}" y="1" width="{max(x(wu) - x(wl), 1):.1f}" '
        f'height="{BOX_H - 2}" fill="{color}" opacity="0.10"/>',
        f'<line x1="{x(lo):.1f}" y1="{mid}" x2="{x(hi):.1f}" y2="{mid}" '
        f'stroke="{color}" stroke-width="1"/>',
        f'<rect x="{x(q1):.1f}" y="{mid - 5}" width="{max(x(q3) - x(q1), 1):.1f}" '
        f'height="10" fill="{color}" opacity="0.45"/>',
        f'<line x1="{x(s.q(0.5)):.1f}" y1="{mid - 6}" x2="{x(s.q(0.5)):.1f}" '
        f'y2="{mid + 6}" stroke="{color}" stroke-width="2"/>',
    ]
    low, high = s.outliers()
    for code in low + high:
        value = float(s.values[code])
        parts.append(
            f'<circle cx="{x(value):.1f}" cy="{mid}" r="2.6" fill="#b3402f" opacity="0.75">'
            f"<title>{e(muni.BY_CODE[code].name)}: {e(format_number(value))}</title></circle>"
        )
    return f'<svg width="{BOX_W}" height="{BOX_H}">{"".join(parts)}</svg>'


def section_distribution(stats: list[Stats]) -> str:
    rows = []
    for s in stats:
        ind = s.indicator
        if s.n == 0:
            rows.append(
                f'<tr><td>{e(ind.label)}</td><td></td><td class="num" colspan="3">値なし</td></tr>'
            )
            continue
        low, high = s.clipped()
        rows.append(
            f"<tr><td>{e(ind.label)}</td>"
            f'<td class="num">{e(format_number(s.q(0.0)))}</td>'
            f"<td>{box_plot(s)}</td>"
            f'<td class="num">{e(format_number(s.q(1.0)))}</td>'
            f'<td class="num">n={s.n} / 丸め {len(low) + len(high)}件</td></tr>'
        )
    return (
        f'<table class="bars"><tbody>{"".join(rows)}</tbody></table>'
        '<p class="legend">横軸は指標ごとに最小〜最大へ引き伸ばしている'
        "（指標間で幅は比べられない）。塗りの帯はウィンザライズ後に残る範囲、箱は四分位、"
        "赤い点は四分位範囲の1.5倍を超える値。</p>"
    )


def section_scores(doc: dict | None) -> str:
    """出力JSONの軸スコアの散らばり。0〜100の共通スケールで並べる。"""
    if not doc:
        return '<p class="note">出力JSONが読めなかったため省略。</p>'
    entries = [m for m in doc.get("municipalities", []) if isinstance(m, dict)]
    rows = []
    for axis in AXES:
        values = [
            (m.get("scores", {}).get(axis.key), m.get("name", ""))
            for m in entries
            if isinstance(m.get("scores"), dict)
        ]
        points = [(v, name) for v, name in values if isinstance(v, (int, float))]
        color = AXIS_COLOR[axis.key]
        marks = "".join(
            f'<circle cx="{BOX_PAD + v / 100 * (BOX_W - 2 * BOX_PAD):.1f}" cy="{BOX_H / 2}" '
            f'r="3" fill="{color}" opacity="0.5">'
            f"<title>{e(name)}: {v}</title></circle>"
            for v, name in points
        )
        average = sum(v for v, _ in points) / len(points) if points else 0
        line = (
            f'<line x1="{BOX_PAD + average / 100 * (BOX_W - 2 * BOX_PAD):.1f}" y1="2" '
            f'x2="{BOX_PAD + average / 100 * (BOX_W - 2 * BOX_PAD):.1f}" y2="{BOX_H - 2}" '
            f'stroke="{color}" stroke-width="2"><title>平均 {average:.1f}</title></line>'
            if points
            else ""
        )
        rows.append(
            f"<tr><td>{e(axis.label)}</td><td class='num'>0</td>"
            f'<td><svg width="{BOX_W}" height="{BOX_H}">'
            f'<line x1="{BOX_PAD}" y1="{BOX_H / 2}" x2="{BOX_W - BOX_PAD}" y2="{BOX_H / 2}" '
            f'stroke="#dfe3e7" stroke-width="1"/>{marks}{line}</svg></td>'
            f"<td class='num'>100</td>"
            f'<td class="num">{len(points)}自治体</td></tr>'
        )
    return (
        f'<table class="bars">{"".join(rows)}</table>'
        '<p class="legend">点は1自治体。縦線は平均。点が片側に寄っている軸は、'
        "min-max のあとでも差がつきにくい（外れ値が1つあると他が潰れる）。</p>"
    )


def section_validation(rep: Report) -> str:
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for issue in rep.issues:
        grouped[(issue.level, issue.code)].append(issue.detail)
    if not grouped:
        return '<p class="note">指摘なし。</p>'

    items = []
    for (level, code), details in sorted(grouped.items(), key=lambda kv: (kv[0][0], -len(kv[1]))):
        shown = [d for d in details if d][:8]
        body = "".join(f'<div class="detail">{e(d)}</div>' for d in shown)
        rest = len(details) - len(shown)
        if rest > 0:
            body += f'<div class="detail">ほか {rest} 件</div>'
        items.append(
            f'<li class="{"e" if level == ERROR else "w"}">'
            f'<div class="head">{e(level)}: {e(code)}（{len(details)}件）</div>{body}</li>'
        )
    return f'<ul class="issues">{"".join(items)}</ul>'


def section_ungenerated(generated: set[str]) -> str:
    missing = [i for i in INDICATORS if i.key not in generated]
    if not missing:
        return '<p class="note">すべての指標が生成済み。</p>'
    rows = "".join(
        f'<tr><td>{e(i.label)}</td><td class="key">{e(i.key)}</td>'
        f"<td>{e(AXIS_BY_KEY[i.axis].label)}</td><td>{e(i.dataset_id)}</td>"
        f"<td>{e(i.definition)}</td></tr>"
        for i in missing
    )
    return (
        '<table class="plain"><tr><th>指標</th><th>キー</th><th>軸</th><th>出典</th>'
        f"<th>定義</th></tr>{rows}</table>"
    )


# ---------------------------------------------------------------- 組み立て


def render(
    frame: pd.DataFrame,
    generated: set[str],
    stats: list[Stats],
    doc: dict | None,
    rep: Report,
    json_path: Path,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RemoteLife Tokyo データ調査レポート</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<h1>データ調査レポート</h1>
<p class="note">生成 {e(generated_at)}　RemoteLife Tokyo のデータパイプラインの状態。
このページは調査用で、成果物には関与しない。</p>

{section_summary(frame, generated, rep, json_path)}

<h2>欠損マップ（{TOTAL}自治体 × {len(INDICATORS)}指標）</h2>
{section_missing_map(frame)}

<h2>指標ごとの充足率</h2>
{section_coverage(frame, generated)}

<h2>軸スコアを算出できた自治体</h2>
{section_axes(frame)}

<h2>未生成の指標</h2>
{section_ungenerated(generated)}

<h2>指標の分布とウィンザライズ</h2>
{section_distribution(stats)}

<h2>軸スコアの散らばり</h2>
{section_scores(doc)}

<h2>出力JSONの検証</h2>
{section_validation(rep)}

<footer>再生成: <span class="key">make report</span><br>
元データ: interim/indicators/ と {e(json_path.name)}</footer>
</div>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="調査結果をHTML1枚にまとめて analysis/ に出す")
    parser.add_argument("--out", type=str, help="出力先（既定: analysis/report.html）")
    parser.add_argument(
        "--file", type=str, help="検証するJSON（既定: processed/municipalities.json）"
    )
    parser.add_argument("--demo", action="store_true", help="ダミーデータの出力を対象にする")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    frame = missing_report.load_frame(args.verbose)
    generated = missing_report.generated_keys()
    stats = indicator_stats.collect(args.verbose)

    json_path = Path(args.file) if args.file else (DEMO_JSON if args.demo else OUTPUT_JSON)
    doc = validate_output.load_document(json_path)
    rep = validate_output.validate(doc) if doc else Report()
    if doc is None:
        logger.warning("出力JSONを読めなかったため、検証と軸スコアのセクションは空になります。")

    out = Path(args.out) if args.out else (ANALYSIS_DIR / "report.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(frame, generated, stats, doc, rep, json_path), encoding="utf-8")
    logger.info("書き出し: %s (%.1f KB)", out, out.stat().st_size / 1024)
    print(f"ブラウザで開く: open {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
