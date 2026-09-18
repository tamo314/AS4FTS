# AS4FTS 戦略単位の高速研究

## この変更の実行単位

1回の研究ループは、1つの戦略仮説と、その仮説について宣言した全パラメータ組合せです。
高コストモデルが仮説・設計・有限の探索範囲をまとめ、低コストモデルがパラメータ化された戦略を一度実装し、Pythonが全ケースを実行します。
結果取得前の仮説承認、設計レビュー、全データ再監査は通常ループにありません。

コードは共有ソースへ追加します。実行ごとのsource.zipは再現用スナップショットであり、次の研究用に別実装を作り直すためのものではありません。

## 1. ブランチとPython環境

既存のローカルリポジトリから実行します。

```powershell
git fetch origin
git switch feat/strategy-batch-research
uv sync --group dev
```

既にPython環境を管理している場合は、対応Pythonで `python -m pip install -e .` を実行しても構いません。
以下の `uv run python` は、その環境の `python` に読み替えられます。
各AI CLIのインストール・ログインをやり直す処理はありません。
既存 `n225m-bt backtest run` は従来の基準戦略用のままです。新しい研究機能には `python -m n225m_bt.research` を使用してください。

## 2. 相場データを使わない動作確認

```powershell
uv run python -m n225m_bt.research dataset-register demo --synthetic-days 3
uv run python -m n225m_bt.research plan examples/research/breakout.yaml
uv run python -m n225m_bt.research run examples/research/breakout.yaml --workers 2
```

付属例は、lookback 3通り × stop 2通り × target 2通り × direction 2通り × slippage 2通り = 48ケースです。
`plan` は組合せ数を表示する任意コマンドで、承認工程ではありません。直接 `run` できます。
合成価格は配線確認専用です。成績を投資判断や戦略有効性の根拠に使わないでください。

## 3. 既存Goldデータを一度だけ登録

```powershell
uv run python -m n225m_bt.research dataset-register center-v1 --gold-root data/gold --calendar config/local_calendar.yaml
uv run python -m n225m_bt.research dataset-register forward-v1 --gold-root data/gold/forward --calendar config/local_calendar.yaml
```

登録は既存Goldを読み替える参照表の作成で、再取込・品質再監査は実行しません。
`year=*/month=*/*.parquet` のファイルだけを対象にするため、centerの読込に配下のforwardを混在させません。
ファイル内容ハッシュは登録時に一度計算します。カレンダー内容も登録情報に保存します。
各バッチの読込時はサイズ・更新時刻を確認します。同じサイズと更新時刻に偽装された変更を検出する完全な改ざん検知ではありません。
登録したファイルを更新する場合は、新しいデータセット名で登録してください。
夜間データでは実データに合うカレンダーを指定してください。カレンダーの再生成は研究ループに含みません。

戦略仕様の `dataset: demo` を `dataset: center-v1` に変更すれば、同じ戦略実装を実データに使用できます。
データ名の変更は別の実験入力となり、合成データの結果は再利用されません。

## 4. 戦略仕様と探索空間

```yaml
family_id: breakout_family_001
hypothesis: "過去レンジ突破後の継続を、コストとパラメータ領域全体で検証する"
factory: n225m_bt.strategies.range_breakout:create_strategy
dataset: center-v1
seed: 314
uses: [rolling_range, tick_bracket]
space:
  lookback: [3, 5, 8]
  stop_ticks: {start: 2, stop: 4, step: 2}
  target_ticks: [4, 8]
  direction: [long, short]
backtest:
  mode: day_only
  fees.jpy_per_side_per_contract: 100
backtest_space:
  execution.slippage_ticks: [0, 1]
constraints:
  - {left: target_ticks, op: ge, right_param: stop_ticks}
periods:
  explore:
    start: '2021-01-01'
    end: '2024-12-31'
```

金額・期間は書式例です。手数料は利用条件に合わせて指定します。探索期間の指定は、その全期間のデータが存在することを保証しません。
固定値は `parameters`、変化させる値は `space` です。約定やコスト条件は `backtest` と `backtest_space` に分けます。

範囲の終点は、刻みで到達できる場合に含みます。例えば0.1〜0.3を0.1刻みなら0.1、0.2、0.3です。
「全パラメータ」は、設計時に指定した値・上下限・刻み・条件から定まる有限集合の全有効組合せを意味します。
連続値の全実数や、仕様に書かれていない範囲まで試したとは扱いません。

`variants` は条件別空間の和集合です。例えば固定出口と別の出口で異なるパラメータを持たせられます。
各variantは `parameters`、`space`、`backtest`、`backtest_space` を上書きでき、重複する組合せは一度だけ実行します。
`constraints` は `left`、`op`、`right` または `right_param` の比較で指定し、式のevalは使用しません。
比較演算はeq/ne/lt/le/gt/ge/in/not_in、約定側キーは `bt.execution.slippage_ticks` のように参照します。

複数の `periods` を指定した場合は、各組合せを各期間で実行し、期間を分けて出力します。
各期間は戦略の状態をリセットして開始します。期間を越えたウォームアップや学習の自動処理は含みません。
繰り返し参照した検証期間は既知の期間です。独立したホールドアウトとして扱い続けないでください。

## 5. 全組合せの実行・中断再開

```powershell
uv run python -m n225m_bt.research run examples/research/breakout.yaml --workers 2
# リソース都合で新規実行を5ケースだけに制限すると、明示的にpartialになる
uv run python -m n225m_bt.research run examples/research/breakout.yaml --max-new-trials 5
# 同じ指定を再実行すると、記録済みの成功ケースを再利用し、残りを実行する
uv run python -m n225m_bt.research run examples/research/breakout.yaml --workers 2
# 同じソースのまま失敗ケースを再試行するときだけ指定
uv run python -m n225m_bt.research run examples/research/breakout.yaml --retry-failed
```

ケースごとに新しい戦略インスタンスを生成します。状態のある戦略を組合せ間で使い回しません。
各ワーカーは入力データを読み込み、一つのファミリー内で再利用します。大きいデータではワーカー数に比例してメモリ使用量も増えます。
データ・コード・設定・期間・パラメータが同じなら既存結果を再利用します。探索空間だけ拡張した場合も、条件が同じ既存ケースは再実行しません。
コード変更時は保守的にキャッシュを無効化します。無関係な共有Pythonファイルの追加でも現在の実装では再計算対象になる場合があります。

`complete` は全ケース成功、`complete_with_failures` は全ケースを試行したが実行失敗を含む状態です。
`partial` は未実行ケースが残る状態です。途中打切りを全空間完了として扱ったり、無断でサンプリングしたりしません。
通常の非ゼロ終了や例外はケース別に保存し、他のケースの実行を続けます。
無限ループ等のプロセス停止にはキャンペーンのバッチタイムアウトを使用します。ケース単位の強制タイムアウトは未実装です。

## 6. 結果をパラメータ別・領域別に読む

結果は `.research/batches/<family_id>/<batch_id>/` です。

| ファイル | 内容 |
|---|---|
| `trials.csv` / `trials.json` | 全試行のパラメータ、期間、約定条件、成功/失敗、指標、キャッシュ利用、エラー |
| `summary.json` / `summary.md` | 計画件数・試行件数・未実行数、全体分布、パラメータ別集計 |
| `sensitivity.json` | 1パラメータ別集計と2パラメータの組合せ別集計 |
| `monthly.json` | ケース別の月次実現損益 |
| `failures.json` | 失敗ケースとエラー |
| `runtime.json` / `dataset.json` | コード・依存環境・実行設定・入力識別情報 |
| `source.zip` / `catalog.json` | 実行時ソースと共有部品のスナップショット |
| `progress.json` | 途中経過 |

各ケースの取引台帳は `.research/cache/<trial_id>/trades.jsonl.gz` に保存します。
最高利益のケースだけでなく、失敗・損失・取引ゼロも残します。平均、中央値、最小/最大、プラスの割合を併記します。
ドローダウンは実現損益ベースです。含み損益込みではありません。損失取引がない場合のPFは未定義(null)とします。
全体・単変量集計は探索結果の要約であって、交互作用や過学習の問題が解決したという意味ではありません。

## 7. 再利用できる部品を蓄積する

```powershell
uv run python -m n225m_bt.research catalog
```

共有機能は `src/n225m_bt/components/`、戦略は `src/n225m_bt/strategies/` に保存します。
`@component(id=..., kind=..., summary=..., tags=[...], uses=[...])` のリテラルメタデータを付けると、コードをimportせずASTで発見します。
カタログには用途、呼出しシグネチャ、docstring、コードハッシュ、利用したファミリーが入り、設計役・実装役へ自動で渡されます。
戦略の `uses` に共有部品IDを書いて利用履歴を残します。部品登録の承認や自動審査はありません。

付属部品は `RollingRange`、`RollingMean`、`tick_bracket` です。付属戦略 `RangeBreakout` が組合せ利用の例です。
既存factoryをそのまま使える設計では `implementation_required: false` により実装モデルの起動自体を省けます。
部品の自動一般化・重複コード検出まで保証する機構ではありません。共有化はエージェントの実装とカタログ参照によって行います。

## 8. 構成済みCLIを使った自動ループ

```powershell
Copy-Item config/research_agents.example.yaml config/research_agents.local.yaml
# この2変数は、手元のCLIで利用できる実際のモデルIDに設定
$env:AS4FTS_DESIGN_MODEL = '<高コスト側モデルID>'
$env:AS4FTS_IMPLEMENT_MODEL = '<低コスト側モデルID>'
uv run python -m n225m_bt.research loop --config config/research_agents.local.yaml
```

ローカル設定の `dataset`、研究目的、期間、コスト、ファミリー数、CLIコマンドを環境に合わせます。
例はCodexを設計、Claude Codeを実装に割り当てますが、役割は固定されていません。
Antigravityを含む既存CLIは、同じ `argv` 配列契約で接続できます。普段動作している非対話コマンドまたはラッパーを設定してください。
`{prompt}` は1引数に展開、`{output}` は出力先、`stdin: true` ならプロンプトを標準入力から渡します。
プレーンJSON、JSONコードフェンス、result/structured_outputを含むJSON応答に対応します。
独自の出力包み形式を持つCLIには、最終JSONを出す小さな既存ラッパーを使用できます。モデル名・実行ファイル名はコードに固定しません。

中断後は同じ `campaign_id` と設定で `loop` を再実行します。保存された段階から再開します。
完了済みキャンペーンを延長するときは `max_families` を増やします。
バックテストの部分実行中は新しい仮説へ進まず、同じファミリーを再開します。
実行エラーの修正は既定2回までです。経済ルールやパラメータを利益が出るまで同一試行内で書き換えることは指示しません。
結果の解釈と次の仮説立案は、次回の設計モデル呼出しにまとめます。CLIが返さない費用は不明として記録し、ゼロ円としません。

## 現段階の境界

- 一つの作業ツリーに対するキャンペーンは直列です。ケースは並列ですが、複数キャンペーンによる共有コード同時更新は行わないでください。
- 戦略は信頼されたローカルPythonコードとして実行します。この機能はOSサンドボックスではありません。CLIの既存権限と環境分離を使用してください。
- 相場データと認証情報を含む `.research/`、ローカル設定、`.env` はGit対象外です。
- 実行時の構造的な不具合や不正な入力を利益評価として扱いません。基盤の大規模改修は研究ループから分離してください。
- 共有機能の蓄積と全パラメータ評価を優先した初期実装です。独立した学習/最適化/ウォークフォワード自動実行、含み損益評価、実コスト予算による停止は追加対象です。
- 実モデル呼出し・実相場データ・既存全体テストの検証範囲は `VALIDATION.md` を参照してください。
