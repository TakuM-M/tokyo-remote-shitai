# 使用データ一覧（D1〜D20）

定義の実体は [`data/src/datasets.py`](../data/src/datasets.py)。取得状況は `make datasets`、取得は `make ingest`。
ライセンスの考え方とクレジット表記は [data_license_check.md](./data_license_check.md)、採否や差替の経緯は [dev_note.md](./dev_note.md) を参照。

## 1. 一覧

状態は datasets.py の `status` に対応する。不採用＝`dropped`、手続き待ち＝`pending`、それ以外は `ok`。
「参考」は取得はするが軸スコアには算入しない見込みのもの。

| # | データセット名称 | 出所 | 用途 | 形式 | 状態 |
|---|---|---|---|---|---|
| D1 | PM2.5(微小粒子状物質)モニタリングデータ(1分値) | 環境局 | しずけさ | CSV/ZIP | 使用 |
| D2 | 自動車騒音の常時監視結果 | 区市町村（目黒区ほか） | しずけさ | CSV | 不採用 |
| D3 | 交通量統計表 | 警視庁 | しずけさ | CSV/ZIP | 参考 |
| D4 | 平成27年度 全国道路交通情報調査道路交通センサス | 建設局 | しずけさ | XLSX | 使用 |
| D5 | 緑のオープンデータ（GISデータ） | 都市整備局 | いきぬき | SHP | 使用 |
| D6 | エコロジカル・ネットワークマップ | 環境局 | いきぬき | PDF | 不採用 |
| D7 | TOKYO WALKING MAP | 保健医療局 | いきぬき | JSON/KML | 使用 |
| D8 | 自転車走行空間について | 建設局 | いきぬき | SHP | 使用 |
| D9 | 公共施設一覧 | デジタルサービス局 | いきぬき/しごとば/つながり | CSV | 使用 |
| D10 | 「TOKYOテレワークアプリ」掲載サテライトオフィス一覧データ | 産業労働局 | しごとば | CSV | 使用 |
| D11 | 施設関連情報_生涯学習センター | 教育庁 | しごとば | CSV | 使用 |
| D12 | 東京都交通局 都営バス・都営地下鉄オープンデータ | 交通局 | 出社 | GTFS/JSON | 手続き待ち |
| D13 | 地価公示（東京都分） | 財務局 | コスト | CSV | 使用 |
| D14 | 東京都基準地価格（地価調査） | 財務局 | コスト | CSV | 使用 |
| D15 | 土地利用現況調査GISデータ | 都市整備局 | コスト | SHP | 使用 |
| D16 | 特定非営利活動法人（ＮＰＯ法人）情報 | 生活文化スポーツ局 | つながり | CSV | 使用 |
| D17 | 令和２年国勢調査による東京都の昼間人口 | 総務局 | つながり | CSV | 使用 |
| D18 | 東京都の人口（推計） | 総務局 | 共通 | CSV | 使用 |
| D19 | 行政区域データ（国土数値情報 N03） | 国土交通省 | 共通/描画 | SHP | 使用 |
| D20 | 緊急輸送道路 | 建設局 | しずけさ | SHP | 使用 |

## 2. 取得先

1データセットが複数ファイルからなるものがある。`key` は `datasets.py` の `Resource.key`、実体は `raw/<ID>/<保存名>` に置かれる。

| # | key | カタログ | 実ファイル |
|---|---|---|---|
| D1 | stations | [t000009d2000000067](https://catalog.data.metro.tokyo.lg.jp/dataset/t000009d2000000067) | `.../taikikankyo5g/catalogdata/mast/130001_tokyo_airpollution_station_master.csv` |
| D1 | pm25 | 〃 | `.../taikikankyo5g/catalogdata/data/130001_tokyo_airpollution_PM2.5.zip` |
| D3 | results / kousaten_ku / kousaten_tama | [t000022d0000000035](https://catalog.data.metro.tokyo.lg.jp/dataset/t000022d0000000035) | `.../ryo.files/02_cyousakekka_csv.zip` ほか2件 |
| D4 | summary_shi / summary_ku | [t000014d0000000009](https://catalog.data.metro.tokyo.lg.jp/dataset/t000014d0000000009) | `.../t000014d0000000009/a-2_h27_shichoson_hei.xlsx`、`a-4_h27_tokubetsuku_hei.xlsx` |
| D5 | notice / parks / woods | [t000008d2000000024](https://catalog.data.metro.tokyo.lg.jp/dataset/t000008d2000000024) | `.../toshiseibi/green_chuui.pdf`、`01_kouenryokuchi.zip`、`03_jurinchi.zip` |
| D7 | package | [t000055d0000000363](https://catalog.data.metro.tokyo.lg.jp/dataset/t000055d0000000363) | `.../api/3/action/package_show?id=t000055d0000000363` |
| D8 | route / priority | [t000014d0000000026](https://catalog.data.metro.tokyo.lg.jp/dataset/t000014d0000000026) | `.../documents/d/kensetsu/000035730`、`.../content/000035729.zip` |
| D9 | facilities | [t000029d0000000030](https://catalog.data.metro.tokyo.lg.jp/dataset/t000029d0000000030) | `.../suisyoudataset/130001_public_facility.csv` |
| D10 | offices | [t000012d0000000019](https://catalog.data.metro.tokyo.lg.jp/dataset/t000012d0000000019) | `.../sangyouroudou/tokyo-telework2401.csv` |
| D11 | centers | [t000021d2000000023](https://catalog.data.metro.tokyo.lg.jp/dataset/t000021d2000000023) | `.../kyouiku/R3/skshubetu_8.csv` |
| D12 | — | [t000018d0000000052](https://catalog.data.metro.tokyo.lg.jp/dataset/t000018d0000000052) | 未確定（ODPT登録後に決まる） |
| D13 | points | [t000004d0000000004](https://catalog.data.metro.tokyo.lg.jp/dataset/t000004d0000000004) | `.../documents/d/zaimu/12_R8kouji_chiten_opendata` |
| D14 | points | [t000004d0000000001](https://catalog.data.metro.tokyo.lg.jp/dataset/t000004d0000000001) | `.../kijun/R7nen/05-02_r7data_kakaku.csv` |
| D15 | kubu / tama | [t000008d2000000019](https://catalog.data.metro.tokyo.lg.jp/dataset/t000008d2000000019) | `.../toshiseibi/R03.zip`、`R04.zip` |
| D16 | ninsyou | [t313360d0000000052](https://catalog.data.metro.tokyo.lg.jp/dataset/t313360d0000000052) | `.../npo_houjin/files/0000001246/ninsyou.csv` |
| D17 | table1 | [t000003d0000000627](https://catalog.data.metro.tokyo.lg.jp/dataset/t000003d0000000627) | `.../tyukanj/2020/tj20zv0100.csv` |
| D18 | population | [t000003d2000001136](https://catalog.data.metro.tokyo.lg.jp/dataset/t000003d2000001136) | `.../jsuikei/2026/js266v0000_1.csv` |
| D19 | boundary | [国土数値情報 N03](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-v3_1.html) | `.../ksj/gml/data/N03/N03-2026/N03-20260101_13_GML.zip` |
| D20 | network | [t000014d2000000030](https://catalog.data.metro.tokyo.lg.jp/dataset/t000014d2000000030) | `.../kensetsu/kinkyu_yusou.zip` |

## 3. データ構造

「自治体の特定」は、5桁の全国地方公共団体コードに解決する手段。
`コード列` はそのまま使える、`住所` / `自治体名` は `municipalities.py` で解決、`空間結合` は `spatial_join.py` で D19 のポリゴンに落とす。

| # | 自治体の特定 | 文字コード | 年次・時点 | 構造 |
|---|---|---|---|---|
| D1 | コード列（局マスタ） | CP932 | 直近50日・日次更新 | 局マスタCSV（ヘッダ行なし。局コード／局名／市区町村コード／緯度経度）と、1分値のZIP。月別ZIPは `…_PM2.5_YYYYMM.zip` で遡れる |
| D3 | 不可（地点名から推定） | CP932 | 令和6年調査 | ZIP1本に140前後のCSV。集計単位は方面・スクリーンライン・交差点 |
| D4 | 不可（地点名称から推定） | — | 平成27年度 | XLSX。市部・区部でファイルが分かれる。1行1観測地点で、列は路線番号／路線名／地点番号／地点名称と車種別交通量 |
| D5 | 空間結合 | — | 令和8年2月2日時点 | シェープファイル。公園・緑地等／樹林地など全18レイヤ。ZIP内は日本語ディレクトリ |
| D7 | リソースURLのファイル名先頭5桁 | UTF-8 | — | CKANの `package_show` JSON。`resources[].url` のファイル名先頭6桁が団体コード |
| D8 | 空間結合 | — | — | シェープファイル2種（自転車推奨ルート／優先整備区間） |
| D9 | 住所 / 緯度経度 | CP932 | — | 推奨データセット準拠のCSV。コード列は都のコードのみ、市区町村名列は空 |
| D10 | コード列（区市町村コード） | UTF-8 BOM | — | CSV。5桁コードが入るので空間結合は不要 |
| D11 | 自治体名 / 緯度経度 | CP932 | — | CSV。区市町村名・施設名・所在地・緯度経度 |
| D13 | コード列（都道府県市区町村コード） | CP932 | 令和8年地価公示 | CSV。1行目が表題でヘッダは2行目。用途は「標準地番号（用途）」で区分し、住宅地は 0 |
| D14 | コード列（都道府県市区町村コード） | CP932 | 令和7年地価調査 | D13と同構造 |
| D15 | 空間結合 | — | 区部:令和3年 / 多摩・島しょ:令和4年 | シェープファイル。区部と多摩・島しょで別ファイル・別年次。2ファイル計約670MB |
| D16 | 住所（主たる事務所） | CP932 | 月次更新 | CSV。1行目が表題、2行目がヘッダでセル内に改行が入る。認証NPO法人 約9,300件 |
| D17 | コード列（地域コード） | UTF-8 BOM | 令和2年国勢調査 | CSV第1表。地域コード／昼間人口／常住人口／昼夜間人口比率／面積 |
| D18 | コード列（地域コード） | UTF-8 BOM | 令和8年6月1日現在 | CSV。地域階層／地域コード／人口／面積(km2)／人口密度。月次更新でURLの年月部分が変わる |
| D19 | 基準ポリゴンそのもの | — | 令和8年1月1日 | シェープファイル＋GeoJSON。ファイル名の `13` が東京都、`20260101` が年次 |
| D20 | 空間結合 | — | — | シェープファイル。ZIP内の格納名はCP932 |

D2・D6・D12 は取得しないため省略。
