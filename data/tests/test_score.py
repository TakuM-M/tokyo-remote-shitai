"""スコア算出テスト。"""

import numpy as np
import pandas as pd

from defs.indicators import INDICATOR_BY_KEY
from pipeline import score


def test_minmax_scales_to_0_100():
    s = pd.Series([0.0, 5.0, 10.0])
    assert score.minmax(s).tolist() == [0.0, 50.0, 100.0]


def test_minmax_all_equal_returns_50():
    """全自治体が同値なら優劣がつかないので一律50。ゼロ除算にしない。"""
    assert score.minmax(pd.Series([7.0, 7.0, 7.0])).tolist() == [50.0, 50.0, 50.0]


def test_minmax_keeps_missing_as_nan():
    """欠損はそのまま欠損として残す"""
    out = score.minmax(pd.Series([1.0, np.nan, 3.0]))
    assert np.isnan(out.iloc[1])
    assert out.iloc[0] == 0.0 and out.iloc[2] == 100.0


def test_winsorize_clips_outliers():
    """極端値を切り落とす"""
    s = pd.Series(list(range(100)) + [10_000.0])
    out = score.winsorize(s)
    assert out.max() < 10_000.0


def test_lower_is_better_is_inverted():
    """地価は低いほど良い＝安い自治体が高スコアになる。"""
    ind = INDICATOR_BY_KEY["land_price_residential"]
    assert ind.direction == "lower_is_better"
    out = score.score_indicator(pd.Series([100_000.0, 500_000.0, 900_000.0]), ind)
    assert out.iloc[0] == 100.0
    assert out.iloc[2] == 0.0


def test_axis_score_is_null_when_all_indicators_missing():
    """欠損を0で埋めない。指標が全部無い軸は null のまま。"""
    scores = pd.DataFrame(
        {i.key: [np.nan, 50.0] for i in INDICATOR_BY_KEY.values()}, index=["13104", "13208"]
    )
    axes = score.axis_scores(scores)
    assert np.isnan(axes.loc["13104", "quiet"])
    assert axes.loc["13208", "quiet"] == 50.0


def test_apply_denominator_per_10k():
    """人口10万人あたりの件数に換算する"""
    ind = INDICATOR_BY_KEY["satellite_office_count"]
    base = pd.DataFrame({"population": [350_000.0], "area_km2": [18.2]}, index=["13104"])
    out = score.apply_denominator(pd.Series([35.0], index=["13104"]), ind, base)
    assert out.loc["13104"] == 1.0  # 35件 / 35万人 = 1.0件/万人


def test_demo_document_matches_schema():
    """demo_values() で作ったダミーデータをスコア計算してドキュメント化する。"""
    values, base = score.demo_values()
    computed = score.compute(values, base)
    doc = score.build_document(computed, score.axis_scores(computed["score"]), base, demo=True)

    assert len(doc["municipalities"]) == 53
    shinjuku = next(m for m in doc["municipalities"] if m["code"] == "13104")
    assert shinjuku["name"] == "新宿区"
    assert set(shinjuku["scores"]) == {
        "quiet",
        "refresh",
        "workspace",
        "commute",
        "cost",
        "community",
    }
    office = shinjuku["indicators"]["satellite_office_count"]
    assert office["status"] == "ok"
    assert office["source"] == "D8"
    assert "per_10k" in office  # 人口1万人あたりに換算されている

    # 欠損は 0 ではなく null + no_data
    missing = [
        ind
        for m in doc["municipalities"]
        for ind in m["indicators"].values()
        if ind["status"] == "no_data"
    ]
    assert missing, "ダミーデータは欠損表示の確認用に穴を含むはず"
    assert all(ind["value"] is None and ind["score"] is None for ind in missing)


def test_reference_indicator_excluded_from_axis():
    """昼夜間人口比率は参考指標なので軸スコアに算入しない。"""
    assert INDICATOR_BY_KEY["day_night_population_ratio"].include_in_axis is False
    scores = pd.DataFrame(
        {
            "npo_count": [80.0],
            "community_facility_count": [60.0],
            "day_night_population_ratio": [0.0],
        },
        index=["13104"],
    )
    assert score.axis_scores(scores).loc["13104", "community"] == 70.0
