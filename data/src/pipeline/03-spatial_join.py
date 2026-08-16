"""面/点/線データを自治体ポリゴンに集約して interim/indicators/ に出す"""

from __future__ import annotations

import logging
from collections.abc import Callable
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
    """公園緑地の面積を自治体ごとに出す。

    レイヤが用途別に多数のSHPに分かれ、レイヤ間で重なりがあるので
    全部まとめて溶かしてから自治体ポリゴンで切る。
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

    return {"park_area": park_area}


# 土地利用細分メッシュ（D-refresh-02）の土地利用種コード。ログの内訳表示に使う。
LANDUSE_LABELS: dict[str, str] = {
    "0100": "田",
    "0200": "その他の農用地",
    "0500": "森林",
    "0600": "荒地",
    "0700": "建物用地",
    "0901": "道路",
    "0902": "鉄道",
    "1000": "その他の用地",
    "1100": "河川地及び湖沼",
    "1400": "海浜",
    "1500": "海水域",
    "1600": "ゴルフ場",
}

# 緑とみなす土地利用種。ゴルフ場(1600) は私有地で立ち入れず気分転換の場にならないので外す。
# 河川地及び湖沼(1100) は水面だが、川辺・湖畔は息抜きに行ける場所なので入れる。
GREEN_CODES: tuple[str, ...] = ("0100", "0200", "0500", "0600", "1100")

# 陸地面積の分母から外す土地利用種。海水域メッシュは自治体ポリゴンの外にあり
# 大半は sjoin で落ちるが、境界の丸めで拾ってしまう分をここで確実に外す。
SEA_CODE = "1500"

# メッシュSHPの属性名は CP932 のまま格納されている
MESH_ENCODING = "cp932"
MESH_LANDUSE_COL = "土地利用種"


def _mesh_files() -> list[Path]:
    paths = []
    for key in ("mesh_5339", "mesh_5338"):
        src = next(iter(sorted(extracted_dir("D-refresh-02", key).glob("*.shp"))), None)
        if src is None:
            raise FileNotFoundError(f"D-refresh-02/{key} の展開先に shp がありません")
        paths.append(src)
    return paths


def _read_mesh(path: Path, bbox: tuple[float, float, float, float]):
    """土地利用細分メッシュを1枚読み、[landuse, area, 重心] の GeoDataFrame にする。

    1枚46万ポリゴンあるので、読み込みの時点で東京都の外接矩形に絞る。
    属性名が CP932 なので encoding を明示するが、化けた場合に備えて
    列順（メッシュ, 土地利用種, 撮影年月日）でも土地利用種を拾えるようにする。
    """
    gpd = _gpd()
    gdf = gpd.read_file(path, encoding=MESH_ENCODING, bbox=bbox).to_crs(CRS_PLANE)
    col = MESH_LANDUSE_COL if MESH_LANDUSE_COL in gdf.columns else gdf.columns[1]
    # 土地利用種は "0100" のような4桁。数値型で読まれても "100" にならないよう桁を戻す
    landuse = gdf[col].astype(str).str.zfill(4)
    attrs = pd.DataFrame({"landuse": landuse.values, "area": gdf.geometry.area.values})
    return gpd.GeoDataFrame(attrs, geometry=gdf.geometry.centroid, crs=gdf.crs)


def mesh_area_by_landuse(boundaries) -> pd.DataFrame:
    """自治体×土地利用種のメッシュ面積(m2)の表を作る。

    100万ポリゴン規模に overlay をかけるのは現実的でないので、メッシュの重心を
    自治体ポリゴンに sjoin して帰属を決め、メッシュ自身の面積を足し上げる。
    1メッシュが100m角なのに対し自治体は10〜225km2あるため、境界をまたぐメッシュを
    片方に寄せる誤差は無視できる。海水域は自治体ポリゴンの外なので自然に落ちる。
    """
    gpd = _gpd()
    bbox = tuple(boundaries.to_crs(CRS_WGS84).total_bounds)
    frames = []
    for path in _mesh_files():
        mesh = _read_mesh(path, bbox)
        joined = gpd.sjoin(
            mesh, boundaries.loc[:, ["code", "geometry"]], how="inner", predicate="within"
        )
        logger.info("[mesh] %s: %dメッシュ → 都内 %d", path.stem, len(mesh), len(joined))
        frames.append(joined.loc[:, ["code", "landuse", "area"]])

    joined = pd.concat(frames, ignore_index=True)
    pivot = joined.pivot_table(index="code", columns="landuse", values="area", aggfunc="sum")
    return pivot.fillna(0.0)


def _log_landuse_breakdown(by_landuse: pd.DataFrame, denom: pd.Series) -> None:
    """土地利用種ごとの面積シェアを出す。緑にどこまで含めるかの再検討用。"""
    shares = by_landuse.div(denom, axis=0)
    frame = muni.to_frame().set_index("code")
    for label, index in (
        ("全53自治体", by_landuse.index),
        ("区部", frame.index[frame["region"] == "区部"]),
        ("多摩", frame.index[frame["region"] == "多摩"]),
    ):
        # 分母は join_land_use と同じ「海水域を除いた陸地面積」に揃える
        target = by_landuse.loc[by_landuse.index.intersection(index)].drop(
            columns=[SEA_CODE], errors="ignore"
        )
        total = target.to_numpy().sum()
        parts = [
            f"{LANDUSE_LABELS.get(c, c)} {target[c].sum() / total * 100:.1f}%"
            for c in target.columns
        ]
        logger.info("[緑の内訳] %s（面積シェア）: %s", label, " / ".join(parts))
    for code in GREEN_CODES:
        if code in shares.columns:
            top = shares[code].idxmax()
            logger.info(
                "[緑の内訳] %s: 全体 %.2f%% / 最大は%s %.1f%%",
                LANDUSE_LABELS[code],
                by_landuse[code].sum() / denom.sum() * 100,
                muni.BY_CODE[top].name,
                shares.loc[top, code] * 100,
            )


@spatial_handler("D-refresh-02")
def join_land_use() -> IndicatorFrames:
    """土地利用細分メッシュから緑・水辺率（山林と川辺を含む面積割合）を出す。

    分子・分母をどちらもメッシュ由来にすることで、境界メッシュの帰属誤差が相殺される。
    分母は自治体に落ちたメッシュの合計から海水域を除いた陸地面積。
    """
    boundaries = load_boundaries(planar=True)
    by_landuse = mesh_area_by_landuse(boundaries)
    muni.check_coverage(by_landuse.index, "緑・水辺率")

    denom = by_landuse.drop(columns=[SEA_CODE], errors="ignore").sum(axis=1)
    green = by_landuse.reindex(columns=list(GREEN_CODES), fill_value=0.0).sum(axis=1)
    logger.info(
        "メッシュ陸地面積 合計 %.1f km2 / 緑 %.1f km2", denom.sum() / 1e6, green.sum() / 1e6
    )
    _log_landuse_breakdown(by_landuse, denom)

    ratio = (green / denom * 100.0).rename("value").rename_axis("code").reset_index()

    # 分母を自治体境界ポリゴンの面積に替えた場合との差。CSVには出さず確認のみ。
    by_polygon = area_ratio(green.rename("value").rename_axis("code").reset_index(), boundaries)
    diff = (ratio.set_index("code")["value"] - by_polygon.set_index("code")["value"]).abs()
    logger.info(
        "分母をポリゴン面積にした場合との差: 平均 %.2fpt / 最大 %.2fpt (%s)",
        diff.mean(),
        diff.max(),
        muni.BY_CODE[diff.idxmax()].name,
    )
    return {"green_coverage_ratio": ratio}


# ---------------------------------------------------------------- エントリポイント


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    ensure_dirs()

    targets = list(SPATIAL_HANDLERS)
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
