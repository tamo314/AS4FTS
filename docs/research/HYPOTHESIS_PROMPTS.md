# H01〜H06 初期仮説プロンプトとAntigravity implementer

## 今回追加したもの

戦略コードそのものではなく、前回提案した6仮説をそのまま設計役へ渡すプロンプトを登録しました。
各ファイルに仮説、売買ルール、全探索範囲、共通部品への分解、JSON出力契約、結果の読み方があります。
未実装の共有部品名は候補であり、既存と偽って再利用しないよう明記しています。

| ID | objective_file（prompts/research/hypotheses/配下） | 1期間・1データセットの全件数 |
|---|---|---:|
| H01 | H01_opening_range_breakout.md | 288 |
| H02 | H02_opening_range_failure.md | 432 |
| H03 | H03_compression_breakout.md | 288 |
| H04 | H04_impulse_pullback.md | 288 |
| H05 | H05_night_day_response.md | 432 |
| H06 | H06_preclose_response.md | 432 |

合計2160ケース。買い/売り専用と0/1/2ティックのコスト比較を含みます。
H05だけは夜間も観測するためfull_session、ただし新規売買は日中のみ。他はday_onlyです。
サンプリングや設計承認は追加していません。丸め、期限、シグナル回数の数え方など、実装に必要な曖昧さは本文で固定しています。
今回これらの戦略のコード生成・実相場バックテストを実施したという意味ではありません。

## 既存ローカル設定で選ぶ

既に確認済みのCLIパス・モデル・データ登録名は保持します。ローカル設定全体をサンプルで上書きしないでください。

```yaml
campaign_id: h01_agy_v1
dataset: center-auto-v1  # 自分の登録済み名を保持
initial_family: null
objective: "選択した初期仮説を一度実装し、宣言した全パラメータを実行する。"
objective_file: prompts/research/hypotheses/H01_opening_range_breakout.md
max_families: 1
```

`initial_family: null`が重要です。starter_breakout.yamlが残っていると初回はその既存戦略が優先され、新しい設計を呼びません。
`max_families: 1`は「1ケース」ではなく「H01全288ケース」を意味します。

```powershell
git fetch origin
git switch feat/strategy-batch-research
git pull --ff-only origin feat/strategy-batch-research
uv run python -m n225m_bt.research loop --config config/research_agents.local.yaml
```

H02以降ではobjective_fileと未使用のcampaign_idを変えます。6件を自動で順番に選択するキュー機能は今回追加していません。
同じ作業ツリーでキャンペーンを並行実行しないでください。各戦略内のケース並列実行は既存workersで行います。
max_familiesを増やすと初期仮説の結果から次の設計へ進めますが、6仮説を順番に選ぶ指定ではありません。

objective_fileはリポジトリルート基準のUTF-8ファイルです。既存objectiveの後に本文を追加します。
設計時にobjective_snapshot.jsonへ保存し、その設計の再開では保存した本文を使います。プロンプトを変更して新規開始するなら新しいcampaign_idにします。
objective_fileを指定しない従来の設定はそのまま動きます。利用した部品は通常のカタログへ蓄積されます。

期間はdefaults.periodsなど既存設定を引き継ぎます。指定しなければ登録データ全範囲です。既に研究結果を見た期間を独立ホールドアウトと呼びません。
設計は本文の範囲を維持するよう指示しますが、LLMの出力が常に正しいと保証するものではありません。事前審査は追加せず、生成されたfamily.jsonと出力coverageも結果として残します。

## agy implementer：Windowsの長いプロンプト向け設定

config/research_agents.agy.example.yamlに全体例があります。既存設定のimplementer部分だけ置き換える場合:

```yaml
roles:
  implementer:
    model: null  # `agy models`に表示される実際のslugで固定可
    argv:
      - agy  # 必要なら確認済みフルパス（例: C:/.../agy.exe）
      - --input-format
      - stream-json
      - --output-format
      - stream-json
      - --model
      - '{model}'
      - --json-schema
      - schemas/research_implementation.schema.json
      - --print-timeout
      - 120m
    stdin: true
    stdin_format: agy_stream_json
    timeout_seconds: 7260
```

`model`は設定ファイルだけで指定します。nullならCLI側の既定値を使います。利用できないモデルIDを仮定して埋め込まないでください。
model名ではなくslugは手元の`agy models`で確認できます。CLIをインストール・認証し直す手順はありません。

この方式は1回の呼出しで1つのuserイベントを標準入力へ書いて閉じます。agyは最後のresultを返して終了します。
長い設計・ソース・結果要約をWindowsのコマンドライン引数へ入れないための選択です。
stream入力では`-p`や`{prompt}`をargvへ追加しません。stdin_formatがAS4FTS側で通常の文章をイベントJSONへ変換します。
`--json-schema`はfiles配列の出力形式を指定するだけで、設計レビューの工程ではありません。
CLI側の--print-timeoutとAS4FTS側のtimeout_secondsは別です。例では120分と、その終了を待てる7260秒にしています。これは実行所要時間の予測ではなく上限です。

実装役はJSONとして完全なコードを返し、ファイルへの適用はPython側が行います。全権限を自動承認するフラグは標準例に含めません。
必要な読み取り権限は既存CLI設定を使用します。CLIがpermission deniedを出したらstderr.logを確認し、必要な権限だけを調整します。

## 短いプロンプトでの代替argv

```yaml
model: null
argv: [agy, '-p', '{prompt}', --model, '{model}', --output-format, json, --json-schema, schemas/research_implementation.schema.json, --print-timeout, 120m]
stdin: false
stdin_format: text
timeout_seconds: 7260
```

基本形は`agy -p PROMPT --model MODEL --output-format json`です。
こちらは長いプロンプトが引数になるため、大きなカタログや結果を渡す通常研究では上記のstream入力を使用してください。

## 応答形式への対応

agyはSUCCESS/ERROR等のstatus、本文response、conversation_id、usageを返します。
JSON Schema指定時はstructured_outputも返します。stream出力では終端イベントのresultに包まれます。
今回のadapterはこれらを解包し、失敗/待機の応答を空の実装として成功扱いしません。
Claudeのresult形式、Codexのagent_message形式も維持します。費用が返されない場合は不明でありゼロ円にしません。

実際にagyを呼んだことは、キャンペーンのimplement-0/stdout.log、stderr.log、response.jsonで確認します。
response.jsonのrequested_modelは要求値で、metadataのモデル情報とは別です。agyがmodelを報告しない場合は実モデルを確認済みとはしません。
既存factoryを完全再利用できる設計ではimplementation_required=falseになり、implementerを呼びません。CLI切替えの確認時は生成family.jsonの値も確認してください。

## 確認範囲

追加した純粋関数・CLIプロトコルのテストをPython 3.13.5で実行し、33件成功。
全6グリッドの件数、H05の観測モード、objective読込/スナップショット、旧形式とagy形式のJSON解包、非SUCCESS拒否、Unicodeの長いstdin、模擬CLIのEOFでのresult出力を確認しました。

```powershell
uv run pytest tests/test_research_hypothesis_prompts.py tests/test_research_agy_protocol.py
```

実agy・実モデル、利用者の認証環境、実Goldでの6戦略実行、全リポジトリのCI、Windowsの実CLI起動は未確認です。
確認テストは今回の機能開発用で、研究ループの事前条件にはしていません。
今回も既存のキャンペーン全体complete表示の仕様は変更していません。各historyのsummary.statusとcoverageを確認してください。

## 公式資料（CLI仕様の確認元）

確認日: 2026-09-19。手元の旧バージョンに同じ機能があるかはagy --helpで確認します。
- Google Antigravity Headless mode: https://antigravity.google/docs/cli/headless/
- Google Antigravity CLI Permissions: https://antigravity.google/docs/cli/permissions

headless資料の-p、--input-format stream-json、--output-format、--json-schema、--model、--print-timeoutとイベント例に基づいています。
本リポジトリでは第三者CLIの実行結果や認証済み環境を同梱しません。
