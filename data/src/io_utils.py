"""文字コード・数値パース・ファイル入出力の共通処理。

都のオープンデータは Shift_JIS(CP932) と UTF-8 が混在し、数値も「1,234」「△5」「-」
のような表記で入ってくる。ここで吸収して以降の層をきれいに保つ。
"""

from __future__ import annotations

import codecs
import hashlib
import json
import logging
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# 試す順序。cp932 を utf-8 より先に置くと UTF-8 が化けるため、この順を守る。
ENCODINGS = ("utf-8-sig", "utf-8", "cp932", "euc_jp")

# 判定に使う先頭バイト数。全部読むと数百MBのファイルで無駄が大きい。
SNIFF_BYTES = 1 << 20

# 欠損を表す記号。0 と区別する（0で埋めない方針）。
NA_TOKENS = {"", "-", "‐", "—", "–", "…", "・・・", "n.a.", "N.A.", "NA", "不明", "非該当", "×"}


def detect_encoding(path: Path) -> str:
    """先頭を試し読みして文字コードを判定する。

    切り出した末尾がマルチバイト文字の途中に当たると、素の `bytes.decode()` では
    正しい文字コードでも失敗する。持ち越し可能なインクリメンタルデコーダで判定し、
    末尾の欠けは無視する（`final=False`）。
    """
    with path.open("rb") as f:
        head = f.read(SNIFF_BYTES)
    for enc in ENCODINGS:
        try:
            codecs.getincrementaldecoder(enc)().decode(head)
        except UnicodeDecodeError:
            continue
        return enc
    raise UnicodeDecodeError("unknown", b"", 0, 1, f"文字コードを判定できません: {path}")


def read_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    """文字コードを自動判定して CSV を読む。

    自治体コードを数値として読まれると先頭0や桁落ちが起きるため、既定で dtype=str。
    """
    enc = detect_encoding(path)
    logger.debug("read_csv %s (encoding=%s)", path.name, enc)
    kwargs.setdefault("dtype", str)
    kwargs.setdefault("keep_default_na", False)
    return pd.read_csv(path, encoding=enc, **kwargs)


def read_excel(path: Path, **kwargs: Any) -> pd.DataFrame:
    kwargs.setdefault("dtype", str)
    return pd.read_excel(path, **kwargs)


def parse_number(raw: object) -> float:
    """表記ゆれのある数値を float にする。欠損は NaN（0にはしない）。

    >>> parse_number("1,234.5")
    1234.5
    >>> parse_number("△12")   # 統計表のマイナス表記
    -12.0
    >>> parse_number("-")
    nan
    """
    if raw is None:
        return float("nan")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    s = unicodedata.normalize("NFKC", str(raw)).strip()
    if s in NA_TOKENS:
        return float("nan")
    s = s.replace(",", "").replace(" ", "")
    s = re.sub(r"^[△▲]", "-", s)
    # 「1234人」「56.7μg/m3」のような単位付きから数値部分を取る
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return float("nan")
    return float(m.group())


def parse_numeric_column(series: pd.Series) -> pd.Series:
    return series.map(parse_number).astype(float)


def ha_to_km2(value: float) -> float:
    return value / 100.0


def m2_to_km2(value: float) -> float:
    return value / 1_000_000.0


def m_to_km(value: float) -> float:
    return value / 1000.0


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "item"):  # numpy スカラー
        return obj.item()
    raise TypeError(f"JSON化できない型: {type(obj)}")


def write_json(path: Path, data: Any, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        data,
        ensure_ascii=False,
        indent=None if compact else 2,
        separators=(",", ":") if compact else None,
        default=_json_default,
    )
    path.write_text(text + ("" if compact else "\n"), encoding="utf-8")
    logger.info("書き出し: %s (%.1f KB)", path, path.stat().st_size / 1024)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_interim_csv(df: pd.DataFrame, path: Path) -> None:
    """中間データは UTF-8(BOMなし) の CSV に統一する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")
    logger.info("書き出し: %s (%d行)", path, len(df))
