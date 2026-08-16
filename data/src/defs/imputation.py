"""欠損を他の自治体の値で代替する規則の定義。

原則は「欠損を0で埋めない」で、値の無い自治体は `no_data` のまま残す。
ただし原データに調査地点が置かれていないだけで、周辺自治体と暮らしの実態が
ほとんど変わらないケースがある。そこだけを例外として、代替できる根拠を
1件ずつ書いた上でここに列挙する。

補った値は出力JSONで `status: "imputed"` として区別し、どの自治体の値から
埋めたかも `imputed_from` に残す。0埋めと違って「推定値だと分かる推定値」に
なることが条件。

補完の実行は pipeline/04-impute が行い、この定義には手続きを持たせない。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

from core import municipalities as muni
from defs.indicators import INDICATOR_BY_KEY

# 当面は参照自治体の平均のみ。中央値・近傍加重などを足す余地を型として残しておく。
Method = Literal["mean"]


@dataclass(frozen=True)
class Imputation:
    indicator: str  # 対象の指標キー（defs.indicators の Indicator.key）
    targets: tuple[str, ...]  # 補完する自治体コード
    reference: tuple[str, ...]  # 参照する自治体コード
    method: Method
    reason: str  # なぜこの参照先で代替できるのか。ログと査読のための根拠


IMPUTATIONS: tuple[Imputation, ...] = (
    Imputation(
        indicator="land_price_residential",
        targets=("13307", "13308"),
        reference=("13205", "13305"),
        method="mean",
        reason=(
            "檜原村・奥多摩町は地価公示に調査地点が無い。隣接する西多摩の山間部で"
            "住宅地の性格が近い青梅市・日の出町の平均で代替する。"
        ),
    ),
)

# 指標キーから引く。1指標に複数の規則（対象自治体の組が違う）を足せる形にしておく。
IMPUTATION_BY_INDICATOR: dict[str, tuple[Imputation, ...]] = {
    key: tuple(r for r in IMPUTATIONS if r.indicator == key)
    for key in dict.fromkeys(r.indicator for r in IMPUTATIONS)
}


def validate() -> None:
    """定義の綴り間違いを実行時に気づけるようにする。

    指標キーも自治体コードも文字列で持つため、typo があっても静かに
    「その規則が効かないだけ」で通ってしまう。読み込み時に落とす。
    """
    seen: set[tuple[str, str]] = set()
    for rule in IMPUTATIONS:
        if rule.indicator not in INDICATOR_BY_KEY:
            raise ValueError(f"indicators.py に無い指標キー: {rule.indicator}")
        if not rule.targets or not rule.reference:
            raise ValueError(f"[{rule.indicator}] targets と reference は空にできません")
        if rule.method not in get_args(Method):
            raise ValueError(f"[{rule.indicator}] 未対応の補完方法: {rule.method}")
        for code in (*rule.targets, *rule.reference):
            if code not in muni.BY_CODE:
                raise ValueError(f"[{rule.indicator}] 対象外の自治体コード: {code}")
        # 自分自身を参照すると、埋めたい欠損がそのまま参照先の欠損になる
        overlap = set(rule.targets) & set(rule.reference)
        if overlap:
            raise ValueError(f"[{rule.indicator}] 補完先を参照先にできません: {sorted(overlap)}")
        # 同じセルを2つの規則が埋めると、どちらが効いたか結果から追えなくなる
        for code in rule.targets:
            if (rule.indicator, code) in seen:
                raise ValueError(f"[{rule.indicator}] {code} の補完規則が重複しています")
            seen.add((rule.indicator, code))


validate()
