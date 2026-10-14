# 追加D/E録画5本の受入れ・初回モデル診断（2026-10-14）

## 結論

**5本とも録画整合性PASS。E02とE03は両方使える。**
E02は固定位置での赤・黄コーンの繰り返し、E03は近い配置・位置替え・部分遮蔽を含む補足として、別々に評価する。
D01/D02は学習候補、E01/E02/E03は評価専用。ファイル末尾の`c`で役割を変更していない。

各動画8枚、計40枚の時間均等サンプルを、原解像度のPNGへ抽出した。
**基準モデルはD02の赤い水筒を、抽出8枚すべてでコーンと誤検出した。**
ユーザー確認「赤色の水筒です。コーンではないです」を記録した。
今回は単なる空の背景でなく、実際に誤検出する学習用負例を集められた。

人による全画角ラベル確認はまだpending。今回の録画を使った再学習・モデル運用採用・FFB出力はしていない。
追加撮影は今すぐ必要ない。次は学習Dの16枚のnegative確認から進める。

## 録画整合性

| 録画 | 役割 | CSV/実動画frame数 | 記録末尾時刻 | 記録時刻由来の平均frame rate |
|---|---|---:|---:|---:|
| D01 | 学習候補：家具・棚・人物 | 1,104 | 36.854秒 | 29.95 fps |
| D02 | 学習候補：赤い水筒を含む | 912 | 33.240秒 | 27.43 fps |
| E01 | 評価用：コーンなし、廊下・看板 | 1,320 | 44.193秒 | 29.86 fps |
| E02 | 評価用：赤・黄の固定配置 | 1,156 | 41.775秒 | 27.69 fps |
| E03 | 評価用：赤・黄の配置変更 | 1,097 | 38.500秒 | 28.49 fps |

合計5,589frame。全raw動画を逐次デコードし、CSV連番、単調時刻、動画/CSV枚数、1280×720の一致を確認した。
上のfpsは記録時刻の差とframe数から求めたもので、GPU推論速度・カメラの要求30fps・端末間遅延とは異なる。
今回の静止画像の学習・評価候補づくりでは、この差だけで録画を無効にはしない。
5本とも記録metadataのAI・FFB publish・relayは0だった。
原動画・metadata・CSVの処理前後hash、PNGとデコード元画素のhashを検査済み。

- [archive_inventory.csv](archive_inventory.csv)：圧縮原本のhash・session構成。
- [session_integrity.csv](session_integrity.csv)：全frame検査・時刻・設定。
- [input_inventory.json](input_inventory.json)：実展開path・raw/metadata/CSV hash・camera parameters。
- 展開原本：`recordings/2026-10-14_cone_ingest_de/{d01,d02,e01,e02,e03}/`（Git対象外）。
- [selected_manifest.csv](selected_manifest.csv)：40枚のsession/frame/time/PNG/画素/raw hash。

動画全体の数値・デコード検査と、40枚だけの目視確認は区別する。全frameを目視・推論したわけではない。

## 画像内容・用途

| 録画 | 抽出8枚の目視所見 |
|---|---|
| D01 | 棚、収納箱、階段、人物、床面反射。両レンズでコーンを特定せず |
| D02 | 同様の背景に赤い水筒。水筒はユーザーが非コーンと確認。両レンズでコーンを特定せず |
| E01 | 廊下・青い看板・人物などの別構図。両レンズでコーンを特定せず |
| E02 | 左レンズの黄色と右レンズの赤、各1個。固定配置のまま安定して見える |
| E03 | 左レンズの赤と右レンズの黄色、各1個。近い配置から移動。frame627/784は置き替え中、frame1の赤は人物で部分遮蔽 |

E02の同じ配置が続くことは欠陥ではない。ただし8枚を独立した8組のコーン・配置として数えない。
E03の扱っているコーンを床に置かれた対象として距離/TTC評価へ転用しない。反射の影響も距離評価では別途検証する。
DとEのraw hash・抽出画素に重複はない。D/E01/E02/E03は異なる室内構図を含むが、DとE02/E03には似た棚・窓の背景もある。
録画の分離と、完全に未知の背景での独立testは同じではない。
今回Eは別収録の開発比較用とし、trainに入れない。Eを見て条件を調整すれば最終blind testとは呼ばない。

## 凍結済み2モデルの比較

推論前の[frozen_comparison.json](frozen_comparison.json)でモデルhashとconfidence 0.25/0.50を固定。
モデルは[同PC35/36枚再学習比較](../cone_ab_retraining_comparison_r01/README.md)で作成済みの2つ。
今回のD/Eはどちらの学習にも未使用。
imgsz960、FP32、batch1、rect=false、NMS IoU0.7、max_det300、保存画像なし、floor0.01。
confidenceやruntimeを結果に合わせて変更していない。

凍結メモ内のsame-room表現は受領時の保守的な想定で、実際の目視では廊下等の別構図も確認した。
この表現でモデル・閾値を選び直したわけではなく、場所の独立性を証明するものでもない。

### 確認済み水筒への誤検出

| 閾値 | 基準35枚：水筒をコーンと予測した画像 | 追加36枚：同じ誤予測 |
|---|---:|---:|
| 0.25 | 8/8枚 | 3/8枚 |
| 0.50 | 8/8枚 | 0/8枚 |

基準の水筒scoreは約0.548～0.608。単に極端に低いscoreの候補ではない。
同じ物理水筒1個の反復であり、8種類の水筒での性能ではない。
元画面の水筒領域とのIoU0.5以上で関連付け、非コーンというユーザー確認と照合した。
この物体の非コーン確認は、D02全画角を人がラベル確認したこととは区別する。

根拠：[water_bottle_false_predictions.csv](water_bottle_false_predictions.csv)、[閾値別集計](water_bottle_threshold_summary.csv)。
D01とE01の抽出各8枚には、どちらのモデルも0.25以上の予測は0枠。
全動画での誤検出率や全画像のhuman GT精度ではなく、選んだ画像に対する出力数である。

### 赤・黄色コーンへの参考照合

**以下はassistantが原画像を目視した参考領域とのIoU0.5関連付け。人の確定GT・正式Recallではない。**
色はモデルが分類した出力ではなく目視属性。モデルclassは赤・黄共通の`traffic_cone`。

| 条件 | 基準35枚：赤 | 基準35枚：黄 | 追加36枚：赤 | 追加36枚：黄 |
|---|---:|---:|---:|---:|
| E02、0.25 | 8/8 | 8/8 | 8/8 | 8/8 |
| E02、0.50 | 8/8 | 8/8 | 8/8 | 8/8 |
| E03、0.25 | 8/8 | 7/8 | 8/8 | 8/8 |
| E03、0.50 | 8/8 | 1/8 | 8/8 | 5/8 |

基準モデルはE03 frame784の黄色（置き替え中）でscore約0.098まで下がった。
0.50へ上げるだけでは、水筒誤検出の低減と黄色の保持を両立できないモデルもある。
今回のD/Eでは追加36枚版に有利な場面があるが、既存BではFP増加が確認済み。
**今回の値だけで追加36枚版を採用しない。** 負例補強後、既存Bと今回Eの両方を固定条件で比較する。

根拠：[color_reference_summary.csv](color_reference_summary.csv)、[各frameのscore](positive_target_associations.csv)。
参考領域は[assistant_reference_boxes.csv](assistant_reference_boxes.csv)。これをhuman labelとして自動登録していない。
候補全数：[prediction_counts.csv](prediction_counts.csv)、全来歴：[analysis_summary.json](analysis_summary.json)。
個々の予測枠は`../cone_de_{d,e}_{baseline,augmented}_diagnose_r01/predictions.csv`。

## 次にユーザーが行うこと

**追加録画より先に、この解析PCで学習Dの16枚を確認する。**

```bash
cd /home/robo25/theta_ws/RICHO-theta
./yolo-env/bin/python3 src/annotate_cone_dataset.py \
  --dataset datasets/cone/de_negative_train_review_v01
```

両レンズに赤・黄を含む三角コーンがないと確認できたら、画像ごとに**N→Y**。
水筒・人物・収納箱はコーンではないので枠を描かない。曖昧なものがあればSで保留。
キャンセル・未確認をnegativeにしない。Qで中断し、同じコマンドでpendingから再開できる。
生PNGは保存時もそのままで、原画像へ枠は描かない。

評価Eの24枚も人のGTを確定する場合は、**別のqueue**を開く：

```bash
./yolo-env/bin/python3 src/annotate_cone_dataset.py \
  --dataset datasets/cone/de_evaluation_review_v01 \
  --split val
```

E01の8枚はコーンがなければN→Y。
E02/E03の16枚はP→両レンズの赤・黄色コーンを台座まで囲む（32枠が目安）。Enterは対象ごとに1回、全枠選択後Esc→確認画面でY。
持ち替えや部分遮蔽は、見えるコーンを対象とし、人物・反射を別のコーンとして囲まない。難しい画像はSで保留して知らせる。
Eのqueueにdata.yamlはなく、学習datasetではない。DのmergeコマンドへEを渡さない。

まずDの確認が終わったら知らせてほしい。現在の36枚に確認済みD負例を追加した新datasetを作成し、固定条件で再学習を比較する。
元の35/36枚・既存B・評価E・原録画を上書きしない。
受入れ時点ではGUI確認までラベル確定・merge・再学習に進めていなかった。
**後続のユーザー確認でD16枚がnegative確定し、52枚版の再学習比較まで完了した。**
結果・非採用判断・次のE確認は[負例追加後の報告](../cone_negative_retraining_v04_r01/README.md)へ。
以下の受入れ数値・assistant参考照合は、再学習前のsnapshotとして維持する。

## 原画像・グラフ

- [D02、水筒の原画像](raw_examples/block_d_20261014_1eba1760023abcce_f000001.png)
- [E02、固定配置の原画像](raw_examples/block_e_20261014_b6fd99bdae17dfd4_f000661.png)
- [E03、配置変更後の原画像](raw_examples/block_e_20261014_acec4adbfa04e57a_f000940.png)
- [水筒誤検出と黄色参考照合のグラフ](selected_frame_comparison.png)

原画像3点は1280×720、全画角、元PNGのバイト同一コピー。
注釈・切り抜き・補正なし。[raw_example_manifest.csv](raw_example_manifest.csv)でsession/frame/time/hashを追跡できる。
グラフは今回の実CSVを元に`analyze_selected_frames.py`で生成、hashはanalysis_summary.json。

## 実施範囲・検証

`ingest_recordings.py`は既存のsafe extraction・hash・等間隔抽出を利用。
各archiveは新しい展開先にのみ展開し、path traversal/linkを拒否、1本あたり3GiBの上限を設定した。
全5動画のデコード/CSV検査・全40PNGのhash検査・D/E重複検査・4runの完了来歴/凍結model hash照合を完了。
作成時の括弧の構文ミス1件は実データ処理開始前に修正し、その後構文確認と全受入れが成功した。
camera/driver/venv/ROS/FFBの変更はない。GPU使用はオフライン画像診断だけ。
Coreの同入力成功済みテスト145件は再利用、今回のdated scriptは構文・実入力来歴・数値集計を検査。
Matplotlibの既存Axes3D警告は出たが、今回の2Dグラフは正常生成・目視確認した。環境修復はしていない。
Git commit/pushは今回依頼されていないため行っていない。
