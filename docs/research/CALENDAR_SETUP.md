# カレンダーの自動作成：既存Goldがある場合

日付を手入力する必要はありません。旧システムの別形式カレンダーは使用せず、
配置した正規化済み1分足GoldからAS4FTS形式のYAMLを一度生成します。
価格の再計算、Rawの再取込、OHLCの全品質監査、AIの呼出しは行いません。

## 1. 最新コードを取得

```powershell
git fetch origin
git switch feat/strategy-batch-research
git pull --ff-only origin feat/strategy-batch-research
```

## 2. 配置済みGoldから生成

リポジトリルートで実行します。centerとforwardを両方配置している場合:

```powershell
uv run python -m n225m_bt.calendar.gold --gold-root data/gold --gold-root data/gold/forward --output config/local_calendar_as4fts.yaml
```

各rootの `year=*/month=*/*.parquet` だけを対象にします。center配下のforwardを
暗黙に重複読込しません。片方しかない場合は、そのrootだけを指定します。
既定の時間制度は `config/sessions.yaml` です。変更時は `--sessions` で指定できます。

生成物:
- `config/local_calendar_as4fts.yaml`: `trading_days` 形式のカレンダー。
- `config/local_calendar_as4fts.summary.json`: 日数、夜間対応の根拠、注意事項。

読み込む列は `trade_date`、`session`、`ts_jst` の3列のみです。
パーティションごとに日付・セッション単位へ集約するため、全OHLCをPythonの足配列にはしません。
`ts_jst` はタイムゾーン付きDatetime、`session` は `day` または `night` が前提です。
これらは既存研究ランナーが用いる標準Goldの列です。
生成した小さなYAMLは既存ローダーで読めることを確認してから出力を置き換えます。
旧カレンダーのファイル形式を手修正する必要はありません。

## 3. 新しいカレンダーでデータ登録

旧カレンダーはcenter-v1等の登録情報に内容が保存されています。元ファイルを直すだけでは反映されません。
新しい未使用の登録名を使用します。Goldそのものの再生成は不要です。

```powershell
uv run python -m n225m_bt.research dataset-register center-auto-v1 --gold-root data/gold --calendar config/local_calendar_as4fts.yaml
uv run python -m n225m_bt.research dataset-register forward-auto-v1 --gold-root data/gold/forward --calendar config/local_calendar_as4fts.yaml
```

登録では既存処理により入力ハッシュを一度計算します。価格の正規化や品質監査をやり直すわけではありません。
既存の登録JSONの直接編集・削除は不要です。

## 4. 研究を開始

`config/research_agents.local.yaml` の該当する項目だけ変更します:

```yaml
campaign_id: starter_research_auto_v1
dataset: center-auto-v1
initial_family: examples/research/starter_breakout.yaml
```

解決済みのCLIパスとモデル指定は変更しません。上記campaign_idが既に使われている場合は未使用のIDを選びます。

```powershell
uv run python -m n225m_bt.research loop --config config/research_agents.local.yaml
```

旧キャンペーンのcompleteは全成功を意味しない現行挙動があるため、失敗済みキャンペーンを今回の再開始に再利用しません。
この変更はキャンペーン状態機械やCLIの起動処理を修正するものではありません。
カレンダー生成とデータ登録は準備時だけです。戦略ごとに繰り返しません。

## 自動生成の根拠と限界

- 夜間の夕方部分がGoldにあれば、その実際の暦日を開始日に採用します。
  取引日から単純に1日引く処理ではありません。最初の取引日でも夕方データがあれば対応できます。
- 朝の夜間データしかない場合は、その実際の暦日の前日を候補にし、当日の夜間時刻制度と照合します。
  これは観測された午前時刻からの推定であり、報告の `morning_only_inferred_mappings` に分けて記録します。
- 日中足しかない取引日は夜間開始日を空欄にします。存在しない夜間や休日を補完しません。
- 前後の取引日は、入力に存在する取引日の前後関係です。欠落した取引日は分かりません。
- 公式取引所カレンダーを取得・認証する機能ではありません。
  休日取引の有無はGoldの3列だけでは確定できません。既存スキーマで必須の
  `is_holiday_trading_day` は互換用にfalseを出力し、`source_note` と集計ではunknownと明記します。
- 夕方の観測と午前時刻からの推定が食い違う場合、夕方を保持して警告に残します。
  複数の異なる夕方開始日が同じ取引日に対応してしまう場合は、一意に変換できないため具体的な日付を表示します。
- この機能は旧Goldの `trade_date` や `ts_jst` 自体の意味を修正しません。
  旧システムの時刻意味や標準列が異なる場合は、その取込仕様に合わせた変換が別途必要です。

## 元のXLSX・CSVしかない場合：既存コマンド

元ファイルは `data/raw/225labo/center/`、別系列は `data/raw/225labo/forward/` に置きます。
両方のディレクトリが存在する場合、次の既存コマンドで日付列から生成できます:

```powershell
uv run n225m-bt data build-calendar --source-root data/raw/225labo/center --source-root data/raw/225labo/forward --output config/local_calendar_as4fts.yaml
```

CSV・TXT・ZIP・XLSXの入力に対応する既存機能です。元ファイルの日付表現や列対応は `config/data.yaml` に従います。
日付集合から前の観測取引日を推定する方式なので、対象全期間を含む入力を渡します。
先頭日の前の取引日がない場合、その先頭日の夜間対応はこの方式だけでは分かりません。
今回のようにGoldが既にある場合は、上記のGoldからの生成方法を利用してください。
新規取込時は、生成カレンダーを `n225m-bt data ingest ... --calendar-override ...` に渡して正規化します。

## 今回の実装確認

Python 3.13.5で対象テストを実行: **20 passed, 2 skipped**。
対応ロジック、週末、制度変更境界、午前のみ、日中のみ、重複系列、競合の通知、
既存カレンダーローダーとの往復、元ファイル不変、コマンドのhelpを確認しました。
依存する既存config/domain/calendarモジュールは、取得したGitHub blob SHAとの一致も確認しました。

実装環境にはPolarsがなく追加導入もできなかったため、実Parquetの2テストはskipです。
利用者の実Gold・Windows環境で実行済みとは主張しません。全リポジトリのテストやlintも実行していません。

```powershell
uv run pytest tests/test_calendar_from_gold.py
```

これは導入時の任意確認であり、通常の研究ループの事前ゲートではありません。
