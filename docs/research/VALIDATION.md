# 実装時の検証記録

## 実行した確認

実装用環境のPython 3.13.5で、新規 `tests/test_research_*.py` を実行しました。

```text
31 passed, 1 skipped
```

確認対象:
- 刻み付き範囲、小数の安定した展開、条件付きvariants、重複除外、全組合せ列挙。
- 共有RollingRange/RollingMean/tick_bracket、コードを実行しないカタログ生成。
- 合成データによる48ケース全実行、パラメータ別CSV/JSON、取引台帳との損益一致。
- 5ケースでの中断と残り43ケースの再開、探索範囲拡張時の既存48ケース再利用。
- 不正なパラメータのケースだけ失敗として保存し、他のケースを継続する処理。
- 共有ソース変更時の再計算、複数期間の区別。
- データ末尾決済の実現損益整合、最終有効足の利用、新規禁止時刻後の手仕舞いシグナル。
- データ登録時のcenter/forward分離、入力記述の不整合検出。
- JSON形式別のCLI応答処理、コマンド呼出しの再利用、プロセスタイムアウト。
- 模擬CLIによる2戦略ファミリー連続実行、追加部品が次回設計カタログへ渡ること、完了キャンペーンの不要な再呼出し抑止。

別途、3日分の合成入力を登録してコマンドラインから48ケースを実行しました。

```text
planned=48 attempted=48 successful=48 failed=0 remaining=0
status=complete
```

これは処理機構の確認であり、収益性の実証ではありません。

## 未確認の範囲

実装用環境にはPolars/PyArrowがなく、ネットワーク制限で追加インストールできなかったため、実Parquet読込の統合テスト1件を明示的にskipしました。
既存の依存環境を持つ利用者側では `uv run pytest tests/test_research_datasets.py` で該当テストを実行できます。

新規機能の検証では、取得した既存のドメイン・設定・カレンダー・約定処理に新規研究モジュールを接続しています。
リポジトリ全体の元からあるpytest、Ruff、mypyは今回実行していません。全CI合格とは主張しません。

ユーザーの認証済みCodex/Claude Code/Antigravity環境や実相場データには接続していません。
外部モデルを呼ばず、同じ標準入力/標準出力の契約を使う模擬CLIでオーケストレーションを確認しました。
Windowsでの実CLI起動、実料金、年単位の実データ性能は未計測です。

## 利用者環境での任意確認コマンド

```powershell
uv sync --group dev
uv run pytest tests/test_research_space.py tests/test_research_components.py tests/test_research_datasets.py tests/test_research_runner.py tests/test_research_agents.py
uv run python -m n225m_bt.research dataset-register demo --synthetic-days 3
uv run python -m n225m_bt.research run examples/research/breakout.yaml --workers 2
```

これらは導入時・基盤変更時の確認です。通常の戦略研究で毎回の全テスト・データ監査を前提にするものではありません。
