# 2026-10-12 代表資料

前段は赤コーン学習・評価パイプラインの準備。その後、A/Bの実録画4本を受け取り、無加工の学習入力400枚を抽出した。黄色コーンも対象と確認し、うち73枚に109枠を付けた初回試作用datasetを作成した。終業時点では73枚の人の確認記録を受領し、GPU PCの初回50 epoch学習と明示的valまで完了している。実測CSVに基づく学習曲線を追加したが、独立test・実用精度・距離/TTC/FFB接続は未完了。架空の精度グラフや合成画像は保存しない。

録画を取得したら、[データ作成手順](../cone_yolo_preparation/README.md)で元画角・元解像度・無加工PNGを保存する。代表frameはsession／frame／source・画素hashで追跡し、検出精度・処理時間の数値図は対応するCSV・run条件と合わせて追加する。

## A/B実録画の代表資料

- [A・frame1](cone_ab_a_raw_frame_000001.png)：廊下、正面の赤コーン。`cone_train_block_a_r01_20261012_153804_108`、0.025334秒。
- [B・frame2618](cone_ab_b_raw_frame_002618.png)：室内、別の距離・左右位置の赤コーン。`cone_train_block_b_r01_20261012_155114_513`、87.723148秒。
- [Bなし・frame286](cone_ab_b_nasi_raw_frame_000286.png)：赤コーンは見当たらないが、後方に黄色コーンが写ることをユーザー確認済み。`cone_nasi_block_b_r01_20261012_155435_017`、9.591073秒。単一クラス`traffic_cone`ではpositiveの例で、negativeではない。

3枚とも1280×720・全画角・無加工。元rawの逐次デコードから取得し、画素一致を確認した。選択は各録画の最初／中央／最後という事前規則からで、モデル出力を見て成功例を選んでいない。[画像manifest](cone_ab_raw_asset_manifest.csv)、[入力・検証・来歴](../cone_ab_intake/README.md)。

## 初回学習の学習曲線（後続作業）

[cone_ab_bootstrap_training_curve.png](cone_ab_bootstrap_training_curve.png)：GPU PCで実施した50 epochの開発用val指標とtraining lossの推移。初回学習は完了したが、赤・黄色混合の少数valであり、独立testや実用精度の合格とは異なる。元カメラ画像は編集していない。

根拠CSV：[results.csv](../cone_ab_bootstrap_training/results.csv)。生成：[analyze_training_result.py](../cone_ab_bootstrap_training/analyze_training_result.py)。CSV・生成コード・画像hash：[verification.json](../cone_ab_bootstrap_training/verification.json)。数値の解釈と未評価範囲：[学習結果](../cone_ab_bootstrap_training/README.md)。
