"""5軸と指標の定義。

スコア算出のルールはすべてこのファイルに集約

軸あたりの出典データセットは原則1つに絞ってある。指標を増やすより、
1本ずつ欠損とスケールの妥当性を確かめられる状態を優先する。
例外はいきぬきで、1本では区部と多摩のどちらかが必ず潰れるため2本立てにしている。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Direction = Literal["higher_is_better", "lower_is_better"]
Denominator = Literal["area_km2", "population_10k", "population"] | None


@dataclass(frozen=True)
class Axis:
    key: str
    label: str
    description: str


AXES: tuple[Axis, ...] = (
    Axis("quiet", "しずけさ", "道路交通騒音の小ささ・大気のきれいさ"),
    Axis("refresh", "いきぬき", "緑の多さ"),
    Axis("workspace", "しごとば", "家以外で作業できる場所の多さ"),
    Axis("cost", "くらしのコスト", "住居費の負担の軽さ"),
    Axis("community", "つながり", "地域活動やNPOなど人とつながる機会"),
)

AXIS_KEYS: tuple[str, ...] = tuple(a.key for a in AXES)
AXIS_BY_KEY: dict[str, Axis] = {a.key: a for a in AXES}


@dataclass(frozen=True)
class Indicator:
    key: str
    label: str
    axis: str
    direction: Direction
    dataset_id: str
    unit: str | None = None
    denominator: Denominator = None
    # 参考指標（軸スコアには算入せず、詳細パネルで数値だけ見せる）
    include_in_axis: bool = True
    definition: str = ""

    @property
    def per_key(self) -> str | None:
        """出力JSONで正規化後の値を入れるキー名。"""
        if self.denominator == "population_10k":
            return "per_10k"
        if self.denominator == "population":
            return "per_capita"
        if self.denominator == "area_km2":
            return "per_km2"
        return None


INDICATORS: tuple[Indicator, ...] = (
    # 軸1: しずけさ
    Indicator(
        key="pm25_annual_avg",
        label="PM2.5",
        axis="quiet",
        direction="lower_is_better",
        dataset_id="D-quiet-01",
        unit="μg/m3",
        definition=(
            "大気測定局の1分値（2025年6月〜2026年5月）を局ごとに月平均し、"
            "各月を等重みで平均した年平均値を自治体内で平均。"
        ),
    ),
    Indicator(
        key="road_noise_leq",
        label="道路交通騒音",
        axis="quiet",
        direction="lower_is_better",
        dataset_id="D-quiet-02",
        unit="dB",
        definition="幹線道路沿いの測定地点の昼間等価騒音レベル(Leq)を自治体内で平均。",
    ),
    # 軸2: いきぬき
    #
    # 緑被率と公園面積比の2本立てにしている。緑被率は100mメッシュ由来で
    # 市街地の細かい緑を拾えず23区の値が0.1〜12%に潰れるため、区部の解像度は
    # 公園面積比が担う。両者の順位相関はほぼ0で、補い合う関係にある。
    #
    # 公園面積の分母は人口ではなく面積。÷人口だと奥多摩町110m2/人に対し
    # 豊島区0.75m2/人と147倍に開き、人口の少ない自治体が上端に張り付く。
    Indicator(
        key="park_area",
        label="公園面積比",
        axis="refresh",
        direction="higher_is_better",
        dataset_id="D-refresh-01",
        unit="m2",
        denominator="area_km2",
        definition=(
            "公園緑地のポリゴン面積 ÷ 総面積。海上公園は開園区域のみ、"
            "計画決定区域・予定地・霊園・葬儀所は含めない。"
        ),
    ),
    # 山林まで含めた緑の総量。D-refresh-01 が取りこぼす西多摩の森林が入る。
    # 分解能の限界（市街地の細かい緑を拾えない）は datasets.py の notes 側に書く。
    Indicator(
        key="green_coverage_ratio",
        label="緑被率",
        axis="refresh",
        direction="higher_is_better",
        dataset_id="D-refresh-02",
        unit="%",
        definition=(
            "土地利用細分メッシュ（100m）のうち田・その他の農用地・森林・荒地・"
            "ゴルフ場の面積 ÷ 海水域を除く全メッシュ面積。"
        ),
    ),
    # 軸3: しごとば
    Indicator(
        key="satellite_office_count",
        label="サテライトオフィス",
        axis="workspace",
        direction="higher_is_better",
        dataset_id="D-workspace-01",
        unit="件",
        denominator="population_10k",
        definition="TOKYOテレワークアプリ掲載施設数 ÷ 人口1万人。",
    ),
    # 軸4: くらしのコスト
    Indicator(
        key="land_price_residential",
        label="地価水準",
        axis="cost",
        direction="lower_is_better",
        dataset_id="D-cost-01",
        unit="円/m2",
        definition="地価公示（用途:住宅地）の自治体内平均㎡単価。",
    ),
    # 軸5: つながり
    Indicator(
        key="npo_count",
        label="NPO密度",
        axis="community",
        direction="higher_is_better",
        dataset_id="D-community-01",
        unit="件",
        denominator="population_10k",
        definition="認証NPO法人数 ÷ 人口1万人。",
    ),
)

INDICATOR_BY_KEY: dict[str, Indicator] = {i.key: i for i in INDICATORS}


def indicators_for_axis(axis_key: str, scored_only: bool = False) -> list[Indicator]:
    return [
        i for i in INDICATORS if i.axis == axis_key and (i.include_in_axis if scored_only else True)
    ]


# プリセット。フロントのワンタップ切替に使うため meta に埋め込む。
# 重みの列順は AXES の定義順（しずけさ / いきぬき / しごとば / コスト / つながり）。
# 「ハイブリッド（週2出社）」は出社軸を落とした時点で既定の重みとほぼ同じになったため外した。
_PRESET_TABLE: tuple[tuple, ...] = (
    ("full_remote", "フルリモート集中型", 2.0, 1.5, 1.5, 1.0, 0.5),
    ("nature", "移住検討・自然重視", 1.5, 2.0, 0.8, 1.5, 1.0),
    ("community", "コミュニティ重視", 1.0, 1.0, 1.5, 1.0, 2.0),
)

PRESETS: tuple[dict, ...] = tuple(
    {"key": key, "label": label, "weights": dict(zip(AXIS_KEYS, weights, strict=True))}
    for key, label, *weights in _PRESET_TABLE
)

# 重みの初期値は全軸均等
DEFAULT_WEIGHTS: dict[str, float] = {k: 1.0 for k in AXIS_KEYS}
