# src/ をimportパスに通し、サブパッケージをモジュールとして実行する
PY := PYTHONPATH=src uv run python

.PHONY: setup ingest normalize spatial-join score all demo datasets \
	inventory missing stats validate report lint test clean clean-all

setup:
	uv sync

## 生データを raw/ に取得
ingest:
	$(PY) -m pipeline.01-ingest

ingest-heavy:
	$(PY) -m pipeline.01-ingest --heavy

## raw/ → interim/（文字コード変換・自治体コード付与・単位統一）
normalize:
	$(PY) -m pipeline.normalize

## 点/線データを自治体ポリゴンに集約して interim/indicators/ に出力
spatial-join:
	$(PY) -m pipeline.spatial_join

## interim/ → processed/municipalities.json（ウィンザライズ → min-max → 軸スコア）
score:
	$(PY) -m pipeline.score

all: ingest normalize spatial-join score

## スキーマ確認用のダミーデータを生成（フロント開発の先行用）
demo:
	$(PY) -m pipeline.score --demo

## ---- 調査用（成果物の生成には関与しない） ----

## raw/ の棚卸し（ファイル一覧・文字コード・manifest との突き合わせ）
inventory:
	$(PY) -m analysis.raw_inventory

## 指標×自治体の欠損レポート
missing:
	$(PY) -m analysis.missing_report

## 指標ごとの分布・外れ値・ウィンザライズの影響
stats:
	$(PY) -m analysis.indicator_stats

## 出力JSONのスキーマ・値域・欠損表現を検証（エラーがあれば終了コード1）
validate:
	$(PY) -m analysis.validate_output

## 上記の結果を1枚のHTMLにまとめて analysis/report.html に書き出す
report:
	$(PY) -m analysis.report

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

test:
	uv run pytest

## 中間データのみ削除（raw/ は再取得が重いので残す）
clean:
	rm -rf interim/*
	touch interim/.gitkeep

clean-all: clean
	rm -rf raw/*
	touch raw/.gitkeep
