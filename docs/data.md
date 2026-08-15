# 使用データ一覧（全8件）
## 1. 一覧

判定は利用可否。◎ カタログ掲載でそのまま使える ／ ○ カタログ掲載だが個別条件あり ／ △ 都庁以外の自治体データで個別確認が要る。
判定の根拠と個別条件の中身は [data_license_check.md](./data_license_check.md) の3節にある。

| # | データセット名称 | 出所 | 用途 | 形式 | 判定 | 状態 |
|---|---|---|---|---|---|---|
| D-quiet-01 | PM2.5(微小粒子状物質)モニタリングデータ(1分値) | 環境局 | しずけさ | CSV/ZIP | ◎ | 使用 |
| D-quiet-02 | 自動車交通騒音調査結果 | 環境局 | しずけさ | CSV | ◎ | 使用（平成20〜25年度の6年分） |
| D-refresh-01 | 緑のオープンデータ（GISデータ） | 都市整備局 | いきぬき | SHP | ○ | 使用 |
| D-workspace-01 | 「TOKYOテレワークアプリ」掲載サテライトオフィス一覧データ | 産業労働局 | しごとば | CSV | ◎ | 使用 |
| D-cost-01 | 地価公示（東京都分） | 財務局 | コスト | CSV | ◎ | 使用 | 
| D-community-01 | 特定非営利活動法人（ＮＰＯ法人）情報 | 生活文化スポーツ局 | つながり | CSV | ◎ | 使用 |
| D-common-01 | 東京都の人口（推計） | 総務局 | 共通（全指標の分母） | CSV | ◎ | 使用 |
| D-common-02 | 行政区域データ（国土数値情報 N03） | 国土交通省 | 共通/描画 | SHP | ◎ | 使用 |

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
| D-workspace-01 | offices | [t000012d0000000019](https://catalog.data.metro.tokyo.lg.jp/dataset/t000012d0000000019) | `.../sangyouroudou/tokyo-telework2401.csv` |
| D-cost-01 | points | [t000004d0000000004](https://catalog.data.metro.tokyo.lg.jp/dataset/t000004d0000000004) | `.../documents/d/zaimu/12_R8kouji_chiten_opendata` |
| D-community-01 | ninsyou | [t313360d0000000052](https://catalog.data.metro.tokyo.lg.jp/dataset/t313360d0000000052) | `.../npo_houjin/files/0000001246/ninsyou.csv` |
| D-common-01 | population | [t000003d2000001136](https://catalog.data.metro.tokyo.lg.jp/dataset/t000003d2000001136) | `.../jsuikei/2026/js266v0000_1.csv` |
| D-common-02 | boundary | [国土数値情報 N03](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-v3_1.html) | `.../ksj/gml/data/N03/N03-2026/N03-20260101_13_GML.zip` |

## 3. データ構造

「自治体の特定」は、5桁の全国地方公共団体コードに解決する手段。
`コード列` はそのまま使える、`住所` / `自治体名` は `municipalities.py` で解決、`空間結合` は `spatial_join.py` で D-common-02 のポリゴンに落とす。

| # | 自治体の特定 | 文字コード | 年次・時点 | 構造 |
|---|---|---|---|---|
| D-quiet-01 | コード列（局マスタ） | CP932 | 直近50日・日次更新 | 局マスタCSV（ヘッダ行なし。局コード／局名／市区町村コード／緯度経度）と、1分値のZIP。月別ZIPは `…_PM2.5_YYYYMM.zip` で遡れる |
| D-quiet-02 | 住所（測定地点） | CP932 | 平成20〜25年度 | 1年度1CSV・1行1測定地点で約600地点。住所／緯度経度／道路名／道路種別／車線数／昼間・夜間の等価騒音レベル(Leq)。列名は年度で揺れる（「測定地点の住所」/「測定地点住所」など）。調査地点が年度ごとに入れ替わるため単年では欠測の自治体が出る。6年分で53自治体すべてが埋まる |
| D-refresh-01 | 空間結合 | — | 令和8年2月2日時点 | シェープファイル17レイヤ（公園・緑地等14＋樹林地3、うち1つは点データ）。ZIP内は日本語ディレクトリ。座標系は EPSG:6677 で単位はメートル。樹林地は市街地の樹林のみで山林を含まない。属性の「面積m2」は調書ベースの数値でポリゴン面積と乖離し、欠損は -9999 |
| D-workspace-01 | コード列（区市町村コード） | UTF-8 BOM | — | CSV。5桁コードが入るので空間結合は不要 |
| D-cost-01 | コード列（都道府県市区町村コード） | CP932 | 令和8年地価公示 | CSV。1行目が表題でヘッダは2行目。用途は「標準地番号（用途）」で区分し、住宅地は 0 |
| D-community-01 | 住所（主たる事務所） | CP932 | 月次更新 | CSV。1行目が表題、2行目がヘッダでセル内に改行が入る。認証NPO法人 約9,300件 |
| D-common-01 | コード列（地域コード） | UTF-8 BOM | 令和8年6月1日現在 | CSV。地域階層／地域コード／人口／面積(km2)／人口密度。月次更新でURLの年月部分が変わる |
| D-common-02 | 基準ポリゴンそのもの | — | 令和8年1月1日 | シェープファイル＋GeoJSON。ファイル名の `13` が東京都、`20260101` が年次 |