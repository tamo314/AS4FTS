# AS4FTS 戦略単位の高速研究

1ループは「1戦略仮説 + 宣言した全パラメータ組合せ」です。
戦略を一度実装し、Pythonが全組合せを実行して結果を次の設計へ渡します。
通常ループに仮説承認・設計レビュー・全データ再監査・全テストを追加しません。
共通機能は共有ソースへ蓄積し、実験ごとの別実装を作り直しません。

## 1. ブランチと環境

既存のリポジトリのルートで実行します。CLIの再インストール・再ログインは不要です。

```powershell
git fetch origin
git switch feat/strategy-batch-research
git pull --ff-only origin feat/strategy-batch-research
uv sync --group dev
```

既存Python環境を使う場合は `python -m pip install -e .` とし、以降の `uv run python` をその環境の `python` に読み替えられます。
従来の `n225m-bt backtest run` は基準戦略用のままです。研究機能は `python -m n225m_bt.research` を使用します。

## 2. モデル名は設定ファイルで指定

初回だけサンプルをコピーします。既にあるローカル設定は上書きしません。

```powershell
if (!(Test-Path config/research_agents.local.yaml)) {
  Copy-Item config/research_agents.example.yaml config/research_agents.local.yaml
}
```

`config/research_agents.local.yaml` の次の2項目を編集します。
以下の文字列は実際に手元のCLIで使えるモデルIDに置き換えてください。

```yaml
roles:
  designer:
    model: "設計用モデルID"
    argv: [codex, exec, --sandbox, read-only, --model, '{model}', -o, '{output}', '-']
    stdin: true
    timeout_seconds: 600
  implementer:
    model: "実装用モデルID"
    argv: [claude, '-p', '{prompt}', --model, '{model}', --output-format, json]
    stdin: false
    timeout_seconds: 600
```

`{model}` に同じ役割の `model` を展開します。`AS4FTS_DESIGN_MODEL` / `AS4FTS_IMPLEMENT_MODEL` の設定コマンドは不要です。
サンプルの `model: null` または空文字では `--model {model}` 自体を省き、既存CLIのデフォルトモデルを使います。
高コスト・低コストを確実に分けるには両方に明示的なIDを指定してください。
`-m {model}` と `--model={model}` にも対応します。
旧 `argv` の `${AS4FTS_DESIGN_MODEL}` 等も、同じ役割に非空の `model` を追記すれば設定値を優先して使います。
旧環境変数方式も、明示的なモデル指定がない既存テンプレート向けに残しています。
要求したモデル名は各呼出しの `response.json` の `requested_model` に記録します。CLIが返す実際のモデル情報とは分けて扱います。

Antigravity等は、普段動いている非対話CLIまたはラッパーの `argv` に置き換えます。
`{prompt}` は1引数、`{output}` は出力先、`stdin: true` は標準入力でのプロンプト送信です。
プレーンJSON、JSONコードフェンス、result/structured_outputを含む応答に対応します。
この設定機構は各製品で利用できないモデルを利用可能にするものではありません。

## 3. 最初の候補を単独で試す（モデル呼出しなし）

初回候補は `examples/research/starter_breakout.yaml` です。
日中の確定終値が直前N本の高値を上回ったら次の有効足で買い、固定幅の損切り・利確または強制決済で終了します。
当該足を高値計算に含めず、セッションごとに履歴をリセットします。
既存 `range_breakout:create_strategy` と `rolling_range` / `tick_bracket` を再利用します。

| パラメータ | 値 |
|---|---|
| lookback | 3, 5 |
| stop_ticks | 2, 4 |
| target_ticks | 4, 8 |
| direction | longで固定 |
| execution.slippage_ticks | 0, 1 |

合計16ケースです。固定の手数料100円/片道は動作例であり、実際の証券会社の手数料を保証しません。
合成入力は動作確認用で、収益性の根拠ではありません。

```powershell
uv run python -m n225m_bt.research dataset-register demo --synthetic-days 3
uv run python -m n225m_bt.research run examples/research/starter_breakout.yaml --workers 2
```

正常時は `status: complete`、`planned: 16`、`successful: 16`、`failed: 0`、`remaining: 0` です。

## 4. ループ全体の配線を確認（外部モデル・実データ不要）

```powershell
uv run python scripts/check_research_loop.py
```

新規の `.research/smoke/starter-*/` 作業領域へ必要なソースだけをコピーして実行します。
元の共有ソース、ローカル設定、相場データには書込みを行いません。

実バックテストエンジンで、初回候補16ケース → 模擬設計CLI → 模擬実装CLI → 次の16ケースを実行します。
モデル名のYAML展開、全結果の次回設計への引継ぎ、共有factoryの発見、完了後の不要な再呼出し抑止を確認します。
成功は `ok: true`、失敗は非ゼロ終了です。ログと `check_result.json` は出力の `workspace` に残ります。
模擬CLIは固定JSONを返す試験用の役割です。実モデルの品質・CLI認証・実料金を確認するものではありません。
これは導入時の任意確認であり、通常の研究ループの事前条件ではありません。

## 5. 初回候補から実CLIによる研究を開始

サンプル設定の主要項目は次のとおりです。

```yaml
campaign_id: starter_research_v1
dataset: demo
initial_family: examples/research/starter_breakout.yaml
max_families: 2
workers: 2
```

既存のローカル設定には、この `initial_family` を追記してください。新しい開始には未使用の `campaign_id` を使います。
`max_families` は初回候補を含む総数です。
初回は用意済み戦略を再利用してバックテストへ直行するため、設計・実装モデルを呼びません。
2戦略目は初回の全パラメータ結果を設計モデルに渡し、必要なら実装モデルを呼んでから全組合せを実行します。
実装が不要な設計では `implementation_required: false` により実装呼出しを省けます。

```powershell
uv run python -m n225m_bt.research loop --config config/research_agents.local.yaml
```

初回候補の `dataset` はキャンペーンの `dataset` に合わせます。相対 `initial_family` はリポジトリルート基準です。
候補の内容は保存され、中断後はその保存済み仕様で再開します。`initial_family: null` なら最初からAIに設計させます。
`defaults.backtest` 等は仕様にないキーを補います。同じキーを仕様で明示した場合は仕様が優先されます。
特に初回候補の手数料・探索範囲を変える場合は、候補YAML内の明示値も確認してください。

同じ `campaign_id` での再実行は再開です。完了後は不要なモデル呼出しをしません。延長するには `max_families` を増やします。
各結果は `.research/campaigns/<campaign_id>/state.json` の `history` に残ります。
キャンペーンの `complete` だけでなく、各 `history[].summary.status` と `coverage`、失敗記録を確認してください。
実行不能なコードの限定修正は既定2回です。赤字を理由に同一試行でパラメータを利益が出るまで変更する指示はありません。

## 6. データの置き場：Goldは1分足、元ファイルはRaw

現在の取込・エンジンは **1分足専用** です。`data/gold` は「日足」の置き場ではありません。

```text
data/raw/225labo/center/       利用者が取得した元のXLSX・CSV等
data/raw/225labo/forward/      別系列の元データ
data/gold/year=YYYY/month=MM/bars.parquet
                             取込済み・正規化済み1分足
data/gold/forward/year=YYYY/month=MM/bars.parquet
                             別系列の正規化済み1分足
```

元のXLSX・CSVをGoldへ置くだけでは読めません。元ファイルはREADMEの `data inspect` / `data ingest` 手順で取込みます。
1日1本のOHLCである日足は、1分足向けの次足約定・セッション・時間計算にそのまま流せません。日足対応は今回追加していません。

既存Goldは一度だけ登録します。通常ループで再取込・品質再監査はしません。

```powershell
uv run python -m n225m_bt.research dataset-register center-v1 --gold-root data/gold --calendar config/local_calendar.yaml
uv run python -m n225m_bt.research dataset-register forward-v1 --gold-root data/gold/forward --calendar config/local_calendar.yaml
```

実データに合うカレンダーを指定し、キャンペーンの `dataset` を登録名に変更します。
対象は `year=*/month=*/*.parquet` のため、centerの読込にforwardを混在させません。
登録時に内容ハッシュとカレンダーを保存し、読込時はサイズ・更新時刻を確認します。完全な改ざん検知ではありません。
入力を更新するときは別のデータセット名で登録します。模擬チェックはローカル実データの存在や品質を確認しません。

## 7. 全空間の指定、再開と結果

固定値は `parameters`、候補値・上下限と刻みは `space`、約定条件は `backtest` / `backtest_space` に指定します。
`{start: 0.1, stop: 0.3, step: 0.1}` は0.1、0.2、0.3です。終点は刻みで到達するときに含みます。
`variants` は条件別空間の和集合、`constraints` は比較条件です。全実数ではなく宣言した有限集合の全有効組合せを実行します。
比較はeq/ne/lt/le/gt/ge/in/not_inに対応し、右側は `right` の値または `right_param` の参照で指定します。式のevalはしません。
条件内の約定キーは `bt.execution.slippage_ticks` のように参照します。重複組合せは一度だけ実行します。
複数の `periods` では期間ごとに戦略状態をリセットします。期間を越える学習やウォームアップは自動実行しません。
繰り返し結果を参照した期間は、未使用のホールドアウトと呼び続けないでください。

```powershell
uv run python -m n225m_bt.research plan examples/research/starter_breakout.yaml
uv run python -m n225m_bt.research run examples/research/starter_breakout.yaml --max-new-trials 5
uv run python -m n225m_bt.research run examples/research/starter_breakout.yaml --workers 2
```

`plan` は任意の件数表示で、承認工程ではありません。直接 `run` できます。
未実行が残れば `partial`、全試行成功は `complete`、全試行済みで失敗ありは `complete_with_failures` です。
同じ指定で残りを再開し、同じ条件の成功結果を再利用します。失敗の再試行は `--retry-failed` を使います。
探索範囲だけ拡張しても条件が同じ既存ケースは再利用します。コード変更は保守的にキャッシュを無効化します。
ケースごとに新しい戦略を生成し、各ワーカー内でデータを再利用します。ワーカー増加はメモリ使用量も増加させます。

結果は `.research/batches/<family_id>/<batch_id>/` に保存します。

| 出力 | 内容 |
|---|---|
| trials.csv / trials.json | 全試行のパラメータ・期間・約定条件・指標・失敗・キャッシュ使用 |
| summary.json / summary.md | 計画・試行・未実行件数と全体分布 |
| sensitivity.json | パラメータ別集計と2パラメータの交互作用の集計 |
| monthly.json / failures.json | ケース別月次損益と失敗情報 |
| runtime.json / dataset.json | 使用コード・依存環境・実行設定・入力識別情報 |
| source.zip / catalog.json | 再現用ソースと部品カタログのスナップショット |

取引台帳は `.research/cache/<trial_id>/trades.jsonl.gz` です。
最良値だけでなく赤字・取引ゼロ・失敗も残します。ドローダウンは実現損益ベース、損失取引がないPFはnullです。
集計は探索結果であり、過学習の問題が解消したことや収益性を意味しません。

## 8. 再利用と実行上の境界

`python -m n225m_bt.research catalog` で共有部品を確認できます。
共有機能は `components/`、戦略は `strategies/` に保存し、リテラルの `@component(id=..., kind=..., summary=..., tags=[...], uses=[...])` で発見します。
用途、呼出し方、docstring、コードハッシュ、利用ファミリーが設計・実装役に渡ります。登録承認や部品の自動一般化はありません。
`source.zip` は再現用であり、次の研究で別実装を作るための場所ではありません。

一つの作業ツリーではキャンペーンは直列、ケースは並列です。共有コードを複数キャンペーンで同時更新しないでください。
戦略は信頼されたローカルPythonとして実行し、この機能自体はOSサンドボックスではありません。
通常の例外はケース別に保存します。無限ループ等にはバッチタイムアウトを使用し、ケース別の強制タイムアウトは未実装です。
実コスト予算による停止、独立した学習・ウォークフォワード、含み損益評価は追加対象です。
実モデル・実相場データの確認範囲は `VALIDATION.md` と `STARTER_VALIDATION.md` を参照してください。
