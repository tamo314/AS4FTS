# H05 夜間の方向性と日中寄付後の反応

## 仮説
夜間セッションに明確な方向が出た後の日中寄付後には、継続または反転に条件付きの特徴があるか。

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
1. backtest.modeは必ずfull_sessionです。現行エンジンのday_onlyでは夜間足が戦略へ渡らないためです。ただし新規シグナルは日中だけで、夜間に売買しません。
2. 同じtrade_dateに対応する直前の確定済み夜間OHLC(On,Cn,Hn,Ln)を集計します。W=Hn-Ln、夜間方向性=abs(Cn-On)/W、夜間方向=sign(Cn-On)です。W=0、方向0、対応する夜間を観測できなかった場合はその局面を見送ります。
3. 夜間方向性>=min_night_directionのとき、日中寄付からconfirmation_minutesまで観測します。夜間と同方向がcontinuation、逆方向がreversalです。日中寄付から確認終値までの変化が候補方向と一致し、directionにも一致すれば1回シグナルを出します。
4. 確認は予定時点で確定した足で行い、その時点の足がなければ未来足を遡って採用しません。売買は次の有効足で、夜間終値で約定したことにはしません。
5. 単純な暦日の前日ではなくtrade_date/sessionで夜間と日中を対応付け、観測していない夜間のOHLCを他の日から流用しません。海外市場データは追加しません。
部品候補: SessionOHLC、SessionClock、確定済み前セッション状態、ScaledBracket。
評価焦点: 夜間方向性と日中確認時間ごとに継続/反転を比較します。full_sessionの観測と夜間売買を混同しません。

## 固定する初期探索仕様
```yaml
factory: n225m_bt.strategies.night_day_response:create_strategy
implementation_required: true
parameters:
  tick_size: 5
  sessions_path: config/sessions.yaml
  max_entry_signals_per_session: 1
space:
  min_night_direction:
  - 0.3
  - 0.5
  - 0.7
  confirmation_minutes:
  - 5
  - 15
  - 30
  policy:
  - continuation
  - reversal
  stop_fraction:
  - 0.1
  - 0.2
  reward_multiple:
  - 1
  - 2
  direction:
  - long
  - short
backtest:
  mode: full_session
backtest_space:
  execution.slippage_ticks:
  - 0
  - 1
  - 2
```

全探索件数: **432ケース**（1データセット・1期間、directionとslippageを含む）。
