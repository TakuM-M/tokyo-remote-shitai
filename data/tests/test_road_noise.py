"""自動車交通騒音調査結果（D-quiet-02）の集計テスト。"""

import importlib

import pandas as pd

# モジュール名が数字始まりで import 文に書けないため importlib で読む
normalize = importlib.import_module("pipeline.02-normalize")

# 実データの並び。列名は年度によって揺れる（ここでは平成25年度の表記）。
HEADER = (
    "一連番号,測定地点住所,緯度,経度,座標系,道路名,環境基準類型,測定開始年月日,"
    "測定終了年月日,道路種別,車線数,車道端からの距離,地上からの高さ,"
    "昼間等価騒音レベル(dB),夜間等価騒音レベル(dB)"
)


def write_csv(path, rows, header=HEADER):
    """CP932 の調査結果CSVを1本書く。"""
    path.write_text("\n".join([header, *rows]) + "\n", encoding="cp932")
    return path


def points(codes_years):
    """(コード, 年度, 昼間Leq) の並びを地点表にする。"""
    return pd.DataFrame(codes_years, columns=["code", "year", "leq_day"])


def test_read_year_resolves_municipality_and_value(tmp_path):
    """住所の先頭から自治体コードを引き、昼間Leqを取り出す"""
    path = write_csv(
        tmp_path / "h25_kekka.csv",
        [
            "1,新宿区西新宿2-8,35.6,139.6,JGD2011,都道,c,2013-07-08,2013-07-10,4,4,5.2,1.2,71,69",
            "2,調布市小島町2-35,35.6,139.5,JGD2011,都道,b,2013-07-08,2013-07-10,4,2,3.0,1.2,65,60",
        ],
    )
    out = normalize.read_noise_year(path, 2013)
    assert list(out["code"]) == ["13104", "13208"]
    assert list(out["leq_day"]) == [71.0, 65.0]
    assert set(out["year"]) == {2013}


def test_read_year_drops_missing_but_keeps_night_only_dash(tmp_path):
    """昼間が「欠測」「-」の地点は落とし、夜間だけが「-」の地点は残す"""
    path = write_csv(
        tmp_path / "h22_kekka.csv",
        [
            "1,稲城市矢野口228,35.6,139.5,JGD2011,都道,b,2010-06-01,2010-06-03,4,2,3.0,1.5,69,-",
            "2,新宿区西新宿2-8,35.6,139.6,JGD2011,都道,c,2010-06-01,2010-06-03,4,4,5.2,1.5,欠測,60",
            "3,調布市小島町2-35,35.6,139.5,JGD2011,都道,b,2010-06-01,2010-06-03,4,2,3.0,1.5,-,-",
        ],
    )
    out = normalize.read_noise_year(path, 2010)
    assert list(out["code"]) == ["13225"]
    assert list(out["leq_day"]) == [69.0]


def test_read_year_drops_rows_with_a_missing_column(tmp_path):
    """列が1つ足りない行は値が1列ずれるので採らない（平成25年度に2件ある）"""
    path = write_csv(
        tmp_path / "h25_kekka.csv",
        [
            # 「車線数」が抜けており、昼間の 67 が「地上からの高さ」に落ちる
            "478,府中市分梅町3-50,35.6,139.4,JGD2011,都道,b,2013-12-12,2013-12-13,4,3,1.5,67,64",
            "479,府中市宮西町1-1,35.6,139.4,JGD2011,都道,b,2013-12-12,2013-12-13,4,4,3.0,1.2,70,66",
        ],
    )
    out = normalize.read_noise_year(path, 2013)
    assert list(out["leq_day"]) == [70.0]


def test_read_year_handles_older_column_labels(tmp_path):
    """平成20年度の列名（「測定地点の住所」「…(Leq)(dB)」）でも読める"""
    header = HEADER.replace("測定地点住所", "測定地点の住所").replace(
        "昼間等価騒音レベル(dB)", "昼間等価騒音レベル(Leq)(dB)"
    )
    path = write_csv(
        tmp_path / "h20_kekka.csv",
        ["1,新宿区西新宿2-8,35.6,139.6,JGD2011,都道,c,2008-06-03,2008-06-10,4,5,8.8,1.5,72,69"],
        header=header,
    )
    out = normalize.read_noise_year(path, 2008)
    assert list(out["leq_day"]) == [72.0]


def test_aggregate_uses_newest_year_with_data():
    """複数年度に測定がある自治体は最も新しい年度だけを使う"""
    out = normalize.aggregate_noise(
        points([("13104", 2013, 70.0), ("13104", 2013, 72.0), ("13104", 2008, 50.0)])
    )
    assert out.loc[0, "value"] == 71.0
    assert out.loc[0, "year"] == 2013
    assert out.loc[0, "points"] == 2


def test_aggregate_falls_back_to_older_year():
    """最新年度に測定が無い自治体は、値のある最も新しい年度まで遡る"""
    out = normalize.aggregate_noise(
        points(
            [
                ("13104", 2013, 70.0),
                ("13307", 2010, 60.0),
                ("13307", 2008, 40.0),
            ]
        )
    ).set_index("code")
    assert out.loc["13104", "year"] == 2013
    # 檜原村は平成25年度に測定が無いので平成22年度（2010年度）まで遡る
    assert out.loc["13307", "year"] == 2010
    assert out.loc["13307", "value"] == 60.0


def test_aggregate_leaves_unmeasured_municipality_out():
    """どの年度にも測定が無い自治体は行ごと出さない（0では埋めない）"""
    out = normalize.aggregate_noise(points([("13104", 2013, 70.0)]))
    assert list(out["code"]) == ["13104"]
