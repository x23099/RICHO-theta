# コーンYOLO B動画の全フレーム評価（2026-10-13）

## 到達点

RTX 3070で既存B録画2本・**5,808frameを間引かず解析**した。
注釈済み38frameの評価は赤18/18・黄色0/38で、先ほどのPNG診断と一致。
しかし赤コーンを動かした動画には検出0の区間10か所・計48frameがあり、静止画の成功だけで連続認識が完全と判断できない。

今回確認した代表点では、小さく傾いた持ち運び、近距離で傾けた持ち運び、魚眼の境界・部分欠けで出力が途切れていた。
モデルや閾値の本番採用、全動画の精度合格、距離/TTC/FFBの実装・実機動作は完了していない。
元録画・model・dataset・本番設定は変更していない。

## 1. 実行条件と整合性

| 項目 | 内容 |
|---|---|
| GPU / Python | RTX 3070 / リポジトリ内yolo-env |
| torch / CUDA / Ultralytics | 2.14.1+cu130 / 13.0 / 8.4.175 |
| model | 10/12受領のbest.pt。SHA256をprovenanceへ保存 |
| 画像 | raw.avi全逐次デコード、1280×720、全dual-fisheye |
| 推論 | imgsz960、rect=false、FP32、batch1、confidence0.25、NMS IoU0.7 |
| 枠対応 | 同じ画像半分内・隣接frame・IoU>=0.3、greedy一対一。空白を跨いだ復元なし |
| B赤あり | cone_train_block_b_r01_20261012_155114_513、5,236frame、CSV末尾175.260612秒 |
| B赤なし | cone_nasi_block_b_r01_20261012_155435_017、572frame、CSV末尾19.124547秒。黄色は写る |
| 注釈との照合 | 38frame/56GT、元PNGのpixel hashとの不一致0 |
| 出力status | COMPLETED_OFFLINE_VIDEO_NOT_DEPLOYMENT_APPROVAL |
| source/code/plan | [provenance.json](provenance.json)でhashと実行条件を追跡 |

全動画の長さ・geometryがCSV/metadataと一致し、余剰frameがないことを確認した。
録画frame/timeとPNG抽出時のpixel hashが一致した38点では、前段と同じ入力画像として比較できる。
モデルのclassはtraffic_coneのままで、赤/黄の分類ネットワークを追加したものではない。
今回のBは既に使った開発用データで、独立test・実走行試験ではない。

## 2. 連続出力と処理時間

| 指標 | 赤コーンを動かしたB | 赤なしB |
|---|---:|---:|
| 全frame | 5,236 | 572 |
| 検出1件以上のframe | 5,188 | 0 |
| 検出0のframe | 48 | 572 |
| 検出2件以上のframe | 59 | 0 |
| 検出で前後を囲まれた0区間 | 10 | 0 |
| 最長0区間のsample時刻幅 | 0.404462秒（frame28～38） | 全編19.098130秒 |
| 隣接IoU対応の断片数 | 50 | 0 |
| session処理時間 | 108.677秒 | 11.027秒 |
| オフライン逐次処理速度 | 48.18 fps | 51.87 fps |
| 初回除外pipeline平均 | 20.29 ms | 19.13 ms |
| 初回除外pipeline p95 | 25.24 ms | 23.53 ms |
| 初回除外pipeline最大 | 78.23 ms | 61.45 ms |
| 初回除外framework推論p95 | 10.17 ms | 10.90 ms |

**検出1件以上が5,188/5,236=約99.08%という値はRecallではない。**
全frameの物体可視性・正解枠がないため、全体のFP/FNを測っていない。
2件以上の59frameも、複数物体・二重魚眼に写る同じ物体・重複・背景のどれかを全件確認した数ではない。
50の対応断片は物理コーン50個ではなく、ID復元をせず隣接IoUで結んだ断片数。

時刻幅は0区間の最初と最後のsample時刻差で、1frame区間は0秒になる。
厳密な遮蔽時間・警告遅延・frame数/fpsの換算値と混同しない。

処理速度はこの実行時のオフライン値。pipeline範囲はdecode/predict/枠対応/予測CSVまで。
CSV最終保存・モデル起動・source hash・図作成は含まない。初回callは別に記録し、表のpipeline統計から除外した。
p95は33.3 msより短い一方、最大は超える。liveカメラ、GUI、ROS、relay、FFBまで含めた30 fps保証ではない。

根拠：[video_summary.json](video_summary.json)、[frames.csv](frames.csv)、[predictions.csv](predictions.csv)、[zero_detection_runs.csv](zero_detection_runs.csv)。

## 3. 注釈frameと新しい目視確認

注釈38frameでTP18/FP0/FN38。赤18/18、黄色0/38。[anchor_stratum_recall.csv](anchor_stratum_recall.csv)。
注釈を時間方向へ補間して、未確認frameまで正解扱いすることはしない。

全10か所の0区間から中央sampleを1点ずつ選び、元解像度・無加工PNGで確認した。
さらに下端変化最大の前後2frameを確認し、計12点の[visibility_review.csv](visibility_review.csv)を保存した。
これはassistantの代表点レビューで、全5,808frameの目視・bboxラベル追加・独立人評価ではない。

| 代表frame | 確認した見え方 |
|---|---|
| 22/33 | 小さい赤コーンを手で持って傾け、机周辺に一部が隠れる |
| 51/56/63 | 小さい赤コーンが傾いた状態で見える |
| 1462/2872 | 大きい赤コーンを持ち上げて傾けている。床に台座が接していない |
| 3207/3213 | 魚眼間の境界を移動し、端に赤い部分/台座だけが残る |
| 4566 | 境界移動後、左レンズ端付近の赤コーンが見える |

10区間の代表点のうち8点は赤の本体が少なくとも一部見える。2点はごく一部のみで、物体全体が認識可能な状態とは断定しない。
したがって「単に全区間でコーンが完全に画角外だった」という説明では済まないが、区間内全frameをFNとして確定したわけでもない。
0.25以上の出力しか今回保存していないため、これらのframeで候補が完全に無いのか、0.25未満で捨てられたのかは未分離。
必要なら選択した未編集PNGだけを低floorで再推論し、全動画を無条件に再処理しない。

## 4. 枠下端の変化と距離への接続

隣接対応した枠の下端中央移動のframe内最大値は、中央値0.341 px、p95=3.889 px、最大28.250 px。
対象の実移動が含まれるので「距離推定ノイズ」とは呼ばない。

最大はframe4553→4554、右画像のtrack29。IoU0.7886で対応継続し、x方向差0.523 pxに対してy下端が28.246 px変わった。
両rawではコーンが魚眼の端にまたがり部分的に写る。この条件のbbox下端は距離へ直結させる前に妥当性の評価が必要。
枠の揺れと実移動の割合を今回確定していない。[原画像manifest](raw_review_manifest.csv)とraw_reviews/を参照。

**持ち上げたコーンのbbox下端は床接地点ではない。**
今後は床上で立っている対象、画角端で切れた対象、台座が隠れた対象を分け、接地点が確認できる場面だけで固定魚眼→床面投影の評価を進める。
既存の青箱用横位置補正・TTC・FFBへ、そのままこの座標を流用する実装は行っていない。

## 5. 追加実装と次の作業

- `./start_cone_yolo.sh video`で既存sessionをワンコマンド解析できるようになった。
- 現在の2本は処理済みなので、同じコマンドを打ち直す必要はない。同名outputは上書き拒否する。
- 別の走行録画が見つかれば、raw.avi/detections.csv/metadata.jsonを含むsessionのpathを新しいplanへ登録し、新しいoutputで評価できる。未ラベル動画でも出力/時間の診断は可能だが精度合格にはしない。
- 走行録画が未発見でも、上記12点のうち見える対象を低floorで再推論し、姿勢・端欠け・confidenceの問題を切り分けられる。
- 次の距離評価には、床上に置いたコーンの接地点が見えるデータと、距離の参照が必要。今回の持ち運び動画を、そのまま距離精度・動的TTCの正解へ置き換えない。
- モデル再学習・新しい録画・全体閾値の変更はまだ行わない。

起動・plan・CSVの説明：[動画評価手順](../cone_video_preparation/README.md)。
関連unit test90件PASS（新規16件を含む）。元動画hash保持、逐次frame数/geometry、注釈PNGとのpixel一致を実データでも確認した。
全12PNGは元rawデコードと画素一致・1280×720・全画角で、注釈/切抜き/色補正なし。
集計図は[video_detection_and_timing.png](video_detection_and_timing.png)、生成は[analyze_video_results.py](analyze_video_results.py)。
source/CSV/図/script hash：[postprocess_verification.json](postprocess_verification.json)。
Matplotlibの未使用Axes3D/一時cache警告は出たが、2D図の生成と表示確認は完了。グローバル環境は変更していない。
Gitへのコミット/PUSH、実機操作はこの作業では行っていない。
