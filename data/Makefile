# src/ をimportパスに通し、サブパッケージをモジュールとして実行する
PY := PYTHONPATH=src uv run python

.PHONY: setup ingest normalize spatial-join score all demo datasets lint test clean clean-all

setup:
	uv sync

## 生データを raw/ に取得
ingest:
	$(PY) -m pipeline.ingest

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

## データセット定義の一覧と取得状況
datasets:
	$(PY) -m pipeline.ingest --list

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
