"""[3] 空間結合（GeoPandas）: 点/線/面データを自治体ポリゴンに集約する

先に `build_boundaries()` で行政区域ポリゴン（D17）を interim/boundaries.geojson に
整えてから、各データを集約する。長さ・面積は緯度経度のままでは正しく測れないため、
平面直角座標系 第IX系（EPSG:6677）に変換してから計算する。

使い方:
    uv run python src/spatial_join.py --boundaries   # ポリゴンの整備のみ
    uv run python src/spatial_join.py                # 実装済みハンドラを実行
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from pathlib import Path

import pandas as pd

import municipalities as muni
from config import (
    BOUNDARY_GEOJSON,
    CRS_PLANE,
    CRS_WGS84,
    ensure_dirs,
    setup_logging,
)
from io_utils import parse_number
from normalize import IndicatorFrames, find_raw_file, write_indicators

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


def build_boundaries(source: Path | None = None) -> Path:
    """D17（国土数値情報 N03）から53自治体のポリゴンを作る。

    同一自治体が複数ポリゴンに分かれている（飛地・埋立地）ため code で dissolve する。
    """
    gpd = _gpd()
    src = source or find_raw_file("D17", "*.geojson")
    logger.info("行政区域ポリゴンを読み込み: %s", src)
    gdf = gpd.read_file(src)

    code_col = N03_CODE_COL if N03_CODE_COL in gdf.columns else None
    name_col = N03_NAME_COL if N03_NAME_COL in gdf.columns else None
    if code_col is None and name_col is None:
        raise KeyError(f"N03 の想定列が見つかりません: {list(gdf.columns)}")

    gdf["code"] = (
        gdf[code_col].map(muni.normalize_code)
        if code_col
        else gdf[name_col].map(muni.code_from_name)
    )
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
        raise FileNotFoundError(
            f"{BOUNDARY_GEOJSON} がありません。先に --boundaries を実行してください。"
        )
    gdf = gpd.read_file(BOUNDARY_GEOJSON)
    return gdf.to_crs(CRS_PLANE) if planar else gdf


# ---------------------------------------------------------------- 集約の基本操作


def points_to_code(points, boundaries=None):
    """点データに自治体コードを付ける（境界外の点は落とす）。"""
    gpd = _gpd()
    bnd = boundaries if boundaries is not None else load_boundaries()
    points = points.to_crs(bnd.crs)
    joined = gpd.sjoin(points, bnd.loc[:, ["code", "geometry"]], how="left", predicate="within")
    outside = joined["code"].isna().sum()
    if outside:
        logger.warning("自治体ポリゴン外の点が %d 件（都外・座標不正）", int(outside))
    return joined.dropna(subset=["code"])


def count_points(points, boundaries=None) -> pd.DataFrame:
    """点の件数を自治体ごとに集計する。"""
    joined = points_to_code(points, boundaries)
    out = joined.groupby("code").size().rename("value").reset_index()
    muni.check_coverage(out["code"], "点の件数")
    return out


def mean_points(points, value_col: str, boundaries=None) -> pd.DataFrame:
    """点が持つ観測値を自治体ごとに平均する（大気測定局など）。"""
    joined = points_to_code(points, boundaries)
    joined["_v"] = joined[value_col].map(parse_number)
    out = joined.groupby("code")["_v"].mean().rename("value").reset_index().dropna()
    muni.check_coverage(out["code"], f"{value_col} 平均")
    return out


def line_length_km(lines, boundaries=None) -> pd.DataFrame:
    """線データを自治体境界で切って、自治体内の総延長(km)を出す。"""
    gpd = _gpd()
    bnd = (boundaries if boundaries is not None else load_boundaries()).to_crs(CRS_PLANE)
    lines = lines.to_crs(CRS_PLANE)
    clipped = gpd.overlay(
        lines.loc[:, ["geometry"]].assign(_i=range(len(lines))),
        bnd.loc[:, ["code", "geometry"]],
        how="intersection",
        keep_geom_type=True,
    )
    clipped["_km"] = clipped.geometry.length / 1000.0
    out = clipped.groupby("code")["_km"].sum().rename("value").reset_index()
    muni.check_coverage(out["code"], "線の総延長")
    return out


def area_ratio(polygons, boundaries=None) -> pd.DataFrame:
    """面データが自治体面積に占める割合(%)を出す（緑被率など）。"""
    gpd = _gpd()
    bnd = (boundaries if boundaries is not None else load_boundaries()).to_crs(CRS_PLANE)
    polygons = polygons.to_crs(CRS_PLANE)
    # 重なりの二重計上を避けるため、先に対象面をまとめて溶かす
    merged = gpd.GeoDataFrame(geometry=[polygons.union_all()], crs=CRS_PLANE)
    inter = gpd.overlay(
        bnd.loc[:, ["code", "geometry"]], merged, how="intersection", keep_geom_type=True
    )
    covered = inter.groupby("code").geometry.apply(lambda g: g.area.sum())
    total = bnd.set_index("code").geometry.area
    out = (covered / total * 100.0).rename("value").reset_index().dropna()
    muni.check_coverage(out["code"], "面積比")
    return out


def density_by_area(counts: pd.DataFrame, boundaries=None) -> pd.DataFrame:
    """件数を自治体面積(km2)で割る。分母をポリゴンから直接得たいときに使う。"""
    bnd = (boundaries if boundaries is not None else load_boundaries()).to_crs(CRS_PLANE)
    area_km2 = (bnd.set_index("code").geometry.area / 1_000_000.0).rename("area_km2")
    merged = counts.set_index("code").join(area_km2, how="left")
    merged["value"] = merged["value"] / merged["area_km2"]
    return merged.reset_index().loc[:, ["code", "value"]]


# ---------------------------------------------------------------- ハンドラ


@spatial_handler("D1")
def join_pm25() -> IndicatorFrames:
    """大気測定局（点）の年間平均値を自治体に落とす。

    局のない自治体は欠損のままにする（近傍局での補完を入れる場合は、
    補完した旨を指標側の status に残せるようにしてから行う）。
    """
    gpd = _gpd()
    src = find_raw_file("D1", "*.geojson")
    stations = gpd.read_file(src)
    value_col = next((c for c in stations.columns if "PM2" in str(c).upper()), None)
    if value_col is None:
        raise KeyError(f"PM2.5 の値列が見つかりません: {list(stations.columns)}")
    return {"pm25_annual_avg": mean_points(stations, value_col)}


@spatial_handler("D4")
def join_green() -> IndicatorFrames:
    """緑地ポリゴンの面積比から緑被率を出す。"""
    gpd = _gpd()
    green = gpd.read_file(find_raw_file("D4", "*.geojson"))
    return {"green_coverage_ratio": area_ratio(green)}


@spatial_handler("D18")
def join_arterial_roads() -> IndicatorFrames:
    """緊急輸送道路（線）の総延長を面積で割って幹線道路密度を出す。

    都のカタログに都道そのものの線データがないため、国道・都道の主要路線で
    構成される緊急輸送道路ネットワークを幹線道路の代理として使う。
    """
    gpd = _gpd()
    roads = gpd.read_file(find_raw_file("D18", "*.shp"))
    lengths = line_length_km(roads)
    return {"arterial_road_density": density_by_area(lengths)}


@spatial_handler("D10")
def join_transit() -> IndicatorFrames:
    """GTFS の stops.txt（駅・バス停）から駅アクセス密度を出す。"""
    gpd = _gpd()
    stops_txt = find_raw_file("D10", "stops.txt")
    stops = pd.read_csv(stops_txt)
    points = gpd.GeoDataFrame(
        stops,
        geometry=gpd.points_from_xy(stops["stop_lon"], stops["stop_lat"]),
        crs=CRS_WGS84,
    )
    return {"station_density": density_by_area(count_points(points))}


# ---------------------------------------------------------------- エントリポイント


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="点/線/面データを自治体ポリゴンに集約する")
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

    if not BOUNDARY_GEOJSON.exists():
        try:
            build_boundaries()
        except FileNotFoundError as e:
            logger.error("行政区域ポリゴンを用意できません: %s", e)
            return 1

    targets = args.only or list(SPATIAL_HANDLERS)
    ok, failed = 0, 0
    for dataset_id in targets:
        fn = SPATIAL_HANDLERS.get(dataset_id)
        if fn is None:
            logger.warning("[%s] 空間結合ハンドラ未実装のためスキップ", dataset_id)
            continue
        try:
            write_indicators(fn())
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
