# YAMLモデル指定・初回候補の確認記録

## 今回実行した確認

Python 3.13.5で、GitHubから取得した実行に必要な既存モジュールへ今回の変更を適用して確認しました。
この記録は追加機能の確認であり、リポジトリ全体のCI合格ではありません。

```text
pytest -q tests/test_research_starter.py
21 passed
```

確認対象は、YAMLのmodel指定、null時のCLIデフォルト使用、旧テンプレート互換、モデル変更時の応答キャッシュ切替え、
プロンプト内の置換文字を再解釈しないこと、初回候補16ケース、初回のモデル呼出し省略、キャンペーンのデータ指定、
設定デフォルトの保持、中断後の同一仕様再開、次回設計への結果引継ぎ、共有部品の発見です。

初回候補単独の合成データ実行結果:

```text
planned=16 attempted=16 successful=16 failed=0 remaining=0
status=complete
```

`python scripts/check_research_loop.py` も実行し、次を確認しました。

```text
ok=true
family 1: planned=16 successful=16 failed=0 remaining=0
family 2: planned=16 successful=16 failed=0 remaining=0
one_design_one_implementation=true
models_from_yaml=true
previous_results_reach_design=true
shared_factory_discovered=true
completed_resume_has_no_new_calls=true
live_model_calls=0
```

バックテストは実際のエンジンです。データは合成、設計・実装役だけが固定JSONを返す模擬CLIです。
初回候補は既存のrange_breakout実装を再利用し、再実装していません。
確認用スクリプトは別作業領域へコピーして動き、元の共有コード・実データ・ローカル設定を変更しません。

## 未確認の範囲

利用者の認証済みCLI、実モデル、実料金、Windowsでの実CLI起動には接続していません。
この環境ではPolars/PyArrowを利用できず、実Parquet・実相場データの読込は今回実行していません。
リポジトリ全体の既存テスト・Ruff・mypyも今回の確認範囲には含みません。
合成データ上の実行成功は収益性の証明ではありません。

これらのテストは導入時・基盤変更時の任意確認です。各研究ループの事前ゲートにはしません。
