"""使用オープンデータの定義

`D-{ジャンル}-{連番2桁}`
ジャンル:（quiet / refresh / workspace / cost / community）
(全指標共通の分母・描画基盤:common)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# url
CATALOG_TOP = "https://portal.data.metro.tokyo.lg.jp/"
CATALOG_DATASET = "https://catalog.data.metro.tokyo.lg.jp/dataset/"

# license
LICENSE_CC_BY = "CC BY 4.0（東京都オープンデータ利用規約）"
LICENSE_TOKYO_OTHER = "東京都オープンデータ利用規約（個別の注意事項あり）"
LICENSE_MLIT = "国土数値情報 利用約款（公共データ利用規約 PDL1.0）"
LICENSE_ODPT = "CC BY 4.0（公共交通オープンデータセンター）"

# ok      … ダウンロードURLが確定していて、そのまま取得できる
# pending … データ自体は存在するが、利用条件の確認が済んでおらず取得先を確定させていない
Status = Literal["ok", "pending"]


@dataclass(frozen=True)
class Resource:
    """データセットを構成する実ファイル1つ。"""

    key: str  # データセット内での役割。ログ表示とマニフェストのキーに使う
    url: str
    filename: str  # raw/<データセットID>/ 配下での保存名
    # 100MB超など、既定の一括取得から外すもの。`ingest --heavy` か `--only` で取る
    heavy: bool = False
    # 年度別に分かれて配布されるデータで、そのファイルが表す年度（西暦）
    year: int | None = None
    # zip配布のうち、展開せず zip のまま読むもの。
    # 展開後が巨大なわりに使う列がごく一部のデータで指定する（PM2.5の1分値）。
    extract: bool = True
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


# PM2.5(D-quiet-01)の集計対象期間。既定のZIPは直近50日分しか入っておらず、
# それだけでは季節変動を含む年平均値にならないため、月別ZIPを12か月分そろえる。
# 2025年6月〜2026年5月。ちょうど1年ぶんにして、どの月も1回だけ入るようにしている。
PM25_MONTHS: tuple[str, ...] = (
    "202506",
    "202507",
    "202508",
    "202509",
    "202510",
    "202511",
    "202512",
    "202601",
    "202602",
    "202603",
    "202604",
    "202605",
)

_PM25_BASE = "https://www.taiki.kankyo.metro.tokyo.lg.jp/taikikankyo5g/catalogdata/data/"


def pm25_resource_key(month: str) -> str:
    """`PM25_MONTHS` の要素から D-quiet-01 のリソースキーを作る。"""
    return f"pm25_{month}"


def _pm25_monthly_resources() -> tuple[Resource, ...]:
    return tuple(
        Resource(
            key=pm25_resource_key(m),
            url=f"{_PM25_BASE}130001_tokyo_airpollution_PM2.5_{m}.zip",
            filename=f"pm25_1min_{m}.zip",
            extract=False,
            notes=f"{m[:4]}年{int(m[4:])}月分の1分値（1か月あたり約11MB）。",
        )
        for m in PM25_MONTHS
    )


_DATASETS: tuple[Dataset, ...] = (
    # しずけさ
    Dataset(
        id="D-quiet-01",
        name="PM2.5(微小粒子状物質)モニタリングデータ(1分値)",
        org="東京都環境局",
        # IDは しずけさ 用に採ったときの名残。PM2.5は「外で過ごすときの空気の質」として
        # いきぬき軸で使っている。IDを変えると raw/ と interim/ のパスまで動くので据え置く。
        axes=("refresh",),
        format="CSV/ZIP",
        catalog_id="t000009d2000000067",
        license=LICENSE_CC_BY,
        updated_at="2025年6月〜2026年5月（月別ZIP12か月分）",
        resources=(
            Resource(
                key="stations",
                url="https://www.taiki.kankyo.metro.tokyo.lg.jp/taikikankyo5g/catalogdata/mast/130001_tokyo_airpollution_station_master.csv",
                filename="stations.csv",
                notes="局コード・局名・市区町村コード(5桁)・緯度経度。ヘッダ行なし。",
            ),
            *_pm25_monthly_resources(),
        ),
        notes=(
            "公開されているのは1分値の速報値のみ。既定の配布ZIPは直近50日分しか入らないため、"
            "月別ZIP（…_PM2.5_YYYYMM.zip）を12か月分取得して年平均値を組み立てている。"
            "測定局は全自治体にはないため、局のない自治体は近傍局で補完する（補完した旨を画面に出す）。"
        ),
    ),
    Dataset(
        id="D-quiet-02",
        name="自動車交通騒音調査結果",
        org="東京都環境局",
        axes=("quiet",),
        format="CSV",
        catalog_id="t000009d1900000003",
        license=LICENSE_CC_BY,
        updated_at="平成20〜25年度（2008〜2013年度）",
        resources=(
            Resource(
                key="h25",
                url="https://www.opendata.metro.tokyo.lg.jp/kankyo/vehicle/noise/H25/H25_kekka.csv",
                filename="h25_kekka.csv",
                year=2013,
                notes="平成25年度分。カタログID t000009d1900000003",
            ),
            Resource(
                key="h24",
                url="https://www.opendata.metro.tokyo.lg.jp/kankyo/vehicle/noise/H24/H24_kekka.csv",
                filename="h24_kekka.csv",
                year=2012,
                notes="平成24年度分。カタログID t000009d1900000004",
            ),
            Resource(
                key="h23",
                url="https://www.opendata.metro.tokyo.lg.jp/kankyo/vehicle/noise/H23/H23_kekka.csv",
                filename="h23_kekka.csv",
                year=2011,
                notes="平成23年度分。カタログID t000009d1900000005",
            ),
            Resource(
                key="h22",
                url="https://www.opendata.metro.tokyo.lg.jp/kankyo/vehicle/noise/H22/H22_kekka2.csv",
                filename="h22_kekka.csv",
                year=2010,
                notes="平成22年度分。カタログID t000009d1900000006。この年度だけURLが kekka2。",
            ),
            Resource(
                key="h21",
                url="https://www.opendata.metro.tokyo.lg.jp/kankyo/vehicle/noise/H21/H21_kekka.csv",
                filename="h21_kekka.csv",
                year=2009,
                notes="平成21年度分。カタログID t000009d1900000007",
            ),
            Resource(
                key="h20",
                url="https://www.opendata.metro.tokyo.lg.jp/kankyo/vehicle/noise/H20/H20_kekka.csv",
                filename="h20_kekka.csv",
                year=2008,
                notes="平成20年度分。カタログID t000009d1900000008",
            ),
        ),
        notes=(
            "幹線道路沿いの測定地点ごとに昼間・夜間の等価騒音レベル(Leq)が入る。"
            "住所列の先頭が自治体名なので空間結合は不要。"
            "1年度あたり約600地点だが調査地点は年度ごとに入れ替わり、"
            "単年では測定のない自治体が出る（平成25年度は檜原村が欠測）。"
            "6年分を合わせると53自治体すべてが埋まるため、自治体ごとに6年度分の"
            "地点をまとめて平均する。単年だと1自治体あたりの地点数が1〜40件と偏り、"
            "その年に測った道路がそのまま値になってしまうため"
            "（奥多摩町は平成25年度の4地点で68.8dB、6年度13地点では64.5dB）。"
            "文字コードは CP932。"
        ),
    ),
    # いきぬき
    Dataset(
        id="D-refresh-01",
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
                notes=(
                    "都立・区市町村立・国営・海上公園などのポリゴン14レイヤ（うち1つは点）。約3.6MB。"
                    "属性の「面積m2」は調書ベースの数値でポリゴン面積と乖離し、欠損が -9999 で入る"
                    "（210件）ため使わない。面積はポリゴンから測る。"
                ),
            ),
        ),
        notes=(
            "本土部のみで島しょ部は欠損。注意事項PDFの制限は精度に関するもので二次利用は妨げないが、"
            "「宅地化農地」「市街化調整区域内農地」だけは東京都地形図（国土地理院承認）由来のため"
            "別途手続きが要る。この2レイヤは使わない。"
            "同梱の樹林地（03_jurinchi.zip・約474MB）も使わない。市街地の樹林だけで山林を含まず"
            "（檜原村0.01km2・奥多摩町0.01km2）、緑の総量は D-refresh-02 の緑・水辺率で測るため。"
            "公園側は海上公園の3レイヤが同じ公園を重複収録し水域も含むので開園区域のみを使い、"
            "計画決定区域・予定地・霊園・葬儀所・点データは外す。"
            "檜原村は都市計画区域外で公園調書に載らず、公園レイヤに1件も無い（値は0でなく欠損）。"
        ),
    ),
    Dataset(
        id="D-refresh-02",
        name="土地利用細分メッシュ（国土数値情報 L03-b）",
        org="国土交通省 国土数値情報ダウンロードサイト",
        axes=("refresh",),
        format="SHP",
        source_url="https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html",
        license=LICENSE_MLIT,
        updated_at="平成28年度（2016年度）",
        resources=(
            Resource(
                key="mesh_5339",
                url="https://nlftp.mlit.go.jp/ksj/gml/data/L03-b/L03-b-16/L03-b-16_5339-jgd_GML.zip",
                filename="L03-b-16_5339-jgd_GML.zip",
                year=2016,
                notes="東経139〜140度・北緯35度20分〜36度。都本土部のほぼ全域。約13MB。",
            ),
            Resource(
                key="mesh_5338",
                url="https://nlftp.mlit.go.jp/ksj/gml/data/L03-b/L03-b-16/L03-b-16_5338-jgd_GML.zip",
                filename="L03-b-16_5338-jgd_GML.zip",
                year=2016,
                notes=(
                    "東経138〜139度。都の西端（東経138.94）がはみ出す分で、"
                    "奥多摩町の42km2（同町の18%）がこちらに入る。約13MB。"
                ),
            ),
        ),
        notes=(
            "100mメッシュ（3次メッシュの1/10細分）1つが1ポリゴンで、土地利用種のコードを持つ。"
            "2次メッシュコードは 上2桁=緯度×1.5・下2桁=経度-100 で、"
            "都本土部（東経138.94〜139.92）に必要なのは 5339 と 5338 の2枚。"
            "1枚あたり約46万ポリゴン。CRSは EPSG:4612（JGD2000）。"
            "最新は令和3年度版だが、そちらは都市地域を対象にした -u 版しか無く、"
            "都市計画区域外の奥多摩町・檜原村が落ちる。山林を数えるのが目的なので、"
            "全国をカバーする通常版の最終年次である平成28年度版を使う。"
            "属性名が CP932 のまま格納されており、既定の読み方だと化ける"
            "（列順は メッシュ, 土地利用種, 撮影年月日）。"
            "緑とみなすのは 田(0100)・その他の農用地(0200)・森林(0500)・荒地(0600)・"
            "河川地及び湖沼(1100) の5種。川辺・湖畔は息抜きに行ける場所なので水面も入れる。"
            "ゴルフ場(1600) は私有地で立ち入れず気分転換の場にならないので含めない。"
            "【限界1】100mメッシュに分類を1つだけ割り当てる形式のため、市街地の街路樹・庭・"
            "社寺林・街区公園は建物用地メッシュに吸収されて消え、区部の緑が構造的に過小評価される。"
            "実測でも23区は0.88%（豊島区）〜19.91%（千代田区）に収まり、拾えているのは"
            "皇居・明治神宮のようなまとまった緑と大きな河川だけ。区部の解像度は公園面積比が担う。"
            "【限界2】面積加重した値は区部8.1%・多摩部57.6%で、"
            "東京都公表の「みどり率」（区部24.0%・多摩部67.4%）とは定義も分解能も異なる。"
            "水面を含めたことで差は縮んだが、みどり率がさらに含む公園区域はこちらでは"
            "公園面積比が別に持つ。区部に残る差はメッシュの分解能によるもので、"
            "みどり率の代用にはならない。"
        ),
    ),
    # しごとば
    Dataset(
        id="D-workspace-01",
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
        id="D-workspace-02",
        name="施設関連情報_図書館",
        org="東京都教育庁",
        axes=("workspace",),
        format="CSV",
        catalog_id="t000021d2000000003",
        license=LICENSE_CC_BY,
        updated_at="令和3年3月（カタログ登録時点）",
        resources=(
            Resource(
                key="libraries",
                url="https://www.opendata.metro.tokyo.lg.jp/kyouiku/R3/skshubetu_4.csv",
                filename="library.csv",
                notes="区市町村名／施設区分／施設名／所在地／緯度経度／電話番号。417件。",
            ),
        ),
        notes=(
            "都内の公立図書館一覧。「区市町村名」列があるので空間結合は不要。文字コードは CP932。"
            "島しょ部を含む58自治体が載り、本土53自治体はすべて1館以上ある"
            "（最少は狛江市・檜原村の1館、最多は世田谷区の18館）。"
            "末尾に注記の行が1行あるが、自治体名が空なのでコード解決の段階で落ちる。"
            "同名のデータセットがカタログに2件あり、もう一方（t000021d2000000019）は"
            "無関係な特別支援教育の統計CSVが同じデータセットに混在している。"
            "図書館CSV1件だけを持つこちらを使う。"
            "更新頻度は「随時」だが、リソースの登録は令和3年3月から動いていない。"
        ),
    ),
    # くらしのコスト
    Dataset(
        id="D-cost-01",
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
    # つながり
    Dataset(
        id="D-community-01",
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
        id="D-community-02",
        name="東京都統計年鑑　令和5年　17　教育・文化・スポーツ",
        org="東京都総務局",
        axes=("community",),
        format="CSV",
        catalog_id="t000003d2000001028",
        license=LICENSE_CC_BY,
        updated_at="令和5年度（施設数は令和5年5月1日現在）",
        resources=(
            Resource(
                key="social_education",
                url="https://www.toukei.metro.tokyo.lg.jp/tnenkan/2023/tn23qv170800.csv",
                filename="social_education.csv",
                year=2023,
                notes="表17-8 社会教育施設数及び社会教育事業数。この1表だけを使う。",
            ),
        ),
        notes=(
            "章まるごとが1データセットで、使うのは表17-8のみ。"
            "「地域コード」に5桁コードが入るので空間結合は不要。UTF-8 BOM付き。"
            "1行1自治体で、総数・区部・市部・郡部・島部の集計行と島しょ部が同じ表に混ざるが、"
            "自治体コードに解決できないか対象外なので落ちる。末尾5行は注記。"
            "採るのは「学級・事業数（総数）」で、学級・講座（対象別）と分野別事業数の合計にあたる。"
            "同じ表にある「施設数」は使わない。図書館数との順位相関が0.80あり、"
            "しごとば軸の図書館密度と同じものを測ってしまうため。"
            "原資料は都教育庁生涯学習課「区市町村生涯学習・社会教育行政データブック」。"
            "自治体によって事業の数え方が揃っていない可能性があり"
            "（施設数が近い新宿区41件と品川区526件のような開きがある）、生の件数ではなく"
            "順位に直してから使う。年次を上げるときはURLの 2023 と tn23 を差し替える。"
        ),
    ),
    # 共通（分母・描画基盤）
    Dataset(
        id="D-common-01",
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
        id="D-common-02",
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
    """利用条件の確認が済めば使えるデータセット。"""
    return [d for d in _DATASETS if d.status == "pending"]


def sources_for(dataset_ids: set[str] | list[str]) -> list[dict]:
    """実際に使った出典だけを meta.sources 用に整形して返す。"""
    wanted = set(dataset_ids)
    return [d.to_source() for d in _DATASETS if d.id in wanted]
