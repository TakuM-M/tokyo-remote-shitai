"""調査レポートのHTML描画。

analysis/ 配下のスクリプトが共通で使う部品。外部のCSS・JS・フォントを一切参照せず、
生成した1ファイルをブラウザで開くだけで読めるページを組み立てる。

配色はライト/ダークの2組を用意し、OSの設定に追従する。状態を表す色（good/critical）は
両モードで同じ値を使い、地の色との混ぜ具合だけをモードごとに変える。
"""

from __future__ import annotations

import html as _html
import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_CSS = """
*, *::before, *::after { box-sizing: border-box; }

:root {
  color-scheme: light;
  --plane:      #f9f9f7;
  --surface:    #fcfcfb;
  --ink:        #0b0b0b;
  --ink-2:      #52514e;
  --ink-muted:  #898781;
  --grid:       #e1e0d9;
  --rule:       #c3c2b7;
  --border:     rgba(11, 11, 11, 0.10);
  --accent:     #2a78d6;
  --good:       #0ca30c;
  --warning:    #fab219;
  --critical:   #d03b3b;
  --wash:       rgba(11, 11, 11, 0.05);
  /* セルの塗り。地の色と混ぜて、面で置いても騒がしくならない濃さにする */
  --cell-ok:        color-mix(in oklab, var(--good) 20%, var(--surface));
  --cell-no-data:   color-mix(in oklab, var(--critical) 26%, var(--surface));
  --cell-not-built: color-mix(in oklab, var(--ink-muted) 17%, var(--surface));
  --cell-no-source: color-mix(in oklab, var(--warning) 40%, var(--surface));
}

@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --plane:      #0d0d0d;
    --surface:    #1a1a19;
    --ink:        #ffffff;
    --ink-2:      #c3c2b7;
    --ink-muted:  #898781;
    --grid:       #2c2c2a;
    --rule:       #383835;
    --border:     rgba(255, 255, 255, 0.10);
    --accent:     #3987e5;
    --wash:       rgba(255, 255, 255, 0.06);
    --cell-ok:        color-mix(in oklab, var(--good) 34%, var(--surface));
    --cell-no-data:   color-mix(in oklab, var(--critical) 40%, var(--surface));
    --cell-not-built: color-mix(in oklab, var(--ink-muted) 26%, var(--surface));
    --cell-no-source: color-mix(in oklab, var(--warning) 46%, var(--surface));
  }
}

body {
  margin: 0;
  padding: 32px 28px 64px;
  background: var(--plane);
  color: var(--ink);
  font-family: system-ui, -apple-system, "Hiragino Sans", "Noto Sans JP", sans-serif;
  font-size: 14px;
  line-height: 1.6;
}

.page { max-width: 1200px; margin: 0 auto; }

h1 { font-size: 24px; font-weight: 600; margin: 0 0 4px; letter-spacing: 0.01em; }
h2 { font-size: 15px; font-weight: 600; margin: 40px 0 12px; }
h2:first-of-type { margin-top: 28px; }
p  { margin: 0 0 8px; }
.sub  { color: var(--ink-2); margin: 0; }
.note { color: var(--ink-muted); font-size: 12px; margin: 8px 0 0; }

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
}

/* ---- 数値タイル ---- */
.tiles { display: flex; flex-wrap: wrap; gap: 12px; }
.tile {
  flex: 1 1 210px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
}
.tile .label { color: var(--ink-2); font-size: 12px; }
.tile .value { font-size: 28px; font-weight: 600; line-height: 1.2; margin-top: 2px; }
.tile .unit  { font-size: 14px; font-weight: 500; color: var(--ink-2); margin-left: 2px; }
.tile .note  { color: var(--ink-muted); font-size: 12px; margin-top: 2px; }

/* ---- 表 ---- */
table { border-collapse: collapse; font-size: 13px; }
.data-table { width: 100%; }
.data-table th, .data-table td {
  text-align: left;
  padding: 6px 10px;
  border-bottom: 1px solid var(--grid);
  white-space: nowrap;
}
.data-table thead th {
  color: var(--ink-2);
  font-weight: 500;
  font-size: 12px;
  border-bottom: 1px solid var(--rule);
}
.data-table td.num, .data-table th.num { text-align: right; font-variant-numeric: tabular-nums; }
.data-table tbody tr:hover { background: var(--wash); }
.data-table td.wrap { white-space: normal; color: var(--ink-2); }

/* ---- 横棒（1系列の量） ---- */
.bar-track {
  position: relative;
  height: 8px;
  min-width: 120px;
  background: var(--grid);
  border-radius: 4px;
  overflow: hidden;
}
.bar-fill { position: absolute; inset: 0 auto 0 0; background: var(--accent); border-radius: 4px; }

.scroll { overflow-x: auto; }

footer { color: var(--ink-muted); font-size: 12px; margin-top: 48px; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
"""


def esc(value: object) -> str:
    """HTMLエスケープ。None は空文字にする。"""
    return _html.escape("" if value is None else str(value))


def tile(label: str, value: str, unit: str = "", note: str = "") -> str:
    """数値ひとつを見せるタイル。棒1本のグラフを描くくらいならこちらを使う。"""
    unit_html = f'<span class="unit">{esc(unit)}</span>' if unit else ""
    note_html = f'<div class="note">{esc(note)}</div>' if note else ""
    return (
        '<div class="tile">'
        f'<div class="label">{esc(label)}</div>'
        f'<div class="value">{esc(value)}{unit_html}</div>'
        f"{note_html}"
        "</div>"
    )


def tiles(items: Iterable[str]) -> str:
    return f'<div class="tiles">{"".join(items)}</div>'


def bar(ratio: float) -> str:
    """0〜1 の割合を横棒で表す。"""
    pct = max(0.0, min(1.0, ratio)) * 100
    return f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%"></div></div>'


def page(
    title: str,
    subtitle: str,
    body: str,
    command: str = "",
    extra_css: str = "",
    extra_js: str = "",
) -> str:
    """1ファイル完結のページを組み立てる。`command` は作り直しに使うコマンド。"""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    made_by = f"{stamp} — <code>{esc(command)}</code>" if command else stamp
    script = f"<script>{extra_js}</script>" if extra_js else ""
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{BASE_CSS}{extra_css}</style>
</head>
<body>
<div class="page">
<h1>{esc(title)}</h1>
<p class="sub">{esc(subtitle)}</p>
{body}
<footer>生成: {made_by}</footer>
</div>
{script}
</body>
</html>
"""


def write(path: Path, html_text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")
    logger.info("書き出し: %s (%.1f KB)", path, path.stat().st_size / 1024)
    return path
