# 使用データ一覧（全18件）

- IDは `D-{ジャンル}-{連番2桁}`。ジャンルは主な使い道の軸キー、複数の軸で使うものと全指標共通の分母・描画基盤は `common`。連番はジャンルごとに1から振る。`raw/<ID>/` のディレクトリ名と出力JSONの `source` にそのまま出る
- 定義の実体 [`data/src/defs/datasets.py`](../data/src/defs/datasets.py)
- 取得状況は `make datasets`, 取得は `make ingest`。
- ライセンスの考え方とクレジット表記 [data_license_check.md](./data_license_check.md)
- 採否や差替の経緯は [dev_note.md](./dev_note.md) 

## 1. 一覧

判定は利用可否。◎ カタログ掲載でそのまま使える ／ ○ カタログ掲載だが個別条件あり ／ △ 都庁以外の自治体データで個別確認が要る。
判定の根拠と個別条件の中身は [data_license_check.md](./data_license_check.md) の3節にある。

| # | データセット名称 | 出所 | 用途 | 形式 | 判定 | 状態 |
|---|---|---|---|---|---|---|
| D-quiet-01 | PM2.5(微小粒子状物質)モニタリングデータ(1分値) | 環境局 | しずけさ | CSV/ZIP | ◎ | 使用 |
| D-quiet-02 | 自動車交通騒音調査結果 | 環境局 | しずけさ | CSV | ◎ | 使用（平成20〜25年度の6年分） |
| D-refresh-01 | 緑のオープンデータ（GISデータ） | 都市整備局 | いきぬき | SHP | ○ | 使用 |
| D-refresh-02 | TOKYO WALKING MAP | 保健医療局 | いきぬき | JSON/KML | ◎ | 使用 |
| D-refresh-03 | 自転車走行空間について | 建設局 | いきぬき | SHP | ◎ | 使用 |
| D-workspace-01 | 「TOKYOテレワークアプリ」掲載サテライトオフィス一覧データ | 産業労働局 | しごとば | CSV | ◎ | 使用 |
| D-workspace-02 | 施設関連情報_生涯学習センター | 教育庁 | しごとば | CSV | ◎ | 使用 |
| D-commute-01 | 東京都交通局 都営バス・都営地下鉄オープンデータ | 交通局 | 出社 | GTFS/JSON | ◎ | 使用（都営のみ） |
| D-cost-01 | 地価公示（東京都分） | 財務局 | コスト | CSV | ◎ | 使用 |
| D-cost-02 | 東京都基準地価格（地価調査） | 財務局 | コスト | CSV | ◎ | 使用 |
| D-cost-03 | 土地利用現況調査GISデータ | 都市整備局 | コスト | SHP | ○ | 使用 |
| D-community-01 | 特定非営利活動法人（ＮＰＯ法人）情報 | 生活文化スポーツ局 | つながり | CSV | ◎ | 使用 |
| D-community-02 | 令和２年国勢調査による東京都の昼間人口 | 総務局 | つながり | CSV | ◎ | 使用 |
| D-common-01 | 公共施設一覧 | デジタルサービス局 | いきぬき/しごとば/つながり | CSV | ◎ | 使用 |
| D-common-02 | 東京都の人口（推計） | 総務局 | 共通（全指標の分母） | CSV | ◎ | 使用 |
| D-common-03 | 行政区域データ（国土数値情報 N03） | 国土交通省 | 共通/描画 | SHP | ◎ | 使用 |

## 2. 取得先

1データセットが複数ファイルからなるものがある。`key` は `datasets.py` の `Resource.key`、実体は `raw/<ID>/<保存名>` に置かれる。

| # | key | カタログ | 実ファイル |
|---|---|---|---|
| D-quiet-01 | stations | [t000009d2000000067](https://catalog.data.metro.tokyo.lg.jp/dataset/t000009d2000000067) | `.../taikikankyo5g/catalogdata/mast/130001_tokyo_airpollution_station_master.csv` |
| D-quiet-01 | pm25 | 〃 | `.../taikikankyo5g/catalogdata/data/130001_tokyo_airpollution_PM2.5.zip` |
| D-quiet-02 | h25 | [t000009d1900000003](https://catalog.data.metro.tokyo.lg.jp/dataset/t000009d1900000003) | `.../kankyo/vehicle/noise/H25/H25_kekka.csv` |
| D-quiet-02 | h24 | [t000009d1900000004](https://catalog.data.metro.tokyo.lg.jp/dataset/t000009d1900000004) | `.../kankyo/vehicle/noise/H24/H24_kekka.csv` |
| D-quiet-02 | h23 | [t000009d1900000005](https://catalog.data.metro.tokyo.lg.jp/dataset/t000009d1900000005) | `.../kankyo/vehicle/noise/H23/H23_kekka.csv` |
| D-quiet-02 | h22 | [t000009d1900000006](https://catalog.data.metro.tokyo.lg.jp/dataset/t000009d1900000006) | `.../kankyo/vehicle/noise/H22/H22_kekka2.csv`（この年度だけ `kekka2`） |
| D-quiet-02 | h21 | [t000009d1900000007](https://catalog.data.metro.tokyo.lg.jp/dataset/t000009d1900000007) | `.../kankyo/vehicle/noise/H21/H21_kekka.csv` |
| D-quiet-02 | h20 | [t000009d1900000008](https://catalog.data.metro.tokyo.lg.jp/dataset/t000009d1900000008) | `.../kankyo/vehicle/noise/H20/H20_kekka.csv` |
| D-refresh-01 | notice / parks / woods | [t000008d2000000024](https://catalog.data.metro.tokyo.lg.jp/dataset/t000008d2000000024) | `.../toshiseibi/green_chuui.pdf`、`01_kouenryokuchi.zip`、`03_jurinchi.zip` |
| D-refresh-02 | package | [t000055d0000000363](https://catalog.data.metro.tokyo.lg.jp/dataset/t000055d0000000363) | `.../api/3/action/package_show?id=t000055d0000000363` |
| D-refresh-03 | route / priority | [t000014d0000000026](https://catalog.data.metro.tokyo.lg.jp/dataset/t000014d0000000026) | `.../documents/d/kensetsu/000035730`、`.../content/000035729.zip` |
| D-workspace-01 | offices | [t000012d0000000019](https://catalog.data.metro.tokyo.lg.jp/dataset/t000012d0000000019) | `.../sangyouroudou/tokyo-telework2401.csv` |
| D-workspace-02 | centers | [t000021d2000000023](https://catalog.data.metro.tokyo.lg.jp/dataset/t000021d2000000023) | `.../kyouiku/R3/skshubetu_8.csv` |
| D-commute-01 | gtfs_bus / stations | [t000018d0000000052](https://catalog.data.metro.tokyo.lg.jp/dataset/t000018d0000000052) | `api-public.odpt.org/api/v4/files/Toei/data/ToeiBus-GTFS.zip`、`api-public.odpt.org/api/v4/odpt:Station?odpt:operator=odpt.Operator:Toei` |
| D-cost-01 | points | [t000004d0000000004](https://catalog.data.metro.tokyo.lg.jp/dataset/t000004d0000000004) | `.../documents/d/zaimu/12_R8kouji_chiten_opendata` |
| D-cost-02 | points | [t000004d0000000001](https://catalog.data.metro.tokyo.lg.jp/dataset/t000004d0000000001) | `.../kijun/R7nen/05-02_r7data_kakaku.csv` |
| D-cost-03 | kubu / tama | [t000008d2000000019](https://catalog.data.metro.tokyo.lg.jp/dataset/t000008d2000000019) | `.../toshiseibi/R03.zip`、`R04.zip` |
| D-community-01 | ninsyou | [t313360d0000000052](https://catalog.data.metro.tokyo.lg.jp/dataset/t313360d0000000052) | `.../npo_houjin/files/0000001246/ninsyou.csv` |
| D-community-02 | table1 | [t000003d0000000627](https://catalog.data.metro.tokyo.lg.jp/dataset/t000003d0000000627) | `.../tyukanj/2020/tj20zv0100.csv` |
| D-common-01 | facilities | [t000029d0000000030](https://catalog.data.metro.tokyo.lg.jp/dataset/t000029d0000000030) | `.../suisyoudataset/130001_public_facility.csv` |
| D-common-02 | population | [t000003d2000001136](https://catalog.data.metro.tokyo.lg.jp/dataset/t000003d2000001136) | `.../jsuikei/2026/js266v0000_1.csv` |
| D-common-03 | boundary | [国土数値情報 N03](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-v3_1.html) | `.../ksj/gml/data/N03/N03-2026/N03-20260101_13_GML.zip` |

## 3. データ構造

「自治体の特定」は、5桁の全国地方公共団体コードに解決する手段。
`コード列` はそのまま使える、`住所` / `自治体名` は `municipalities.py` で解決、`空間結合` は `spatial_join.py` で D-common-03 のポリゴンに落とす。

| # | 自治体の特定 | 文字コード | 年次・時点 | 構造 |
|---|---|---|---|---|
| D-quiet-01 | コード列（局マスタ） | CP932 | 直近50日・日次更新 | 局マスタCSV（ヘッダ行なし。局コード／局名／市区町村コード／緯度経度）と、1分値のZIP。月別ZIPは `…_PM2.5_YYYYMM.zip` で遡れる |
| D-quiet-02 | 住所（測定地点） | CP932 | 平成20〜25年度 | 1年度1CSV・1行1測定地点で約600地点。住所／緯度経度／道路名／道路種別／車線数／昼間・夜間の等価騒音レベル(Leq)。列名は年度で揺れる（「測定地点の住所」/「測定地点住所」など）。調査地点が年度ごとに入れ替わるため単年では欠測の自治体が出る。6年分で53自治体すべてが埋まる |
| D-refresh-01 | 空間結合 | — | 令和8年2月2日時点 | シェープファイル。公園・緑地等／樹林地など全18レイヤ。ZIP内は日本語ディレクトリ |
| D-refresh-02 | リソースURLのファイル名先頭5桁 | UTF-8 | — | CKANの `package_show` JSON。`resources[].url` のファイル名先頭6桁が団体コード |
| D-refresh-03 | 空間結合 | — | — | シェープファイル2種（自転車推奨ルート／優先整備区間） |
| D-workspace-01 | コード列（区市町村コード） | UTF-8 BOM | — | CSV。5桁コードが入るので空間結合は不要 |
| D-workspace-02 | 自治体名 / 緯度経度 | CP932 | — | CSV。区市町村名・施設名・所在地・緯度経度 |
| D-commute-01 | 空間結合 | UTF-8 | GTFS有効期間 2026-08-13〜2029-08-12 | GTFS-JPのZIP（9.1MB、展開後は stop_times.txt だけで95MB）と駅のJSON。stops.txt はポール3,692件と停留所1,674件が混在し、`parent_station` が空の行が停留所そのもの。駅JSONは路線ごとに1レコードで149件・実駅数141 |
| D-cost-01 | コード列（都道府県市区町村コード） | CP932 | 令和8年地価公示 | CSV。1行目が表題でヘッダは2行目。用途は「標準地番号（用途）」で区分し、住宅地は 0 |
| D-cost-02 | コード列（都道府県市区町村コード） | CP932 | 令和7年地価調査 | D-cost-01と同構造 |
| D-cost-03 | 空間結合 | — | 区部:令和3年 / 多摩・島しょ:令和4年 | シェープファイル。区部と多摩・島しょで別ファイル・別年次。2ファイル計約670MB |
| D-community-01 | 住所（主たる事務所） | CP932 | 月次更新 | CSV。1行目が表題、2行目がヘッダでセル内に改行が入る。認証NPO法人 約9,300件 |
| D-community-02 | コード列（地域コード） | UTF-8 BOM | 令和2年国勢調査 | CSV第1表。地域コード／昼間人口／常住人口／昼夜間人口比率／面積 |
| D-common-01 | 住所 / 緯度経度 | CP932 | — | 推奨データセット準拠のCSV。コード列は都のコードのみ、市区町村名列は空 |
| D-common-02 | コード列（地域コード） | UTF-8 BOM | 令和8年6月1日現在 | CSV。地域階層／地域コード／人口／面積(km2)／人口密度。月次更新でURLの年月部分が変わる |
| D-common-03 | 基準ポリゴンそのもの | — | 令和8年1月1日 | シェープファイル＋GeoJSON。ファイル名の `13` が東京都、`20260101` が年次 |