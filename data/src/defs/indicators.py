"""6軸と指標の定義。

スコア算出のルールはすべてこのファイルに集約する。指標を足す・外す・向きを変える
といった調整は、原則ここの1エントリを直すだけで score.py まで通る。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Direction = Literal["higher_is_better", "lower_is_better"]
# 規模の差を除去するための分母。None は「すでに密度・比率・平均になっている値」。
Denominator = Literal["area_km2", "population_10k"] | None


@dataclass(frozen=True)
class Axis:
    key: str
    label: str
    description: str


AXES: tuple[Axis, ...] = (
    Axis("quiet", "しずけさ", "交通量・大気・幹線道路の少なさ"),
    Axis("refresh", "いきぬき", "緑・公園・散歩コースなど気分転換の場"),
    Axis("workspace", "しごとば", "家以外で作業できる場所の多さ"),
    Axis("commute", "しゅっしゃ", "主要拠点への出社のしやすさ"),
    Axis("cost", "くらしのコスト", "住居費の負担の軽さ・広さの余地"),
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
        dataset_id="D1",
        unit="μg/m3",
        definition="大気測定局の測定値（速報値）を自治体内で平均。",
    ),
    Indicator(
        key="arterial_road_density",
        label="幹線道路密度",
        axis="quiet",
        direction="lower_is_better",
        dataset_id="D18",
        unit="km/km2",
        definition="緊急輸送道路の総延長 ÷ 面積。",
    ),
    Indicator(
        key="traffic_volume",
        label="交通量",
        axis="quiet",
        direction="lower_is_better",
        dataset_id="D2",
        unit="台/日",
        definition="主要地点の平日24時間交通量の自治体内平均。",
    ),
    # 軸2: いきぬき
    Indicator(
        key="green_coverage_ratio",
        label="緑被率",
        axis="refresh",
        direction="higher_is_better",
        dataset_id="D4",
        unit="%",
        definition="緑地面積 ÷ 総面積。",
    ),
    Indicator(
        key="park_count",
        label="公園密度",
        axis="refresh",
        direction="higher_is_better",
        dataset_id="D7",
        unit="件",
        denominator="area_km2",
        definition="都立＋区市町村立公園の数 ÷ 面積。",
    ),
    Indicator(
        key="walking_course_count",
        label="散歩コース",
        axis="refresh",
        direction="higher_is_better",
        dataset_id="D5",
        unit="件",
        definition="TOKYO WALKING MAP の掲載コース数。",
    ),
    Indicator(
        key="bicycle_lane_ratio",
        label="自転車走行空間",
        axis="refresh",
        direction="higher_is_better",
        dataset_id="D6",
        unit="%",
        definition="自転車走行空間の整備延長 ÷ 道路総延長。都道分のみ。",
    ),
    # 軸3: しごとば
    Indicator(
        key="satellite_office_count",
        label="サテライトオフィス",
        axis="workspace",
        direction="higher_is_better",
        dataset_id="D8",
        unit="件",
        denominator="population_10k",
        definition="TOKYOテレワークアプリ掲載施設数 ÷ 人口1万人。",
    ),
    Indicator(
        key="library_count",
        label="図書館",
        axis="workspace",
        direction="higher_is_better",
        dataset_id="D7",
        unit="件",
        denominator="population_10k",
        definition="都立・区市町村立図書館数 ÷ 人口1万人。",
    ),
    Indicator(
        key="culture_facility_count",
        label="文化施設",
        axis="workspace",
        direction="higher_is_better",
        dataset_id="D9",
        unit="件",
        denominator="population_10k",
        definition="生涯学習センター・文化施設数 ÷ 人口1万人。",
    ),
    # 軸4: しゅっしゃ
    Indicator(
        key="commute_time_avg",
        label="主要拠点までの所要時間",
        axis="commute",
        direction="lower_is_better",
        dataset_id="D10",
        unit="分",
        definition="自治体代表駅から東京/新宿/渋谷/品川への最短所要時間の平均。",
    ),
    Indicator(
        key="transfer_count_avg",
        label="乗換回数",
        axis="commute",
        direction="lower_is_better",
        dataset_id="D10",
        unit="回",
        definition="同上の平均乗換回数。",
    ),
    Indicator(
        key="station_density",
        label="駅アクセス",
        axis="commute",
        direction="higher_is_better",
        dataset_id="D10",
        unit="件",
        denominator="area_km2",
        definition="都営の鉄道駅数とバス停数の合計 ÷ 面積。JR・私鉄・民間バスは含まない。",
    ),
    Indicator(
        key="transit_options",
        label="交通の選択肢",
        axis="commute",
        direction="higher_is_better",
        dataset_id="D10",
        unit="系統",
        definition="自治体内に停留所がある都営バスの系統数。コミュニティバスは含まない。",
    ),
    # 軸5: くらしのコスト
    Indicator(
        key="land_price_residential",
        label="地価水準",
        axis="cost",
        direction="lower_is_better",
        dataset_id="D11",
        unit="円/m2",
        definition="地価公示（用途:住宅地）の自治体内平均㎡単価。",
    ),
    Indicator(
        key="housing_area_per_building",
        label="住宅の広さ余地",
        axis="cost",
        direction="higher_is_better",
        dataset_id="D13",
        unit="m2/棟",
        definition="土地利用現況調査より、住宅系用途の1棟あたり面積。",
    ),
    # 軸6: つながり
    Indicator(
        key="npo_count",
        label="NPO密度",
        axis="community",
        direction="higher_is_better",
        dataset_id="D14",
        unit="件",
        denominator="population_10k",
        definition="認証NPO法人数 ÷ 人口1万人。",
    ),
    Indicator(
        key="community_facility_count",
        label="地域活動の場",
        axis="community",
        direction="higher_is_better",
        dataset_id="D7",
        unit="件",
        denominator="population_10k",
        definition="集会所・コミュニティ施設数 ÷ 人口1万人。",
    ),
    Indicator(
        key="day_night_population_ratio",
        label="昼夜間人口比率",
        axis="community",
        direction="lower_is_better",
        dataset_id="D15",
        unit="%",
        include_in_axis=False,  # 参考指標。軸スコアには入れない
        definition="昼間人口 ÷ 夜間人口。低いほど『昼も人がいる住宅地』の傾向。",
    ),
)

INDICATOR_BY_KEY: dict[str, Indicator] = {i.key: i for i in INDICATORS}


def indicators_for_axis(axis_key: str, scored_only: bool = False) -> list[Indicator]:
    return [
        i for i in INDICATORS if i.axis == axis_key and (i.include_in_axis if scored_only else True)
    ]


# プリセット。フロントのワンタップ切替に使うため meta に埋め込む。
# 重みの列順は AXES の定義順（しずけさ / いきぬき / しごとば / 出社 / コスト / つながり）。
_PRESET_TABLE: tuple[tuple, ...] = (
    ("full_remote", "フルリモート集中型", 2.0, 1.5, 1.5, 0.2, 1.0, 0.5),
    ("hybrid", "ハイブリッド（週2出社）", 1.0, 1.0, 1.0, 1.5, 1.0, 0.5),
    ("nature", "移住検討・自然重視", 1.5, 2.0, 0.8, 0.5, 1.5, 1.0),
    ("community", "コミュニティ重視", 1.0, 1.0, 1.5, 0.8, 1.0, 2.0),
)

PRESETS: tuple[dict, ...] = tuple(
    {"key": key, "label": label, "weights": dict(zip(AXIS_KEYS, weights, strict=True))}
    for key, label, *weights in _PRESET_TABLE
)

# 重みの初期値は全軸均等
DEFAULT_WEIGHTS: dict[str, float] = {k: 1.0 for k in AXIS_KEYS}
