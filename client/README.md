# client

フロントエンド。技術選定は未定。

## 前提

- バックエンドなし。`data/processed/municipalities.json` を1本読むだけで動く。
- 重み付けの計算（総合スコア = Σ(軸スコア × 重み) / Σ(重み)）はクライアント側で完結させる。
  スライダー操作でサーバに問い合わせが発生しない設計にする。
- 欠損（`status: "no_data"`）は0として扱わず、地図上はハッチングで「データなし」と明示する。

## 入力データ

`data/processed/municipalities.json` のスキーマは [../data/README.md](../data/README.md) を参照。
スキーマ確認用のダミーデータは `cd ../data && make demo` で生成できる
（`data/processed/municipalities.sample.json`）。
