"""対象自治体（東京都 23区 + 多摩26市3町1村 = 53自治体）のマスタ。

識別子は5桁の全国地方公共団体コード（例: 新宿区 = 13104）。
オープンデータ側の表記ゆれ（「東京都新宿区」「新宿 区」など）を吸収して
コードに解決するのがこのモジュールの役割。

島しょ部（大島町ほか9町村）は仕様上の対象外。ただしデータ側には含まれるため、
`is_target()` で明示的に判定してから除外する。
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Municipality:
    code: str  # 全国地方公共団体コード（5桁）
    name: str
    kind: str  # 区 / 市 / 町 / 村
    region: str  # 区部 / 多摩


_WARDS = [
    ("13101", "千代田区"),
    ("13102", "中央区"),
    ("13103", "港区"),
    ("13104", "新宿区"),
    ("13105", "文京区"),
    ("13106", "台東区"),
    ("13107", "墨田区"),
    ("13108", "江東区"),
    ("13109", "品川区"),
    ("13110", "目黒区"),
    ("13111", "大田区"),
    ("13112", "世田谷区"),
    ("13113", "渋谷区"),
    ("13114", "中野区"),
    ("13115", "杉並区"),
    ("13116", "豊島区"),
    ("13117", "北区"),
    ("13118", "荒川区"),
    ("13119", "板橋区"),
    ("13120", "練馬区"),
    ("13121", "足立区"),
    ("13122", "葛飾区"),
    ("13123", "江戸川区"),
]

_CITIES = [
    ("13201", "八王子市"),
    ("13202", "立川市"),
    ("13203", "武蔵野市"),
    ("13204", "三鷹市"),
    ("13205", "青梅市"),
    ("13206", "府中市"),
    ("13207", "昭島市"),
    ("13208", "調布市"),
    ("13209", "町田市"),
    ("13210", "小金井市"),
    ("13211", "小平市"),
    ("13212", "日野市"),
    ("13213", "東村山市"),
    ("13214", "国分寺市"),
    ("13215", "国立市"),
    ("13218", "福生市"),
    ("13219", "狛江市"),
    ("13220", "東大和市"),
    ("13221", "清瀬市"),
    ("13222", "東久留米市"),
    ("13223", "武蔵村山市"),
    ("13224", "多摩市"),
    ("13225", "稲城市"),
    ("13227", "羽村市"),
    ("13228", "あきる野市"),
    ("13229", "西東京市"),
]

# 西多摩郡の3町1村
_TOWNS_VILLAGES = [
    ("13303", "瑞穂町", "町"),
    ("13305", "日の出町", "町"),
    ("13307", "檜原村", "村"),
    ("13308", "奥多摩町", "町"),
]

MUNICIPALITIES: tuple[Municipality, ...] = tuple(
    [Municipality(code, name, "区", "区部") for code, name in _WARDS]
    + [Municipality(code, name, "市", "多摩") for code, name in _CITIES]
    + [Municipality(code, name, kind, "多摩") for code, name, kind in _TOWNS_VILLAGES]
)

CODES: tuple[str, ...] = tuple(m.code for m in MUNICIPALITIES)
BY_CODE: dict[str, Municipality] = {m.code: m for m in MUNICIPALITIES}

# 表記ゆれ・旧自治体名からの別名。値は対象自治体のコード。
# 旧市名は合併先に寄せる（統計の年次によっては旧名で載っているため）。
ALIASES: dict[str, str] = {
    "田無市": "13229",  # → 西東京市（2001年合併）
    "保谷市": "13229",
    "秋川市": "13228",  # → あきる野市（1995年合併）
    "五日市町": "13228",
    "桧原村": "13307",  # 「檜」の異体字
    "西多摩郡瑞穂町": "13303",
    "西多摩郡日の出町": "13305",
    "西多摩郡檜原村": "13307",
    "西多摩郡奥多摩町": "13308",
}


def normalize_name(raw: object) -> str:
    """自治体名の表記ゆれを吸収する。

    - 全角英数・記号を半角化（NFKC）
    - 「東京都」接頭辞、空白、括弧書きを除去
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    s = unicodedata.normalize("NFKC", str(raw)).strip()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"^東京都", "", s)
    s = re.sub(r"[（(].*?[）)]", "", s)
    return s


def code_from_name(raw: object) -> str | None:
    """自治体名からコードを引く。解決できなければ None。"""
    name = normalize_name(raw)
    if not name:
        return None
    for m in MUNICIPALITIES:
        if m.name == name:
            return m.code
    if name in ALIASES:
        return ALIASES[name]
    # 「新宿区役所」「府中市立◯◯」のように接尾辞が付いているケース
    for m in MUNICIPALITIES:
        if name.startswith(m.name):
            return m.code
    return None


def normalize_code(raw: object) -> str | None:
    """コード列を5桁文字列に揃える。

    6桁（検査数字付き）や数値型で入ってくることがあるため、先頭5桁を採る。
    対象外（島しょ部・都外）は None を返す。
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = re.sub(r"\D", "", unicodedata.normalize("NFKC", str(raw)))
    if len(s) < 5:
        return None
    code = s[:5]
    return code if code in BY_CODE else None


def is_target(code: object) -> bool:
    return normalize_code(code) is not None


def attach_code(
    df: pd.DataFrame,
    name_col: str | None = None,
    code_col: str | None = None,
    out_col: str = "code",
    drop_unmatched: bool = True,
) -> pd.DataFrame:
    """自治体コード列を付与する。

    `code_col` があればそれを優先し、無ければ `name_col` から名前解決する。
    対象外・解決不能な行は既定で落とし、件数を警告ログに出す（黙って消さない）。
    """
    out = df.copy()
    if code_col is not None and code_col in out.columns:
        out[out_col] = out[code_col].map(normalize_code)
        # コードが対象外でも名前で拾える場合があるので補完する
        if name_col is not None and name_col in out.columns:
            missing = out[out_col].isna()
            out.loc[missing, out_col] = out.loc[missing, name_col].map(code_from_name)
    elif name_col is not None and name_col in out.columns:
        out[out_col] = out[name_col].map(code_from_name)
    else:
        raise ValueError("name_col か code_col のいずれかは実在する列名である必要があります")

    unmatched = out[out_col].isna()
    if unmatched.any():
        label_col = name_col or code_col
        samples = out.loc[unmatched, label_col].astype(str).unique()[:5] if label_col else []
        logger.warning(
            "自治体コードに解決できない行が %d 件（対象外の島しょ部・都外を含む）: %s",
            int(unmatched.sum()),
            ", ".join(samples),
        )
    return out.loc[~unmatched].reset_index(drop=True) if drop_unmatched else out


def to_frame() -> pd.DataFrame:
    """マスタを DataFrame で返す。"""
    return pd.DataFrame([vars(m) for m in MUNICIPALITIES])


def check_coverage(codes: object, label: str = "") -> set[str]:
    """53自治体のうち値が無いコードを返す（欠損の可視化用）。"""
    present = {c for c in (normalize_code(x) for x in codes) if c}
    missing = set(CODES) - present
    if missing:
        names = ", ".join(BY_CODE[c].name for c in sorted(missing))
        logger.info("%s: %d/53 自治体をカバー。欠損 → %s", label or "coverage", len(present), names)
    return missing
