"""面/点/線データを自治体ポリゴンに集約して interim/indicators/ に出す。

自治体名を持たない（あるいは持っていても信用できない）GISデータを、
行政区域ポリゴンと重ね合わせて自治体単位の値に落とす。
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Iterator
from pathlib import Path

import pandas as pd

from core import municipalities as muni
from core.config import (
    BOUNDARY_GEOJSON,
    CRS_PLANE,
    CRS_WGS84,
    ensure_dirs,
    setup_logging,
)
from pipeline.common import IndicatorFrames, extracted_dir, write_indicators

logger = logging.getLogger(__name__)

# 国土数値情報 N03 の列名
N03_CODE_COL = "N03_007"  # 行政区域コード（5桁）
N03_NAME_COL = "N03_004"  # 市区町村名

SpatialHandler = Callable[[], IndicatorFrames]
SPATIAL_HANDLERS: dict[str, SpatialHandler] = {}


def spatial_handler(dataset_id: str) -> Callable[[SpatialHandler], SpatialHandler]:
    def deco(fn: SpatialHandler) -> SpatialHandler:
        SPATIAL_HANDLERS[dataset_id] = fn
        return fn

    return deco


def _gpd():
    """geopandas は重いので使うときだけ読み込む。"""
    import geopandas as gpd

    return gpd


# ---------------------------------------------------------------- 行政区域ポリゴン


def build_boundaries() -> Path:
    """D-common-02（国土数値情報 N03）から53自治体のポリゴンを作る。

    同一自治体が複数ポリゴンに分かれている（飛地・埋立地）ため code で dissolve する。
    """
    gpd = _gpd()
    src = next(iter(sorted(extracted_dir("D-common-02", "boundary").glob("*.geojson"))), None)
    if src is None:
        raise FileNotFoundError("D-common-02 の展開先に geojson がありません")
    logger.info("行政区域ポリゴンを読み込み: %s", src)
    gdf = gpd.read_file(src)

    if N03_CODE_COL in gdf.columns:
        gdf["code"] = gdf[N03_CODE_COL].map(muni.normalize_code)
    elif N03_NAME_COL in gdf.columns:
        gdf["code"] = gdf[N03_NAME_COL].map(muni.code_from_name)
    else:
        raise KeyError(f"N03 の想定列が見つかりません: {list(gdf.columns)}")

    before = len(gdf)
    gdf = gdf.dropna(subset=["code"])
    logger.info("対象53自治体で絞込み: %d → %d ポリゴン", before, len(gdf))

    dissolved = gdf.dissolve(by="code").reset_index().loc[:, ["code", "geometry"]]
    dissolved["name"] = dissolved["code"].map(lambda c: muni.BY_CODE[c].name)
    dissolved = dissolved.to_crs(CRS_WGS84)

    muni.check_coverage(dissolved["code"], "boundaries")
    BOUNDARY_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    dissolved.to_file(BOUNDARY_GEOJSON, driver="GeoJSON")
    logger.info("書き出し: %s (%d自治体)", BOUNDARY_GEOJSON, len(dissolved))
    return BOUNDARY_GEOJSON


def load_boundaries(planar: bool = False):
    """整備済みの自治体ポリゴンを読む。`planar=True` で面積・長さ計算用の投影に変換。"""
    gpd = _gpd()
    if not BOUNDARY_GEOJSON.exists():
        build_boundaries()
    gdf = gpd.read_file(BOUNDARY_GEOJSON)
    return gdf.to_crs(CRS_PLANE) if planar else gdf


# ---------------------------------------------------------------- 集約の基本操作


def clip_area(polygons, boundaries=None) -> pd.Series:
    """面データを自治体境界で切り、自治体ごとの面積(m2)を返す。

    自治体ポリゴンとの交差を取ることで、次がまとめて片づく:
      - 都県境をまたぐポリゴンの都内分だけを数える
      - 水域（N03 に海面は入っていない）を落とす
      - 属性の自治体名に頼らずに帰属を決める
    """
    gpd = _gpd()
    bnd = boundaries if boundaries is not None else load_boundaries(planar=True)
    inter = gpd.overlay(
        bnd.loc[:, ["code", "geometry"]],
        polygons.loc[:, ["geometry"]],
        how="intersection",
        keep_geom_type=True,
    )
    return inter.groupby("code").geometry.apply(lambda g: g.area.sum())


def dissolved_area(polygons, boundaries=None) -> pd.DataFrame:
    """重なりを解消したうえで自治体ごとの面積(m2)を出す。

    レイヤ間で同じ場所が二重に登録されていることがある（恩賜上野動物園は
    都立公園と植物園・動物園・水族園の両方に入っている）ため、先に溶かす。
    """
    gpd = _gpd()
    merged = gpd.GeoDataFrame(geometry=[polygons.geometry.union_all()], crs=polygons.crs)
    out = clip_area(merged, boundaries).rename("value").reset_index()
    muni.check_coverage(out["code"], "面積集計")
    return out


def area_ratio(areas: pd.DataFrame, boundaries=None) -> pd.DataFrame:
    """自治体面積に占める割合(%)に直す。分母もポリゴンから取る。"""
    bnd = boundaries if boundaries is not None else load_boundaries(planar=True)
    total = bnd.set_index("code").geometry.area
    merged = areas.set_index("code")["value"] / total * 100.0
    return merged.rename("value").reset_index().dropna()


def read_layer(path: Path, crs: str = CRS_PLANE):
    """シェープファイルをポリゴンだけに絞って読む。"""
    gpd = _gpd()
    gdf = gpd.read_file(path).to_crs(crs)
    gdf = gdf[gdf.geom_type.isin(("Polygon", "MultiPolygon"))].loc[:, ["geometry"]]
    # 自己交差を含むポリゴンがあると union に失敗するため先に直す
    gdf["geometry"] = gdf.geometry.make_valid()
    return gdf


def iter_layer_chunks(path: Path, step: int = 500) -> Iterator[object]:
    """巨大なシェープファイルを分割して読む（樹林地.shp は 1.5GB ある）。"""
    gpd = _gpd()
    from pyogrio import read_info

    total = read_info(path)["features"]
    for offset in range(0, total, step):
        gdf = gpd.read_file(path, rows=slice(offset, offset + step)).to_crs(CRS_PLANE)
        gdf = gdf[gdf.geom_type.isin(("Polygon", "MultiPolygon"))].loc[:, ["geometry"]]
        gdf["geometry"] = gdf.geometry.make_valid()
        logger.debug("%s: %d/%d", path.stem, min(offset + step, total), total)
        yield gdf


# ---------------------------------------------------------------- いきぬき

# 緑のオープンデータ（D-refresh-01）から公園面積に含めないレイヤ。
# ファイル名に含まれる語で外す。
PARK_EXCLUDED = (
    "_pt",  # 庭園_pt は点データで面積を持たない（同名のポリゴンが別にある）
    "計画決定",  # 海上公園(計画決定区域) は未整備の計画区域
    "予定",  # 海上公園予定地を含む緑地及び公共空地。開園区域と重複する
    "霊園",  # 霊園・葬儀所は気分転換に行く場所ではない
)


def _park_layers() -> list[Path]:
    root = extracted_dir("D-refresh-01", "parks")
    return [p for p in sorted(root.rglob("*.shp")) if not any(x in p.name for x in PARK_EXCLUDED)]


@spatial_handler("D-refresh-01")
def join_green() -> IndicatorFrames:
    """公園緑地の面積と、市街地の樹林地が自治体面積に占める割合を出す。

    公園はレイヤが用途別に多数のSHPに分かれ、レイヤ間で重なりがあるので
    全部まとめて溶かしてから自治体ポリゴンで切る。
    樹林地は 1.5GB あって一度に読めないため、分割して読みながら足していく。
    """
    gpd = _gpd()
    boundaries = load_boundaries(planar=True)

    frames = []
    for path in _park_layers():
        gdf = read_layer(path)
        logger.info("[parks] %s: %dポリゴン", path.stem, len(gdf))
        frames.append(gdf)
    parks = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=CRS_PLANE)
    park_area = dissolved_area(parks, boundaries)
    logger.info("公園面積 合計 %.2f km2", park_area["value"].sum() / 1e6)

    # 崖線の樹林地・自治体管理の樹林地は樹林地と重複しうるので使わない
    woods_path = extracted_dir("D-refresh-01", "woods") / "03_樹林地" / "樹林地.shp"
    totals: dict[str, float] = {}
    for chunk in iter_layer_chunks(woods_path):
        for code, area in clip_area(chunk, boundaries).items():
            totals[code] = totals.get(code, 0.0) + float(area)
    woods = pd.Series(totals, name="value").rename_axis("code").reset_index()
    muni.check_coverage(woods["code"], "樹林地")
    logger.info("樹林地面積 合計 %.2f km2", woods["value"].sum() / 1e6)

    return {
        "park_area": park_area,
        "urban_woods_ratio": area_ratio(woods, boundaries),
    }


# ---------------------------------------------------------------- エントリポイント


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="面/点/線データを自治体ポリゴンに集約する")
    parser.add_argument("--only", nargs="+", metavar="ID", help="対象データセットID")
    parser.add_argument(
        "--boundaries", action="store_true", help="行政区域ポリゴンの整備だけ行って終了"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    ensure_dirs()

    if args.boundaries:
        build_boundaries()
        return 0

    targets = args.only or list(SPATIAL_HANDLERS)
    ok, failed = 0, 0
    for dataset_id in targets:
        fn = SPATIAL_HANDLERS.get(dataset_id)
        if fn is None:
            logger.warning("[%s] 空間結合ハンドラ未実装のためスキップ", dataset_id)
            continue
        summary = fn.__doc__.splitlines()[0] if fn.__doc__ else ""
        logger.info("[%s] 空間結合: %s", dataset_id, summary)
        try:
            write_indicators(dataset_id, fn())
            ok += 1
        except (FileNotFoundError, KeyError) as e:
            logger.warning("[%s] スキップ: %s", dataset_id, e)
            failed += 1
        except Exception:
            logger.exception("[%s] 空間結合に失敗", dataset_id)
            failed += 1

    logger.info("完了: 成功 %d / スキップ・失敗 %d", ok, failed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
