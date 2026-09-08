# RemoteLife Tokyo

東京都のオープンデータをもとに、**リモートワークのしやすさ**で都内53市区町村（23区・多摩地域）を比較できる可視化地図サービスです。

[都知事杯オープンデータ・ハッカソン2026](https://odhackathon.metro.tokyo.lg.jp/) 応募作品（チーム: Metropolitan(s)）。

- デモ: https://tiny-surf-65f3.syut-htnk-dev.workers.dev/

## 背景と解決方法

コロナ期を境にリモートワークが定着した一方で、リモートワーカーには通勤前提の働き方にはなかった悩みがあります。日中も家にいるため近隣の騒音が仕事に響く、人と会う機会が減って孤独を感じる、仕事とプライベートを切り替える場所がない、といったものです。これらは働き方の問題として語られがちですが、静けさも、家の外で作業できる場所も、人とつながる機会も、住む地域によって大きく異なります。

その差を示すデータは東京都のオープンデータとして公開されているものの、自治体ごとに形式も粒度も異なる状態で散らばっており、地域を横並びで比べられる形にはなっていません。本プロジェクトは、それらを正規化・統合して人口・面積ベースの0〜100スコアに揃え、地図の色分けとランキングで比較できるようにしました。

## 5つの軸

| 軸 | 内容 |
| --- | --- |
| しずけさ | 自動車交通騒音 |
| いきぬき | 緑・水辺、公園、PM2.5 |
| しごとば | サテライトオフィス、図書館 |
| くらしのコスト | 地価公示 |
| つながり | NPO法人、社会教育事業 |

「何を重視するか」は人それぞれ異なるため、各軸の重みはスライダーで変更できます（「静かさ重視」「コスト重視」など）。自治体を選べば、スコアの根拠になった指標の実数値と出典まで確認できます。

## 技術構成

**バックエンドを持たない構成**です。データ加工はオフラインのPythonパイプラインで行い、フロントは生成済みのJSONを1本読むだけで動きます。重みの再計算は通信なしでブラウザ内に閉じます。

- データ加工: Python（pandas / GeoPandas）。CSVとShapefileの両形式を扱い、Shapefileは空間結合で点・線・面を自治体区域に集計
- フロント: Next.js（静的エクスポート）/ TypeScript / Tailwind CSS
- 地図: GeoJSON を SVG で描画（APIキー不要・軽量）

```
原データ ──(01-ingest)──▶ raw/ ──(02-normalize, 03-spatial_join, 04-impute)──▶ interim/ ──(05-score)──▶ processed/municipalities.json ──▶ client
```

欠損は0で埋めず `status: "no_data"` として保持し、地図上はハッチングで「データなし」と明示します。規則にもとづく補完値は `status: "imputed"` で実測値と区別します。

## リポジトリ構成

| ディレクトリ | 内容 |
| --- | --- |
| [data/](data/) | データ取得〜スコア化のパイプライン（[README](data/README.md)） |
| [client/app/](client/app/) | Next.js フロントエンド（[README](client/README.md)） |
| [docs/](docs/) | 仕様・データ出典・ライセンス確認（[submit.md](docs/submit.md)） |

## 開発

```bash
# データパイプライン（processed/municipalities.json を生成）
cd data
uv sync
make all

# フロントエンド
cd client/app
npm install
npm run dev     # http://localhost:3000
```

## 利用オープンデータ

東京都オープンデータカタログサイト 9件、国土数値情報 2件の計11件を利用しています。出典の一覧は [docs/submit.md](docs/submit.md#4-1-利用データ一覧)、定義は [data/src/defs/datasets.py](data/src/defs/datasets.py) を参照してください。

## ライセンス

[MIT License](LICENSE)
