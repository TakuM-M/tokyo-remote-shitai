"""自治体コード解決のテスト"""

import pandas as pd

from core import municipalities as muni


def test_master_has_53_municipalities():
    """23区 + 多摩26市3町1村 = 53自治体"""
    assert len(muni.MUNICIPALITIES) == 53
    assert len(set(muni.CODES)) == 53
    kinds = [m.kind for m in muni.MUNICIPALITIES]
    assert kinds.count("区") == 23
    assert kinds.count("市") == 26
    assert kinds.count("町") == 3
    assert kinds.count("村") == 1


def test_code_from_name_handles_variations():
    """自治体名の表記揺れを吸収してコードを返す"""
    assert muni.code_from_name("新宿区") == "13104"
    assert muni.code_from_name("東京都新宿区") == "13104"
    assert muni.code_from_name(" 新宿区 ") == "13104"
    assert muni.code_from_name("あきる野市") == "13228"
    assert muni.code_from_name("東京都新宿区西新宿2-8-1") == "13104"
    
    # 旧自治体名は合併先へ
    assert muni.code_from_name("田無市") == "13229"
    assert muni.code_from_name("桧原村") == "13307"  # 異体字
    
    # 対象外
    assert muni.code_from_name("横浜市") is None
    assert muni.code_from_name("大島町") is None  # 島しょ部は対象外
    assert muni.code_from_name("") is None


def test_normalize_code():
    """自治体コードを6桁文字列に正規化する"""
    assert muni.normalize_code("13104") == "13104"
    assert muni.normalize_code(13104) == "13104"
    assert muni.normalize_code("131041") == "13104"  # 検査数字付き6桁
    assert muni.normalize_code("14100") is None  # 都外
    assert muni.normalize_code(None) is None


def test_attach_code_drops_unmatched():
    """自治体名からコードを付与する。対象外は落とす"""
    df = pd.DataFrame({"所在地": ["東京都新宿区1-1", "神奈川県横浜市1-1", "東京都調布市2-2"]})
    out = muni.attach_code(df, name_col="所在地")
    assert list(out["code"]) == ["13104", "13208"]
