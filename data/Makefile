RUN := uv run python src

.PHONY: setup ingest normalize spatial-join score all demo datasets lint test clean clean-all

setup:
	uv sync

## 生データを raw/ に取得
ingest:
	$(RUN)/ingest.py

## raw/ → interim/（文字コード変換・自治体コード付与・単位統一）
normalize:
	$(RUN)/normalize.py

## 点/線データを自治体ポリゴンに集約して interim/indicators/ に出力
spatial-join:
	$(RUN)/spatial_join.py

## interim/ → processed/municipalities.json（ウィンザライズ → min-max → 軸スコア）
score:
	$(RUN)/score.py

all: ingest normalize spatial-join score

## スキーマ確認用のダミーデータを生成（フロント開発の先行用）
demo:
	$(RUN)/score.py --demo

## データセット定義の一覧と取得状況
datasets:
	$(RUN)/ingest.py --list

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
