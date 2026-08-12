"""使用オープンデータ（D1〜D19）の定義。

仕様書 6.1 の一覧に対応する。`download_url` は実ファイルのURLが確定したものだけ
埋めてあり、未確定のものは None（ingest ではスキップされ、`--list` に未確定と出る）。
ここに書いた出典情報がそのまま municipalities.json の meta.sources になるため、
画面から原典を辿れるかどうかはこのファイルの正確さに依存する。
"""

from __future__ import annotations

from dataclasses import dataclass

CATALOG_TOP = "https://portal.data.metro.tokyo.lg.jp/"


@dataclass(frozen=True)
class Dataset:
    id: str
    name: str
    org: str
    axes: tuple[str, ...]  # 使用先の軸キー
    format: str  # CSV / GIS / SHP / GTFS / API / XLS など
    catalog_url: str | None = None  # カタログの掲載ページ
    download_url: str | None = None  # 実ファイル。未確定なら None
    license: str | None = None
    updated_at: str | None = None  # データ側の更新日（判明したら埋める）
    notes: str = ""
    filename: str | None = None  # 保存名。未指定ならURL末尾

    @property
    def is_resolved(self) -> bool:
        """ダウンロードURLが確定しているか。"""
        return bool(self.download_url)

    def to_source(self) -> dict:
        """municipalities.json の meta.sources 用の辞書。"""
        return {
            "id": self.id,
            "name": self.name,
            "org": self.org,
            "url": self.catalog_url or CATALOG_TOP,
            "license": self.license,
            "updated_at": self.updated_at,
            "notes": self.notes or None,
        }


_DATASETS: tuple[Dataset, ...] = (
    Dataset(
        id="D1",
        name="PM2.5モニタリングデータ（1分値）",
        org="東京都環境局",
        axes=("quiet",),
        format="API/CSV",
        notes="測定局を自治体に空間結合する。局のない自治体は近傍局で補完する方針（補完した旨を画面に出す）。",
    ),
    Dataset(
        id="D2",
        name="自動車騒音の常時監視結果",
        org="各区市町村",
        axes=("quiet",),
        format="CSV",
        notes="公開元が自治体ごとに異なり、53自治体分は揃わない見込み。R1の対策としてD3/D4で近似する。",
    ),
    Dataset(
        id="D3",
        name="交通量統計表",
        org="警視庁",
        axes=("quiet",),
        format="CSV/PDF",
        notes="地点データ。自治体単位に平均する。",
    ),
    Dataset(
        id="D4",
        name="道路交通センサス",
        org="東京都建設局",
        axes=("quiet",),
        format="CSV",
        notes="平成27年度と古いため参考扱い。指標に採用する場合は更新年を画面に明示する。",
    ),
    Dataset(
        id="D5",
        name="緑のオープンデータ",
        org="東京都都市整備局",
        axes=("refresh",),
        format="GIS",
        notes="本土部のみ。島しょ部は欠損。ライセンス条件は要確認。",
    ),
    Dataset(
        id="D6",
        name="エコロジカル・ネットワークマップ",
        org="東京都環境局",
        axes=("refresh",),
        format="GIS",
    ),
    Dataset(
        id="D7",
        name="TOKYO WALKING MAP",
        org="東京都保健医療局",
        axes=("refresh",),
        format="未確認",
        notes="コース数・距離を自治体単位に集計する。",
    ),
    Dataset(
        id="D8",
        name="自転車走行空間について",
        org="東京都建設局",
        axes=("refresh",),
        format="未確認",
        notes="都道分のみ。区市町村道は含まれない点を画面に明記する。",
    ),
    Dataset(
        id="D9",
        name="公共施設一覧（図書館・文化施設・公園）",
        org="東京都デジタルサービス局",
        axes=("refresh", "workspace", "community"),
        format="CSV",
        catalog_url="https://catalog.data.metro.tokyo.lg.jp/dataset/t000029d0000000030",
        notes="都立中心。区市町村立は別途収集が必要。",
    ),
    Dataset(
        id="D10",
        name="「TOKYOテレワークアプリ」掲載サテライトオフィス一覧データ",
        org="東京都産業労働局",
        axes=("workspace",),
        format="CSV",
        catalog_url="https://catalog.data.metro.tokyo.lg.jp/dataset/t000012d0000000019",
        notes="掲載許諾済みの施設のみ収録。網羅性の限界を画面に明記する（R2）。",
    ),
    Dataset(
        id="D11",
        name="施設関連情報_生涯学習センター",
        org="東京都教育庁",
        axes=("workspace",),
        format="CSV",
    ),
    Dataset(
        id="D12",
        name="都営バス・都営地下鉄オープンデータ",
        org="東京都交通局",
        axes=("commute",),
        format="GTFS",
        catalog_url="https://catalog.data.metro.tokyo.lg.jp/dataset/t000018d0000000052",
        notes="都営のみ。JR・私鉄は含まれないため、通勤指標は近似になる（R3）。",
    ),
    Dataset(
        id="D13",
        name="地価公示（東京都分）",
        org="東京都財務局",
        axes=("cost",),
        format="CSV",
        catalog_url="https://catalog.data.metro.tokyo.lg.jp/dataset/t000004d0000000004",
        notes="用途区分「住宅地」で絞って自治体内平均をとる。",
    ),
    Dataset(
        id="D14",
        name="東京都基準地価格（地価調査）",
        org="東京都財務局",
        axes=("cost",),
        format="未確認",
        notes="D13で地点が不足する自治体の補完に使う。",
    ),
    Dataset(
        id="D15",
        name="土地利用現況調査GISデータ",
        org="東京都都市整備局",
        axes=("cost",),
        format="SHP",
        notes="区部は令和3年、多摩・島しょは令和4年と年次が異なる。",
    ),
    Dataset(
        id="D16",
        name="NPO法人情報",
        org="東京都生活文化スポーツ局",
        axes=("community",),
        format="CSV",
        notes="所在地から自治体を判定する。",
    ),
    Dataset(
        id="D17",
        name="東京の労働力 統計データ",
        org="東京都総務局",
        axes=("community",),
        format="未確認",
        notes="昼夜間人口比率など。",
    ),
    Dataset(
        id="D18",
        name="東京都統計年鑑（土地・気象 / 人口）",
        org="東京都総務局",
        axes=("common",),
        format="HTML/XLS",
        notes="面積・人口。全指標の分母になるため最優先で整備する。",
    ),
    Dataset(
        id="D19",
        name="行政区域データ（国土数値情報 N03）",
        org="国土交通省 国土数値情報ダウンロードサイト",
        axes=("common",),
        format="GeoJSON/SHP",
        catalog_url="https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-v3_1.html",
        license="国土数値情報 利用約款",
        notes="コロプレス描画と空間結合の基準ポリゴン。年次を固定してURLを確定させること。",
    ),
)

DATASETS: dict[str, Dataset] = {d.id: d for d in _DATASETS}


def get(dataset_id: str) -> Dataset:
    if dataset_id not in DATASETS:
        raise KeyError(f"未知のデータセットID: {dataset_id}")
    return DATASETS[dataset_id]


def resolved() -> list[Dataset]:
    """ダウンロードURLが確定しているデータセット。"""
    return [d for d in _DATASETS if d.is_resolved]


def unresolved() -> list[Dataset]:
    """URL未確定のデータセット（仕様書12章のデータ実査で埋める対象）。"""
    return [d for d in _DATASETS if not d.is_resolved]


def sources_for(dataset_ids: set[str] | list[str]) -> list[dict]:
    """実際に使った出典だけを meta.sources 用に整形して返す。"""
    wanted = set(dataset_ids)
    return [d.to_source() for d in _DATASETS if d.id in wanted]
