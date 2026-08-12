"""使用オープンデータの定義。

URL は 2026-08-12 に東京都オープンデータカタログ（CKAN API）から取得し、
実ファイルが返ることを HTTP レスポンスで確認済み。カタログ掲載データは
東京都オープンデータ利用規約に基づき CC BY 4.0（改変・商用可、クレジット必須）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CATALOG_TOP = "https://portal.data.metro.tokyo.lg.jp/"
CATALOG_DATASET = "https://catalog.data.metro.tokyo.lg.jp/dataset/"

LICENSE_CC_BY = "CC BY 4.0（東京都オープンデータ利用規約）"
# 都カタログには載るがライセンス欄が「その他」で、個別の注意事項PDFが優先されるもの
LICENSE_TOKYO_OTHER = "東京都オープンデータ利用規約（個別の注意事項あり）"
LICENSE_MLIT = "国土数値情報 利用約款（公共データ利用規約 PDL1.0）"

# ok      … ダウンロードURLが確定していて、そのまま取得できる
# pending … データ自体は存在するが、利用開始に手続きが要る（ODPTのユーザ登録など）
Status = Literal["ok", "pending"]


@dataclass(frozen=True)
class Resource:
    """データセットを構成する実ファイル1つ。"""

    key: str  # データセット内での役割。ログ表示とマニフェストのキーに使う
    url: str
    filename: str  # raw/<データセットID>/ 配下での保存名
    # 100MB超など、既定の一括取得から外すもの。`ingest --heavy` か `--only` で取る
    heavy: bool = False
    notes: str = ""


@dataclass(frozen=True)
class Dataset:
    id: str
    name: str
    org: str
    axes: tuple[str, ...]  # 使用先の軸キー
    format: str  # CSV / SHP / XLSX / GTFS / JSON など
    status: Status = "ok"
    catalog_id: str | None = None  # 東京都オープンデータカタログのデータセットID
    source_url: str | None = None  # 都カタログ外のデータの掲載ページ
    resources: tuple[Resource, ...] = ()
    license: str | None = None
    updated_at: str | None = None  # データ側の年次・時点
    notes: str = ""

    @property
    def catalog_url(self) -> str:
        """出典として示すページ。"""
        if self.catalog_id:
            return CATALOG_DATASET + self.catalog_id
        return self.source_url or CATALOG_TOP

    @property
    def is_resolved(self) -> bool:
        """取得先が確定しているか。"""
        return self.status == "ok" and bool(self.resources)

    def to_source(self) -> dict:
        """municipalities.json の meta.sources 用の辞書。"""
        return {
            "id": self.id,
            "name": self.name,
            "org": self.org,
            "url": self.catalog_url,
            "license": self.license,
            "updated_at": self.updated_at,
            "notes": self.notes or None,
        }


_DATASETS: tuple[Dataset, ...] = (
    Dataset(
        id="D1",
        name="PM2.5(微小粒子状物質)モニタリングデータ(1分値)",
        org="東京都環境局",
        axes=("quiet",),
        format="CSV/ZIP",
        catalog_id="t000009d2000000067",
        license=LICENSE_CC_BY,
        updated_at="直近50日分・日次更新",
        resources=(
            Resource(
                key="stations",
                url="https://www.taiki.kankyo.metro.tokyo.lg.jp/taikikankyo5g/catalogdata/mast/130001_tokyo_airpollution_station_master.csv",
                filename="stations.csv",
                notes="局コード・局名・市区町村コード(5桁)・緯度経度。ヘッダ行なし。",
            ),
            Resource(
                key="pm25",
                url="https://www.taiki.kankyo.metro.tokyo.lg.jp/taikikankyo5g/catalogdata/data/130001_tokyo_airpollution_PM2.5.zip",
                filename="pm25_1min_recent50days.zip",
                notes="速報値。月別ZIPは …_PM2.5_YYYYMM.zip で遡れる。",
            ),
        ),
        notes=(
            "公開されているのは1分値の速報値のみで、年平均値はこのデータからは作れない。"
            "直近50日平均か、月別ZIPを複数取得して期間平均をとる。"
            "測定局は全自治体にはないため、局のない自治体は近傍局で補完する（補完した旨を画面に出す）。"
        ),
    ),
    Dataset(
        id="D2",
        name="交通量統計表",
        org="警視庁",
        axes=("quiet",),
        format="CSV/ZIP",
        catalog_id="t000022d0000000035",
        license=LICENSE_CC_BY,
        updated_at="令和6年調査",
        resources=(
            Resource(
                key="results",
                url="https://www.keishicho.metro.tokyo.lg.jp/about_mpd/jokyo_tokei/tokei_jokyo/ryo.files/02_cyousakekka_csv.zip",
                filename="cyousakekka.zip",
            ),
            Resource(
                key="kousaten_ku",
                url="https://www.keishicho.metro.tokyo.lg.jp/about_mpd/jokyo_tokei/tokei_jokyo/ryo.files/02_kousatenkubu_csv.zip",
                filename="kousaten_kubu.zip",
            ),
            Resource(
                key="kousaten_tama",
                url="https://www.keishicho.metro.tokyo.lg.jp/about_mpd/jokyo_tokei/tokei_jokyo/ryo.files/02_kousatentamabu_csv.zip",
                filename="kousaten_tamabu.zip",
            ),
        ),
        notes=(
            "01_ が奇数年調査、02_ が偶数年調査で、内容が新しいのは 02_（令和6年）。"
            "集計単位は方面・スクリーンライン・交差点で、自治体コードを持つ列がない。"
            "自治体別に落とすには交差点名からの住所推定が要るため、参考扱いにとどめる。"
        ),
    ),
    Dataset(
        id="D3",
        name="平成27年度　全国道路交通情報調査道路交通センサス",
        org="東京都建設局",
        axes=("quiet",),
        format="XLSX",
        catalog_id="t000014d0000000009",
        license=LICENSE_CC_BY,
        updated_at="平成27年度（2015年）",
        resources=(
            Resource(
                key="summary_shi",
                url="https://www.opendata.metro.tokyo.lg.jp/kensetsu/t000014d0000000009/a-2_h27_shichoson_hei.xlsx",
                filename="a2_h27_shichoson_heijitsu.xlsx",
            ),
            Resource(
                key="summary_ku",
                url="https://www.opendata.metro.tokyo.lg.jp/kensetsu/t000014d0000000009/a-4_h27_tokubetsuku_hei.xlsx",
                filename="a4_h27_tokubetsuku_heijitsu.xlsx",
            ),
        ),
        notes=(
            "取得するのは平日の総括表（市部・区部）。1行1観測地点で、列は路線番号／路線名／"
            "地点番号／地点名称と車種別交通量。自治体コード列はないため、"
            "地点名称から自治体を推定する必要がある。平成27年度と古く、更新年を画面に明示する。"
        ),
    ),
    Dataset(
        id="D4",
        name="緑のオープンデータ（GISデータ）",
        org="東京都都市整備局",
        axes=("refresh",),
        format="SHP",
        catalog_id="t000008d2000000024",
        license=LICENSE_TOKYO_OTHER,
        updated_at="令和8年2月2日時点",
        resources=(
            Resource(
                key="notice",
                url="https://data.storage.data.metro.tokyo.lg.jp/toshiseibi/green_chuui.pdf",
                filename="green_chuui.pdf",
                notes="【必読】利用に当たっての注意事項。出典として手元に残す。",
            ),
            Resource(
                key="parks",
                url="https://data.storage.data.metro.tokyo.lg.jp/toshiseibi/01_kouenryokuchi.zip",
                filename="01_kouenryokuchi.zip",
                notes="都立・区市町村立・国営・海上公園などのポリゴン。約3.6MB。",
            ),
            Resource(
                key="woods",
                url="https://data.storage.data.metro.tokyo.lg.jp/toshiseibi/03_jurinchi.zip",
                filename="03_jurinchi.zip",
                heavy=True,
                notes="樹林地ポリゴン。約474MB。緑被率に使う。",
            ),
        ),
        notes=(
            "本土部のみで島しょ部は欠損。注意事項PDFの制限は精度に関するもので二次利用は妨げないが、"
            "「宅地化農地」「市街化調整区域内農地」だけは東京都地形図（国土地理院承認）由来のため"
            "別途手続きが要る。この2レイヤは使わない。"
        ),
    ),
    Dataset(
        id="D5",
        name="TOKYO WALKING MAP",
        org="東京都保健医療局",
        axes=("refresh",),
        format="JSON",
        catalog_id="t000055d0000000363",
        license=LICENSE_CC_BY,
        resources=(
            Resource(
                key="package",
                url="https://catalog.data.metro.tokyo.lg.jp/api/3/action/package_show?id=t000055d0000000363",
                filename="package.json",
            ),
        ),
        notes=(
            "コースが1件1リソース（KMLのZIP）として登録されており、実体を落とさなくても"
            "カタログAPIのリソース一覧だけでコース数を数えられる。"
            "リソースURLのファイル名先頭6桁がチェックデジット付きの団体コードで、"
            "その先頭5桁が自治体コードになる（例: 131148… → 13114 中野区）。"
            "距離まで指標化するなら各KMLの取得が別途必要。"
            "原著作者の承諾が得られたコースのみ収録で、2026-08時点は29自治体・264コース。"
            "残り24自治体は no_data になる。"
        ),
    ),
    Dataset(
        id="D6",
        name="自転車走行空間について",
        org="東京都建設局",
        axes=("refresh",),
        format="SHP",
        catalog_id="t000014d0000000026",
        license=LICENSE_CC_BY,
        resources=(
            Resource(
                key="route",
                url="https://www.kensetsu.metro.tokyo.lg.jp/documents/d/kensetsu/000035730",
                filename="jitensha_suishou_route.zip",
                notes="自転車推奨ルート。URLに拡張子がないため保存名を明示する。",
            ),
            Resource(
                key="priority",
                url="https://www.kensetsu.metro.tokyo.lg.jp/content/000035729.zip",
                filename="yuusen_seibi_kukan.zip",
                notes="優先整備区間。カタログ側のURLはホスト名が誤記（metro.tokyo.jg.jp）で開けない。",
            ),
        ),
        notes="都道分のみで区市町村道は含まれない。その旨を画面に明記する。",
    ),
    Dataset(
        id="D7",
        name="公共施設一覧",
        org="東京都デジタルサービス局",
        axes=("refresh", "workspace", "community"),
        format="CSV",
        catalog_id="t000029d0000000030",
        license=LICENSE_CC_BY,
        resources=(
            Resource(
                key="facilities",
                url="https://www.opendata.metro.tokyo.lg.jp/suisyoudataset/130001_public_facility.csv",
                filename="public_facility.csv",
            ),
        ),
        notes=(
            "収録は都立図書館・都立文化施設・都立公園／庭園のみ。市区町村名列は空で、"
            "コード列にも都のコードしか入らないため、住所または緯度経度から自治体を判定する。"
            "区市町村立施設は D4（公園）などで補う。文字コードは CP932。"
        ),
    ),
    Dataset(
        id="D8",
        name="「TOKYOテレワークアプリ」掲載サテライトオフィス一覧データ",
        org="東京都産業労働局",
        axes=("workspace",),
        format="CSV",
        catalog_id="t000012d0000000019",
        license=LICENSE_CC_BY,
        resources=(
            Resource(
                key="offices",
                url="https://www.opendata.metro.tokyo.lg.jp/sangyouroudou/tokyo-telework2401.csv",
                filename="satellite_office.csv",
            ),
        ),
        notes=(
            "「区市町村コード」列に5桁コードが入っているので空間結合は不要。UTF-8 BOM付き。"
            "掲載許諾済みの施設のみ収録のため網羅性に限界がある。その旨を画面に明記する。"
        ),
    ),
    Dataset(
        id="D9",
        name="施設関連情報_生涯学習センター",
        org="東京都教育庁",
        axes=("workspace",),
        format="CSV",
        catalog_id="t000021d2000000023",
        license=LICENSE_CC_BY,
        resources=(
            Resource(
                key="centers",
                url="https://www.opendata.metro.tokyo.lg.jp/kyouiku/R3/skshubetu_8.csv",
                filename="shougai_gakushu_center.csv",
            ),
        ),
        notes=(
            "区市町村名・緯度経度つきだが全体で数KBしかなく収録件数が少ない。"
            "文化施設の指標にするなら同じ教育庁の博物館・公民館データセットの併用を検討する。"
            "文字コードは CP932。"
        ),
    ),
    Dataset(
        id="D10",
        name="東京都交通局 都営バス・都営地下鉄オープンデータ",
        org="東京都交通局",
        axes=("commute",),
        format="GTFS/JSON",
        status="pending",
        catalog_id="t000018d0000000052",
        license="公共交通オープンデータセンター 開発者サイトの利用条件",
        notes=(
            "カタログのリソースはすべて ckan.odpt.org へのリンク。静的データ自体は"
            "api-public.odpt.org から認証なしで取得できるが、開発者サイトの利用条件が"
            "CC BY とは別に定められているため、条件を読むまで取得先を確定させない。"
            "登録して条件を確認するまで取得先を確定できない。都営のみでJR・私鉄は含まれない。"
        ),
    ),
    Dataset(
        id="D11",
        name="地価公示（東京都分）",
        org="東京都財務局",
        axes=("cost",),
        format="CSV",
        catalog_id="t000004d0000000004",
        license=LICENSE_CC_BY,
        updated_at="令和8年地価公示",
        resources=(
            Resource(
                key="points",
                url="https://www.zaimu.metro.tokyo.lg.jp/documents/d/zaimu/12_R8kouji_chiten_opendata",
                filename="r8_kouji_chiten.csv",
                notes="URLに拡張子がないため保存名を明示する。",
            ),
        ),
        notes=(
            "1行目が表題で、ヘッダは2行目。「都道府県市区町村コード」に5桁コードが入る。"
            "用途は「標準地番号（用途）」で区分され、住宅地は 0。文字コードは CP932。"
        ),
    ),
    Dataset(
        id="D12",
        name="東京都基準地価格（地価調査）",
        org="東京都財務局",
        axes=("cost",),
        format="CSV",
        catalog_id="t000004d0000000001",
        license=LICENSE_CC_BY,
        updated_at="令和7年地価調査",
        resources=(
            Resource(
                key="points",
                url="https://www.zaimu1.metro.tokyo.lg.jp/kijun/R7nen/05-02_r7data_kakaku.csv",
                filename="r7_kijunchi_kakaku.csv",
            ),
        ),
        notes="D11と同じ構造（表題行＋5桁コード、CP932）。D11で地点が不足する自治体の補完に使う。",
    ),
    Dataset(
        id="D13",
        name="土地利用現況調査GISデータ",
        org="東京都都市整備局",
        axes=("cost",),
        format="SHP",
        catalog_id="t000008d2000000019",
        license=LICENSE_TOKYO_OTHER,
        updated_at="区部:令和3年 / 多摩・島しょ:令和4年",
        resources=(
            Resource(
                key="kubu",
                url="https://data.storage.data.metro.tokyo.lg.jp/toshiseibi/R03.zip",
                filename="R03_kubu.zip",
                heavy=True,
                notes="令和3年 区部。約363MB。",
            ),
            Resource(
                key="tama",
                url="https://data.storage.data.metro.tokyo.lg.jp/toshiseibi/R04.zip",
                filename="R04_tama_tousho.zip",
                heavy=True,
                notes="令和4年 多摩・島しょ。約309MB。",
            ),
        ),
        notes=(
            "区部と多摩・島しょで調査年次が1年ずれる。2ファイル合計で約670MBあり、"
            "展開後はさらに膨らむので既定の一括取得からは外してある。"
        ),
    ),
    Dataset(
        id="D14",
        name="特定非営利活動法人（ＮＰＯ法人）情報",
        org="東京都生活文化スポーツ局",
        axes=("community",),
        format="CSV",
        catalog_id="t313360d0000000052",
        license=LICENSE_CC_BY,
        updated_at="月次更新",
        resources=(
            Resource(
                key="ninsyou",
                url="https://www.seikatubunka.metro.tokyo.lg.jp/houjin/npo_houjin/files/0000001246/ninsyou.csv",
                filename="ninsyou_npo.csv",
            ),
        ),
        notes=(
            "認証NPO法人 約9,300件。「主たる事務所」の住所から自治体を判定する。"
            "1行目が表題、2行目がヘッダで、ヘッダのセルに改行が入る。文字コードは CP932。"
            "表題行の日付表記は更新されていないので、鮮度の判断には使わない。"
        ),
    ),
    Dataset(
        id="D15",
        name="令和２年国勢調査による東京都の昼間人口（従業地・通学地による人口）",
        org="東京都総務局",
        axes=("community",),
        format="CSV",
        catalog_id="t000003d0000000627",
        license=LICENSE_CC_BY,
        updated_at="令和2年国勢調査",
        resources=(
            Resource(
                key="table1",
                url="https://www.toukei.metro.tokyo.lg.jp/tyukanj/2020/tj20zv0100.csv",
                filename="chukan_jinkou_hyou1.csv",
            ),
        ),
        notes=(
            "当初あてにしていた「東京の労働力 統計データ」は都全体の集計で区市町村別の"
            "内訳がなく、昼夜間人口比率を作れないため、こちらに差し替えた。"
            "第1表に地域コード・昼間人口・常住人口・昼夜間人口比率が揃っている。UTF-8 BOM付き。"
        ),
    ),
    Dataset(
        id="D16",
        name="東京都の人口（推計）",
        org="東京都総務局",
        axes=("common",),
        format="CSV",
        catalog_id="t000003d2000001136",
        license=LICENSE_CC_BY,
        updated_at="令和8年6月1日現在",
        resources=(
            Resource(
                key="population",
                url="https://www.toukei.metro.tokyo.lg.jp/jsuikei/2026/js266v0000_1.csv",
                filename="jinkou_suikei.csv",
            ),
        ),
        notes=(
            "全指標の分母。地域コード・人口・面積(km2)・人口密度が1ファイルに揃うため、"
            "当初予定していた東京都統計年鑑（土地・気象／人口）の2本立てを置き換えられる。"
            "統計年鑑もカタログに掲載されており CC BY だが、最新が令和5年と古い。"
            "月次更新でURLの年月部分が変わるので、更新時はカタログで最新のデータセットIDを取り直す。"
            "UTF-8 BOM付き。"
        ),
    ),
    Dataset(
        id="D17",
        name="行政区域データ（国土数値情報 N03）",
        org="国土交通省 国土数値情報ダウンロードサイト",
        axes=("common",),
        format="SHP",
        source_url="https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-v3_1.html",
        license=LICENSE_MLIT,
        updated_at="令和8年1月1日",
        resources=(
            Resource(
                key="boundary",
                url="https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2026/N03-20260101_13_GML.zip",
                filename="N03-20260101_13_GML.zip",
            ),
        ),
        notes=(
            "コロプレス描画と空間結合の基準ポリゴン。ファイル名の 13 が東京都、"
            "20260101 が年次にあたる。年次を上げるときはこの数字だけを差し替える。"
        ),
    ),
    Dataset(
        id="D18",
        name="緊急輸送道路",
        org="東京都建設局",
        axes=("quiet",),
        format="SHP",
        catalog_id="t000014d2000000030",
        license=LICENSE_CC_BY,
        resources=(
            Resource(
                key="network",
                url="https://www.opendata.metro.tokyo.lg.jp/kensetsu/kinkyu_yusou.zip",
                filename="kinkyu_yusou.zip",
            ),
        ),
        notes=(
            "幹線道路密度の代理データ。都のカタログには都道そのものの線データがなく、"
            "国道・都道の主要路線で構成される緊急輸送道路ネットワークが最も近い。"
            "総延長 ÷ 面積で密度を出す。"
        ),
    ),
)

DATASETS: dict[str, Dataset] = {d.id: d for d in _DATASETS}


def get(dataset_id: str) -> Dataset:
    if dataset_id not in DATASETS:
        raise KeyError(f"未知のデータセットID: {dataset_id}")
    return DATASETS[dataset_id]


def resolved() -> list[Dataset]:
    """そのまま取得できるデータセット。"""
    return [d for d in _DATASETS if d.is_resolved]


def pending() -> list[Dataset]:
    """利用手続きが済めば使えるデータセット。"""
    return [d for d in _DATASETS if d.status == "pending"]


def sources_for(dataset_ids: set[str] | list[str]) -> list[dict]:
    """実際に使った出典だけを meta.sources 用に整形して返す。"""
    wanted = set(dataset_ids)
    return [d.to_source() for d in _DATASETS if d.id in wanted]
