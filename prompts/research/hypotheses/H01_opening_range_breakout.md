# H01 寄付レンジ突破

## 仮説
日中寄付直後に形成した一定時間の価格帯を、その後の確定終値が突破した場合、その方向への継続性があるか。

## 役割と進め方
あなたはAS4FTSの設計役です。この初期仮説を、既存のStrategy APIで実行できる戦略ファミリー仕様にしてください。これは未検証の仮説で、収益性を保証しません。
最初の設計では下記の全探索範囲を維持し、少しずつパラメータを変える別ループへ分割しないでください。1つのパラメータ化実装で全組合せを実行します。
結果取得前のデータ再監査、設計承認、全テスト、複数エージェントの合議は追加しません。不明な実装上の境界はdesignへ明記して進め、バックテスト結果から次の仮説で修正します。
previous_familiesがある場合はそれを検証して次の仮説を設計しますが、初回に宣言済みの範囲を微調整するだけの再実装を避けます。独立した初期仮説の確認には新しいcampaign_idとmax_families: 1を使います。

## 実装へ引き渡す共通規約
- 既存カタログ・関連ソースを参照し、使える機能を再実装しないでください。共有機能はsrc/n225m_bt/components/、薄い戦略はstrategies/に保存し、@componentの用途・API・usesを記載します。下記の部品候補は新設案であり実装済みとは限りません。
- 現行create_strategy(parameters)とon_bar(ctx, bar)を使い、全ケースで新しい戦略インスタンスを作ります。戦略固有の可変状態をモジュール全体で共有しません。
- 売買判断は現在までに確定した足だけで行い、次の有効足始値で約定します。価格の未来参照・同一足内の値動き順序の推測・欠損OHLCの補完はしません。
- 初期比較は1枚、買い専用と売り専用を別ケースにします。日中セッション当たり新規シグナルは最大1回。注文が失効してもそのシグナル枠を消費する仕様です。これは今回の固定実験条件で、基盤全体の永久的制約ではありません。
- セッション開始は最初に見えた行ではなくconfig/sessions.yamlの適用期間付き時刻から計算します。時間窓は壁時計の分数で、欠損行を詰めてN分と数えません。期間のウォームアップが未充足ならその局面ではシグナルを出さず、データ全体の監査へ戻りません。
- 基準値幅Wは検出時点で固定します。W<=0では売買しません。損切りティック数はmax(1, ceil(stop_fraction*W/tick_size))、利確ティック数はmax(1, ceil(reward_multiple*損切りティック数))です。
- 出口価格はシグナル終値基準でtick_bracket等により固定します。次足の未知の約定価格を使って設計しません。同一足の損切り・利確は既存エンジンの保守的処理に委ねます。保有終了は損切り・利確・既存の終了前強制決済です。
- sessions_pathからの設定取得は戦略構築または共有ヘルパー内で行い、現在のStrategyContextに存在しない属性があると仮定しません。基盤エンジンを書き換えて動かす設計にはしません。
- datasetと探索期間はキャンペーン設定を引き継ぎます。別の実データ、価格、月次損益を捏造しません。期間未指定なら登録データの全範囲である旨をdesignに記録します。手数料はキャンペーン指定を優先し、未指定時だけ片道100円を比較用仮定にします。

## 設計役の出力
Markdownやコード本体ではなくJSONオブジェクトを1つだけ返してください。必須項目はhypothesis、factory、design、parameters、space、backtest、backtest_space、uses、implementation_requiredです。designに下記ルール・端点・ウォームアップ・共有化方針を含めます。
下記YAMLを仕様の基礎とし、factoryは既存部品で適切なものがあれば置換可能です。存在するだけでなく同じルールと全パラメータに対応する場合のみimplementation_required: falseにし、それ以外はtrueにします。架空の実装を再利用済みとして扱いません。
数値軸の勝手な追加・間引き・サンプリング・最良値だけへの絞込みはしません。case数は1データセット・1期間の値です。比較期間を複数指定したときは各期間で全組合せを実行します。

## 実行後に読む結果
全ケースのtrials.csv/json、sensitivity.json、monthly.jsonを使い、取引ゼロ・赤字・失敗も残します。スリッページ0/1/2を混ぜず、各条件で取引数、1取引当たり純損益、gross・fees・slippageの内訳、月別分布、実現損益ベースのDDを比較します。
パラメータ別平均だけでなく、他条件を揃えた比較と2軸の組合せを確認します。総損失の縮小と1取引の性質の改善を区別し、最大利益の1点だけを検証済み戦略と呼びません。結果がない指標は未確認と記載します。

## この戦略の売買規則
1. 日中開始時刻oから[o, o+opening_minutes)の高値Hと安値Lを集計します。レンジ完成後は固定し、W=H-Lです。基準窓の時刻が終わる前に売買しません。
2. レンジ完成以降、終値がH+breakout_buffer_fraction*Wを厳密に上回れば買い、L-breakout_buffer_fraction*Wを厳密に下回れば売りです。directionに合う方向だけを検出します。
3. 受付は[o+opening_minutes, o+opening_minutes+entry_window_minutes)です。期限を過ぎた最初の足を期限内の足に見立てません。
4. 観測開始が基準窓の途中で寄付部分がない場合、そのセッションでは寄付レンジを作らず理由を残します。過去のセッションからレンジを持ち越しません。
部品候補: SessionClock、FixedRange、ThresholdCross。tick_bracketを再利用します。
評価焦点: 形成時間と余裕幅の効果が取引頻度低下だけか、1取引当たり損益にも現れるか。

## 固定する初期探索仕様
```yaml
factory: n225m_bt.strategies.opening_range_breakout:create_strategy
implementation_required: true
parameters:
  tick_size: 5
  sessions_path: config/sessions.yaml
  max_entry_signals_per_session: 1
space:
  opening_minutes:
  - 15
  - 30
  - 60
  breakout_buffer_fraction:
  - 0.0
  - 0.1
  entry_window_minutes:
  - 60
  - 120
  stop_fraction:
  - 0.25
  - 0.5
  reward_multiple:
  - 1
  - 2
  direction:
  - long
  - short
backtest:
  mode: day_only
backtest_space:
  execution.slippage_ticks:
  - 0
  - 1
  - 2
```

全探索件数: **288ケース**（1データセット・1期間、directionとslippageを含む）。
