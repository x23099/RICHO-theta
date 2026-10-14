# 既存コーン動画の連続フレーム評価（2026-10-13）

`./start_cone_yolo.sh video`を追加し、既存raw動画の全逐次デコード・全frame推論・隣接枠対応・処理時間を記録する。
録画・再学習・ROS・FFB・GUI・モデルの本番採用は行わない。
入力はプロジェクト標準のsession（raw.avi、detections.csv、metadata.json）。
コーンモデルが十分かを評価するもので、コーンの距離やTTCを自動的に実装した処理ではない。

## 構成・入力

- [run_cone_video.py](../../../src/run_cone_video.py)：GPU確認、録画整合性、全frame推論、CSV・来歴保存。
- [test_cone_video.py](../../../tests/test_cone_video.py)：合成動画・Mockによる16件の追加テスト。
- [start_cone_yolo.sh](../../../start_cone_yolo.sh)：既存env/train/val/test/diagnoseを維持し、videoだけ専用runnerへ渡す。
- [video_plan.csv](video_plan.csv)：今回のB赤あり5,236frame、B赤なし572frame。計5,808frame。

input planにsession_dirとnoteを記載する。別の走行録画が見つかれば、別plan・別outputで追加できる。
相対session_dirはplanの場所から解決し、同名session・同じraw内容の二重登録、出力と入力の重なりを拒否する。
入力3ファイルのSHA256、録画時刻の有限値・単調増加、CSVの1始まり連番、動画の全frame数・解像度を検査する。
以前の学習やデータ作成に使った動画を独立testと呼ばない。

## 現在のコマンド（このPC・RTX 3070）

```bash
cd /home/robo25/theta_ws/RICHO-theta

./start_cone_yolo.sh video \
  --plan Experimental_results/2026-10-13/cone_video_preparation/video_plan.csv \
  --weights runs/cone/received_train_ab_bootstrap_v01_r01/yolov8n/weights/best.pt \
  --dataset datasets/cone/ab_bootstrap_v01 \
  --object-attributes Experimental_results/2026-10-13/cone_ab_visual_review_r01/reviewed_attributes.csv \
  --output-dir Experimental_results/2026-10-13/cone_video_b_r01 \
  --confidence 0.25 \
  --device 0
```

同名outputが存在する場合は上書き拒否する。再評価にはr02など未使用名を使う。
制限付きCodexからのGPU使用にはサンドボックス外の実行承認が必要だった。
通常の端末実行と混同してdriver不良と判断しない。venv・driverは既存のまま使用する。
録画やハンコンを起動するコマンドではない。

データ・GPU・モデルを実行せずにplanと引数を確認するには`--dry-run`を付ける。
このpreviewでも入力ファイル・録画CSV・metadata・hashは読み取るが、モデル推論は行わない。
未ラベルの新しい動画は`--dataset`と`--object-attributes`を省いて処理できる。その場合も精度評価や独立test合格にはしない。

## 何を評価するか／しないか

| 出力 | 意味 |
|---|---|
| frames.csv | 各frameの検出数、対応継続/新規数、下端移動量、decode/predict/framework内時間 |
| predictions.csv | すべての閾値以上の予測枠とscore、元pixel座標、隣接枠対応ID、下端dx/dy |
| zero_detection_runs.csv | 検出0の連続区間。前後が検出で囲まれた区間も区別。全frameの正解がないので自動FNにはしない |
| tracks.csv | 隣接frameでIoUが合う枠の連続断片。物理的な同一コーンの証明ではない |
| anchor_pixels.csv | datasetの注釈frameとrawの対応、PNGを作った時のpixel hashとの一致 |
| anchor_per_image/matches/stratum_recall.csv | 注釈済みframeだけの正解対応・色別Recall。全frameへGTを補間しない |
| video_summary.json | 各sessionの集計・処理速度・制約。実機合格判定ではない |
| provenance.json/environment_freeze.txt | source/model/plan/code/dataset hashとGPU・環境版 |

推論はimgsz960、rect=false、FP32、batch1、confidence0.25、NMS IoU0.7、max_det300。
対応は同じ画像半分内の隣接frameをIoU>=0.3でgreedy一対一にする。
検出が途切れたときはIDを引き継がず、後から新しい断片にする。予測で空白を埋めない。
画像半分は左/右であり、物理的な前/後は自動認定しない。

枠下端の移動には、コーンやカメラの実運動・台座の遮蔽・対応の切り替わりが混ざる。
純粋な計測ノイズ、距離誤差、接地点誤差と呼ばない。
pixel hashが異なる注釈frameがあれば、それも記録し、前段PNG推論との同一入力を主張しない。

処理時間は単一GPU・オフライン逐次処理の実測。initial callは別に印を付ける。
pipeline_msはdecode/predict/枠対応/予測CSV書込までで、frame CSVの最終保存や集計図作成は含まない。
sequential_processing_fpsはsessionループ全体で測り、モデル起動・hash検査・後続集計は含まない。
liveカメラ・GUI・ROS・relay・FFBを合わせたFPSや遅延とは別である。

## 検証

既存74件＋新規16件の関連unit test90件PASS。
合成動画の全frame処理と原本hash保持、CSV/video長不一致の拒否、時刻/設定の不正値拒否、
隣接一対一対応・画像半分を跨ぐ対応拒否・途切れを跨ぐID復元の禁止・未ラベル空白のunknown扱いを確認した。
shell/Python構文、diff空白、実在sourceのdry-runを確認した。実データの結果は[動画評価フォルダ](../cone_video_b_r01)へ保存する。

```bash
/home/robo25/theta-env/bin/python3 -m unittest discover -s tests -p 'test_*cone*.py'
```
