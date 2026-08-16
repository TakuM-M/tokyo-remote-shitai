"""5軸と指標の定義。

スコア算出のルールはすべてこのファイルに集約

軸あたりの出典データセットは原則1つに絞ってある。指標を増やすより、
1本ずつ欠損とスケールの妥当性を確かめられる状態を優先する。
例外はいきぬきで、1本では区部と多摩のどちらかが必ず潰れるため3本立てにしている。
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
    Axis("quiet", "しずけさ", "道路交通騒音の小ささ"),
    Axis("refresh", "いきぬき", "緑と水辺の多さ・大気のきれいさ"),
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
    # 小標本の縮小（0なら縮小しない）。分母の小さい自治体で「◯◯あたり」の値が
    # 跳ねるのを抑える。「全体の中央値どおりの密度で、分母をこの量だけ余計に
    # 観測した」という仮想データを足してからスコア化する。
    # 単位は分母と同じ（population_10k なら万人。5.0 = 人口5万人ぶん）。
    shrink_denominator: float = 0.0
    # 軸スコアを平均するときの重み。効くのは軸内での相対値だけ。
    # 欠損した指標は重みごと外し、残った指標の重みで正規化する。
    weight: float = 1.0
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
    # 緑・水辺率、公園面積比、PM2.5 の3本立て。外に出て過ごす場所の量（前2本）と、
    # そこで吸う空気の質（PM2.5）の両方を見る。
    #
    # 緑・水辺率は100mメッシュ由来で市街地の細かい緑を拾えず23区の値が
    # 0.9〜20%に収まるため、区部の解像度は公園面積比が担う。
    # 両者の順位相関はほぼ0で、補い合う関係にある。
    #
    # 重みは緑・水辺率0.5・PM2.5 0.3・公園面積比0.2。緑と水辺の総量そのものを
    # 測るのは緑・水辺率で、公園面積比は区部が潰れるのを補う補正の役回りだから。
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
        weight=0.2,
        definition=(
            "公園緑地のポリゴン面積 ÷ 総面積。海上公園は開園区域のみ、"
            "計画決定区域・予定地・霊園・葬儀所は含めない。"
        ),
    ),
    # 山林と川辺まで含めた息抜きの場の総量。D-refresh-01 が取りこぼす西多摩の森林と、
    # 区部を流れる大きな河川が入る。
    # 分解能の限界（市街地の細かい緑を拾えない）は datasets.py の notes 側に書く。
    Indicator(
        key="green_coverage_ratio",
        label="緑・水辺率",
        axis="refresh",
        direction="higher_is_better",
        dataset_id="D-refresh-02",
        unit="%",
        weight=0.5,
        definition=(
            "土地利用細分メッシュ（100m）のうち田・その他の農用地・森林・荒地・"
            "河川地及び湖沼の面積 ÷ 海水域を除く全メッシュ面積。"
        ),
    ),
    # 測定局のある43自治体でしか出ない。欠損した10自治体は残り2本の重みで正規化される。
    Indicator(
        key="pm25_annual_avg",
        label="PM2.5",
        axis="refresh",
        direction="lower_is_better",
        dataset_id="D-quiet-01",
        unit="μg/m3",
        weight=0.3,
        definition=(
            "大気測定局の1分値（2025年6月〜2026年5月）を局ごとに月平均し、"
            "各月を等重みで平均した年平均値を自治体内で平均。"
        ),
    ),
    # 軸3: しごとば
    #
    # 分母は人口ではなく面積。住民が体感する選択肢の数は自宅周辺の施設密度に比例するため。
    # 生件数だと自治体の広さが混ざり、八王子市と武蔵野市がどちらも12件で同点になる
    # （面積は186km2と11km2で17倍違う）。÷人口だと公園面積比と同じく人口の少ない
    # 自治体が上端に張り付き、1件しかない檜原村が全体2位に来る。
    Indicator(
        key="satellite_office_count",
        label="サテライトオフィス",
        axis="workspace",
        direction="higher_is_better",
        dataset_id="D-workspace-01",
        unit="件",
        denominator="area_km2",
        definition="TOKYOテレワークアプリ掲載施設数 ÷ 総面積(km2)。",
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
    #
    # 人口5万人ぶんの縮小をかける。檜原村は人口1,747人でNPO5件しかなく、
    # 1件増減するだけで密度が±5.7件/万人動く。この振れ幅は下位40自治体が
    # 収まっている範囲（1.9〜5.4件/万人）より広く、28.6件/万人という生の値は
    # ほとんど情報を持たないのに全体3位を決めてしまう。
    # 縮小をかけると実データの重みが人口に応じて決まり（檜原村3% / 世田谷区95%）、
    # 観測数の少ない自治体ほど全体の中央値に寄る。人口が小さくても件数が十分あれば
    # 上位に残る（千代田区は698件あるので1位のまま）。
    Indicator(
        key="npo_count",
        label="NPO密度",
        axis="community",
        direction="higher_is_better",
        dataset_id="D-community-01",
        unit="件",
        denominator="population_10k",
        shrink_denominator=5.0,
        definition="認証NPO法人数 ÷ 人口1万人。人口の少ない自治体は全体の中央値に寄せて補正。",
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
