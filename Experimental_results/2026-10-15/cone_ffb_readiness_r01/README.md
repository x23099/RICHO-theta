# コーン検知 → 距離・TTC → FFB：第1段階（2026-10-15）

## 今回の到達点

ユーザーの優先順位に合わせ、白線modelの調査は進めず、コーンからFFBまでの経路に集中する。
既存4modelの予測を再利用して、全画角の検出と、正面レンズ内の検出、床面投影の**仮説**を分けた。
新しい`src/cone_observation.py`は既存の魚眼投影を再利用するオフライン部品。
モデルの運用採用、学習、推論の再実行、カメラ起動、ROS通信、FFB出力は行っていない。

**コーン検知完成・距離精度合格・FFB接続完了ではない。**
枠が出ることと、対象が床に置かれ台座が見えていることは別である。
全出力は`floor_contact_verified=False`・`usable_for_ffb=False`。
推定できない検出を「障害物なし」「安全」とする処理も追加していない。

## 既存実装との関係

- `bird_eye.py`の既存YOLOは描画用であり、その枠からコーンの距離・TTC・FFBへ接続されていない。
- 青箱用のHSV・追跡・距離/TTC・警告・ROS publisher/relayは変更しない。
- コーンからの座標候補は`ground_contact.dual_fisheye_pixels_to_vehicle_rays`を使用。
- 青箱用の横位置scale/offset、距離補正式、BEV上の車体表示offsetは適用しない。
- 枠下端中央から床面へ交差させるだけであり、台座の輪郭抽出、床接触の自動確認ではない。

## 比較条件と評価範囲

前日と同じimgsz960の35枚版・36枚版・52枚版・友人YOLO11n、confidence0.25/0.50を比較。
追加の閾値探索は行わず、元の予測CSVが前日のsnapshotに記録されたSHA256と一致することを確認した。
全画角のTP/FP/FN・枚数・GT数は前日の結果を全条件で再現した。
画像・正解label・review hash、元予測の画像対応を確認。画像の保存・編集はない。

| データ | 画像 | 全画角の注釈枠 | 今回の正面scopeの注釈枠 | 制約 |
|---|---:|---:|---:|---|
| B | 38 | 56 | 13 | 既存のassistant visual reviewを含む。今回新たにhuman full-frame確認したものではない |
| D | 16 | 0 | 0 | human negative。52枚版には学習再確認であり、独立holdoutではない |
| E | 24 | 32 | 16 | human確認済み。別収録だが既に開発比較に使用しており、最終blind testではない |

正面scopeは「注釈bboxの中心が、設定された正面の校正円内にあること」で定義する。
1280×720、正面は左画像、camera height0.58m、撮影時configの幾何を明示使用。
画像の左半分というだけで正面と判定していない。
これは人が記したfront属性・床接触・実測距離・衝突対象の正解ではない。
画像を狭く選んだことを全画角の精度改善と呼ばない。

### 正面scope：枠の検出（まだ床面投影は使わない）

各欄はTP / FP / FN。IoU0.5・confidence順・1対1照合。

| model / confidence | B：GT13 | D：GT0 | E：GT16 |
|---|---|---|---|
| 35枚 / 0.25 | 13 / 38 / 0 | 0 / 8 / 0 | 16 / 0 / 0 |
| 36枚 / 0.25 | 13 / 51 / 0 | 0 / 3 / 0 | 16 / 0 / 0 |
| 52枚 / 0.25 | 12 / 2 / 1 | 0 / 0 / 0 | 16 / 2 / 0 |
| 友人 / 0.25 | 8 / 38 / 5 | 0 / 16 / 0 | 7 / 20 / 9 |
| 35枚 / 0.50 | 13 / 1 / 0 | 0 / 8 / 0 | 16 / 0 / 0 |
| 36枚 / 0.50 | 13 / 0 / 0 | 0 / 0 / 0 | 16 / 0 / 0 |
| 52枚 / 0.50 | 10 / 0 / 3 | 0 / 0 / 0 | 16 / 0 / 0 |
| 友人 / 0.50 | 6 / 38 / 7 | 0 / 13 / 0 | 6 / 4 / 10 |

今回の静止画・正面scopeでは36枚/0.50が有望。ただし母数はB13枠・E16枠で、独立した29配置ではない。
**この結果だけでモデル/閾値を採用したり、連続動画・後方の検出まで完成したと判断しない。**
赤黄は引き続き共通のtraffic_coneであり、赤専用化や色判別を追加していない。

## 床面投影の診断

次の場合は座標を出さず理由を記録する：

1. 不正なclass/score/枠、校正解像度と異なる画像。
2. 正面円外、画像端で切れた枠、bbox四隅のいずれかが正面の校正円外。
3. 下向きでない光線、前方床面と交わらない光線。
4. 既存の床面幾何診断と同じ距離範囲0.20～4.0mから外れる交点。

校正円は実画像の可視範囲と同一とは限らず、円外の拒否は「物体が存在しない」の意味ではない。
範囲外を範囲内へclampしたり、欠測を前値・ゼロ距離で埋めたりしない。
範囲値は診断用で、コーンの実機運用範囲の合格値ではない。

投影候補だけを残しても、正解側の分母は直前の正面scopeと同じに保つ。
距離範囲外/端で拒否された正解を消してRecallを上げない。

| model / confidence | B：GT13、投影候補TP/FP/FN | D：投影候補FP | E：GT16、投影候補TP/FP/FN |
|---|---|---:|---|
| 35枚 / 0.25 | 11 / 0 / 2 | 8 | 16 / 0 / 0 |
| 36枚 / 0.25 | 11 / 0 / 2 | 3 | 16 / 0 / 0 |
| 52枚 / 0.25 | 10 / 1 / 3 | 0 | 16 / 2 / 0 |
| 友人 / 0.25 | 8 / 0 / 5 | 0 | 7 / 0 / 9 |
| 36枚 / 0.50 | 11 / 0 / 2 | 0 | 16 / 0 / 0 |

幾何条件でFPを落とせる一方で、検出できていた正解も落ちる。
35枚/0.25の水筒誤検出8枠は投影できてしまうため、床面との交点があるだけではコーンの証明にならない。
E03の持ち上げ/置き替え、Bの持ち運びなど、床仮定が成立しないframeもある。
計算されたx/zはすべて未検証の仮説で、距離誤差やTTCの計測値として利用しない。

## ここから一つずつ進める順番

1. **今回完了**：検出枠と座標仮説を分離し、同じ入力で4modelを再比較する。
2. **本日追加で完了**：[36枚/0.50と52枚/0.25の連続動画比較](../cone_video_comparison_r01/README.md)。7本・計11,397frameを各候補で解析し、次の距離試験の開発候補は36枚/0.50とした。本番採用/FFB接続ではない。
3. **次**：[正面の床置き赤コーンの静止距離参照](../cone_static_distance_capture_procedure.md)を取得し、カメラ直下からの実測距離と、台座の見え方・距離推定の安定性を確認する。既存録画の持ち運びを距離正解にしない。
4. 対象ごとの時系列、複数コーンの扱い、欠測/遮蔽時の状態を定義して、距離・TTC・仮想FFBをオフラインで検証する。
5. 設定を固定後、既存のchallenge relayを使うROS dry_runで確認する。
6. 実機試験の条件と承認を確認してから、停止状態・低出力のハンコンで振動を確認する。既存の上限/arm/watchdogを緩めない。

白線検知はこの流れに混ぜない。本番カメラ設定やblue-box経路も今回は変更しない。

## 成果物・再現

- [全指標CSV](evaluation_r01/metrics.csv)：全画角・正面・投影仮説を別scopeで保存。
- [予測別の座標仮説と理由](evaluation_r01/projection_hypotheses.csv)、[理由集計](evaluation_r01/reasons.csv)。
- [1対1照合](evaluation_r01/matches.csv)、[review原文snapshot](evaluation_r01/review_snapshot.csv)。
- [来歴・制約](evaluation_r01/summary.json)：全入力/コードhash、非採用・FFBなしを記録。
- [比較グラフ](evaluation_r01/front_scope_comparison.png)：CSV由来。カメラ画像の加工なし。
- [グラフ来歴](evaluation_r01/graph_provenance.json)：CSV/graph/script hash。

このPCに保持した前日の予測・datasetを使う再現例（新しい出力名を指定）：

```bash
cd ~/theta_ws/RICHO-theta
python3 Experimental_results/2026-10-15/cone_ffb_readiness_r01/audit.py \
  --output-dir Experimental_results/2026-10-15/cone_ffb_readiness_r01/evaluation_r02
python3 Experimental_results/2026-10-15/cone_ffb_readiness_r01/plot.py \
  --evaluation Experimental_results/2026-10-15/cone_ffb_readiness_r01/evaluation_r02
```

numpy/OpenCVのあるPythonで実行可能。GPU・torch・モデル重みの読込は不要。
既存出力への再実行は拒否する。入力の絶対pathは前日snapshot由来なので、別PCへ移す場合は来歴とdatasetの対応を確認する。

検証：新規geometryテスト17件を含む`test_cone*.py`150件PASS。既存ground geometryとYOLO runnerの21件もPASS、合計171件。
初回集計で友人checkpoint metadataのキー名が自作モデルと異なり停止したが、両形式を明示処理して修正。停止時に出力は作っておらず、入力は変更していない。
Matplotlibの既存Axes3D警告は出たが2Dグラフ生成・目視確認は成功。
実測距離・全frame正解・ROS/実機の検証は未実施。Git commit/pushは今回依頼されていないため実施しない。
