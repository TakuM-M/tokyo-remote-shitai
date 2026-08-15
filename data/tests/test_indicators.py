"""指標定義と出典データセット定義の同期テスト

出典は `defs/datasets.py` が正。`defs/indicators.py` がそこに無いIDを指していると、
加工を書いても取得先が無く永久に埋まらないので、定義の時点で落とす。
（実際に D-quiet-04 を datasets.py から外したとき、指標だけが残って気づけなかった）
"""

from defs import datasets, indicators


def test_every_indicator_has_a_defined_source():
    """指標の dataset_id はすべて datasets.py に実在する"""
    unknown = sorted(
        (i.key, i.dataset_id)
        for i in indicators.INDICATORS
        if i.dataset_id not in datasets.DATASETS
    )
    assert not unknown, f"datasets.py に無い出典を参照している指標: {unknown}"


def test_indicator_keys_are_unique():
    keys = [i.key for i in indicators.INDICATORS]
    assert len(keys) == len(set(keys))


def test_every_indicator_belongs_to_a_defined_axis():
    unknown = sorted(i.key for i in indicators.INDICATORS if i.axis not in indicators.AXIS_BY_KEY)
    assert not unknown, f"未定義の軸を指す指標: {unknown}"


def test_every_axis_has_scored_indicators():
    """どの軸も、スコアに算入される指標を最低1つ持つ（空の軸はスコアを出せない）"""
    for axis in indicators.AXES:
        assert indicators.indicators_for_axis(axis.key, scored_only=True), axis.key


def test_presets_cover_all_axes():
    for preset in indicators.PRESETS:
        assert set(preset["weights"]) == set(indicators.AXIS_KEYS), preset["key"]
