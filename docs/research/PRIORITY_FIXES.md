# H01–H06 レビュー後の優先修正

## 反映状況（2026-09-19）
GitHub `feat/strategy-batch-research` には次の2コミットを反映済み。
- `1cee353112b1079686ef2ba39a5f58f04b7efcc6`: H02別バージョンと回帰テスト。
- `f4eb2bc77d8667e3938658f55ef8c12f4a3263fc`: 一意のJSONコードブロックの回収。
その後のGitHub書込みは連携側でブロックされた。以降の変更は適用パッケージに含む。全修正がpush済みではない。

## 1. H02: 既存H01派生の意味は変更しない
`opening_range_failure_fade:create_strategy` は旧動作を保持。
H02は `opening_range_failure:create_strategy`、strategy_version=2を利用する。
帰還は上下両境界を含む [L,H]。0 < 経過時間 <= 帰還期限、監視終了時刻自体は含まない。
帰還期限が過ぎても未発注ならシグナル枠を消費せず、後続の突破を観測する。
監視期間から帰還待ち時間を差し引かない。出口・費用・探索範囲は変えていない。

保存済みH02を、パラメータ・期間・費用を維持して準備する:
```powershell
uv run python scripts/prepare_h02_rerun.py --source .research/campaigns/h02_v1/h02_v1-0001/family.json --output .research/h02_contract_v2.json
uv run python -m n225m_bt.research run .research/h02_contract_v2.json --workers 5
```
新規例は `examples/research/h02_contract_v2.yaml`（432条件）。実Goldの再実行はこの開発環境では実施していない。
旧H02結果は削除しない。factory/versionを区別して比較する。H01派生やH02後続仮説を無条件に書き換えない。

## 2. 応答形式
説明文に囲まれた唯一のJSONコードブロックを回収する。
複数候補・壊れたJSON・CLIのERROR/WAITINGを成功として採用しない。
実装内容の意味の審査は追加しない。6件の実ログから6件ともfiles配列を回収できた。
CLIが正常終了した未解析応答はreceipt.jsonと生ログを保持し、再開時に再解析できる。
本当に不正な応答は paused_agent_output。モデルに戦略全体を無条件に再実装させない。
生応答の修正/出力形式改善後、同じcampaign_id・同じstageを再開できる。

## 3. 障害の配送と再開
戦略例外だけがmax_repairsを消費してimplementerへ進む。
CLI・形式・I/O・プロセス/メモリ・設定の障害は同じactive.stageを保持して停止する。
一時的PermissionErrorには短い上限付き保存再試行がある。恒久的失敗を黙殺しない。
ワーカー初期化の元の例外をexecution_faultとして保存する。
エンジンの経済計算は変更せず、strategy/baseのUTF-8副作用をCLI層へ戻した。
実行ファイルの解決先・cwdをログに残す。プロンプトにもproject_rootを渡す。
CLI内部が独自scratchを使う製品では、これだけで内部cwdが強制変更されるわけではない。

状態:
- complete: 全ファミリー成功。ゼロ取引は成功/診断情報として残る。
- complete_with_failures / failed: 一部/全ファミリーに実行失敗。
- paused_io / paused_agent_cli / paused_agent_output / paused_resource / paused_configuration: 同じ段階を保持。
- partialのバッチは全空間の完了とは扱わない。

一時停止は同じloopコマンドで再開。履歴へ記録済みの最初の失敗を再試行する場合:
```powershell
uv run python -m n225m_bt.research loop --config config/research_agents.local.yaml --retry-failed
```
以前の履歴はattempt_historyへ残す。最古の失敗1件が対象。必要なら同じ指定を繰り返す。
全成功以外のloop終了コードは2。CLI/設定を直すためにキャンペーンを新規設計する必要はない。

## 4. キャンペーン横断の研究履歴
.research/batchesのsummary/familyとcampaignsのstateを、小さいSQLite索引へ自動登録。
変更されたメタデータだけを解析し、Gold・取引台帳全体の監査は行わない。
次の設計にrelated_researchを追加し、既存探索範囲・結果・失敗を知らせる。
関連順に既定8件。利益上位だけで選ばない。全文はsource参照で確認できる。
索引に問題がある場合は警告を残すが、それを研究開始の承認ゲートにはしない。
```powershell
uv run python -m n225m_bt.research history --query compression --dataset center-auto-v1 --limit 8
```
独立した未見期間であるとは扱わない。既に参照した探索結果として明記する。

## 5. キャッシュ
戦略factoryからの静的import依存とランナー・約定・集計等を識別子へ含める。
無関係な戦略追加だけでは再計算しない。利用部品・基盤・入力・コスト・パラメータ・期間・環境変更は区別する。
パス型パラメータとリテラル設定ファイル、明示したcache_dependenciesも内容ハッシュへ含める。
動的import/eval/exec/ワイルドカード等で依存範囲を確定できない場合、グローバル再利用を行わない。
この場合は再開時も新しい識別子となり、既存ケースを再利用しない。dependencies.jsonに理由を残す。
任意の外部状態へアクセスするPython全般の完全な依存解析ではない。追加の外部入力はcache_dependenciesへ明示する。
外部ネットワーク・未宣言ファイル・隠れた可変状態を用いた計算の同一性は保証しない。

識別方式がversion=2へ変わるため、旧方式の成功キャッシュは初回移行時には流用しない。
旧データは削除不要。移行後の同一条件はキャンペーンをまたいで再利用する。
研究時コード全体のsource.zipは引き続き再現用に保存する。

## 6. 実行後の観測
- trialsにentry_signals_returned / exit_signals_returned / eligible_bar_count。
- diagnostics.jsonに戦略が保持する診断の件数・理由・少数の例。
- summaryにゼロ取引ケース数、バッチ壁時計時間、ワーカー計算秒数合計。
- stateにdesign / implement / backtestの実測壁時計秒数。
- component_usage.jsonでは自己申告と静的モジュール参照を区別する。関数単位の実呼出しを証明するログではない。
- variantsの未対応実行キーは無言で無視しない。when/derived_parametersを使う既存仕様はconstraints/parametersで明示し直す必要がある。

これらは結果記録と必須の入力解釈であって、事前の仮説審査・全データ監査ではない。

## 実施した検証
Python 3.13.5 / pytest 9.0.2（利用環境のpytestで実施）。追加対象40テスト成功。
既存H05修正パッケージの18回帰テストも成功。合成データの実エンジンと模擬CLIを利用。
- H02の5不一致、ロング/ショート、432パラメータの構築、旧H01動作維持。
- 実ログ6件のJSON回収。曖昧/ERROR/WAITINGは拒否。
- I/O停止→同じphase再開、モデル不要、失敗履歴の明示再試行。
- ワーカー初期化原因の保存。
- 2キャンペーンの結果引継ぎと実キャッシュ再利用。
- 無関係ソース追加時のキャッシュhit、関連ソース変更時の再計算。
- 添付11ファミリーの履歴索引化。
- 診断・時間・未対応variantsの通知。

未実施: 実Goldの再バックテスト、実CLI/実料金、Windowsの実プロセス、全リポジトリCI、Ruff/mypy。
Polars/PyArrowは本開発環境にない。実Parquetの検証に成功したという意味ではない。
テストは基盤変更の確認として実施したもので、通常の研究ループに全テストを挟む変更はない。
