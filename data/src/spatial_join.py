""" 空間結合（GeoPandas）: 点/線/面データを自治体ポリゴンに集約する

データによっては緯度経度しかない。幾何学的な点/線/面データを自治体ポリゴンに落とすことで、自治体ごとの集計値を得る。
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
from io_utils import parse_number, read_json
from normalize import IndicatorFrames, find_raw_file, find_raw_files, write_indicators

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


def _to_points(df: pd.DataFrame):
    """lat / lon 列を持つ表を点データにする。"""
    gpd = _gpd()
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs=CRS_WGS84)


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


# 緑のオープンデータ（D4）から緑被率に使わないレイヤ。ファイル名に含まれる語で外す。
GREEN_EXCLUDED = (
    "_pt",  # 庭園_pt は点データで面積を持たない（同名のポリゴンが別にある）
    "計画決定",  # 海上公園(計画決定区域) は未整備の計画区域
    "予定",  # 海上公園予定地
)


@spatial_handler("D4")
def join_green() -> IndicatorFrames:
    """公園・緑地と樹林地のポリゴンから緑被率（自治体面積に占める割合）を出す。

    レイヤが用途別に多数のSHPに分かれており、公園と樹林地は重なることがある。
    `area_ratio` 側で先に全ポリゴンを溶かしてから面積を測るので二重計上にはならない。
    未整備の計画区域と点データのレイヤは対象から外す。
    """
    gpd = _gpd()
    layers = [
        p for p in find_raw_files("D4", "*.shp") if not any(x in p.stem for x in GREEN_EXCLUDED)
    ]
    frames = []
    for path in layers:
        gdf = gpd.read_file(path).to_crs(CRS_PLANE)
        # 面を持たないレイヤが混ざっても落ちないようにポリゴンだけ残す
        gdf = gdf[gdf.geom_type.isin(("Polygon", "MultiPolygon"))]
        logger.info("[D4] %s: %dポリゴン", path.stem, len(gdf))
        frames.append(gdf.loc[:, ["geometry"]])
    green = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=CRS_PLANE)
    # 自己交差を含むポリゴンがあると union に失敗するため先に直す
    green["geometry"] = green.geometry.make_valid()
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


def _rail_stations() -> pd.DataFrame:
    """都営地下鉄・都電荒川線・日暮里舎人ライナーの駅。

    odpt:Station は路線ごとに1レコードなので、新宿・三田などの乗換駅が
    路線の数だけ重複する。駅名でまとめて1件に落とす。
    """
    records = read_json(find_raw_file("D10", "toei_stations.json"))
    df = pd.DataFrame(records).drop_duplicates(subset=["dc:title"])
    return pd.DataFrame(
        {
            "id": df["owl:sameAs"],
            "lat": df["geo:lat"].astype(float),
            "lon": df["geo:long"].astype(float),
        }
    )


def _bus_route_counts(gtfs_dir: Path, stops: pd.DataFrame, code_by_stop: pd.Series) -> pd.DataFrame:
    """自治体ごとの都営バス系統数。

    stop_times.txt が参照するのはポールの stop_id なので、
    ポール → 親停留所 → 自治体 とたどってから系統をユニークに数える。
    """
    trips = pd.read_csv(gtfs_dir / "trips.txt", usecols=["trip_id", "route_id"], dtype=str)
    times = pd.read_csv(gtfs_dir / "stop_times.txt", usecols=["trip_id", "stop_id"], dtype=str)
    served = times.merge(trips, on="trip_id").drop_duplicates(subset=["stop_id", "route_id"])
    served["code"] = (
        served["stop_id"].map(stops.set_index("stop_id")["parent_station"]).map(code_by_stop)
    )
    out = (
        served.dropna(subset=["code"])
        .groupby("code")["route_id"]
        .nunique()
        .rename("value")
        .reset_index()
    )
    muni.check_coverage(out["code"], "都営バス系統数")
    return out


@spatial_handler("D10")
def join_transit() -> IndicatorFrames:
    """都営バスの停留所と都営鉄道の駅から、駅アクセス密度と系統数を出す。

    収録されるのは都営分だけで、JR・私鉄・民間バス・コミュニティバスを含まない。
    都営バスが走らない多摩地域の大半は点が1件も落ちないが、0では埋めずに
    欠損のままにする（地図上は「データなし」として扱う）。
    """
    gtfs_dir = find_raw_file("D10", "stops.txt").parent
    stops = pd.read_csv(gtfs_dir / "stops.txt", dtype=str)
    # 親を持たない行が停留所そのもの。ポール（location_type=0）は同じ停留所に
    # 上下線ぶんぶら下がるため、そのまま数えると二重計上になる
    bus = stops[stops["parent_station"].isna()]
    bus_points = _to_points(
        pd.DataFrame(
            {
                "id": bus["stop_id"],
                "lat": bus["stop_lat"].astype(float),
                "lon": bus["stop_lon"].astype(float),
            }
        )
    )
    rail_points = _to_points(_rail_stations())

    boundaries = load_boundaries()
    bus_joined = points_to_code(bus_points, boundaries)
    counts = count_points(pd.concat([bus_points, rail_points], ignore_index=True), boundaries)
    code_by_stop = bus_joined.set_index("id")["code"]
    return {
        "station_density": density_by_area(counts, boundaries),
        "transit_options": _bus_route_counts(gtfs_dir, stops, code_by_stop),
    }


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
