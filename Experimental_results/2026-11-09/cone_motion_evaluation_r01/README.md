# 走行向け・現在フレーム測距経路 r01

追加撮影を行わず、静止判定を待たない専用の実験用受信モードを実装した。**ソフトウェア検証済み、実機走行・CUDA推論・運転系への統合は未確認**であり、走行中測距の完成を宣言する資料ではない。

最終の方針確認：既存の映像送受信とハンコン操縦の併用はユーザーが実施済みで、通信はROSとの回答済み。その実績を再確認することは次の着手条件ではない。次は既存運転用受信映像を測距へ分岐し、**距離推論を加えたことによる**負荷・遅延と走行時の更新安定性を検証する。以下の独立した診断用受信器の制約と、元から可能な映像・操縦の同時運用を混同しない。

## 今回進めた範囲

- `start_cone_distance.sh motion-receive` を追加。従来の `receive` と運転用 RTC は変更しない。
- YOLO の現在枠 → 同じ画像の支持範囲 → 校正済み魚眼の視線 → 仮定した床面との交点、という経路を最新フレーム優先で処理する。
- 静止向けの背景姿勢推定、同じ支持点での3フレーム確認、端点の静止幅制限はこの実験経路では使わない。大きく動く支持点でも現在画像に根拠があれば更新する。
- 支持範囲の列数・広がり・連結性、検出の一意性、画像時刻、接続sessionなどの検査は残す。観測失敗や古い結果は保留し、直前の数値を埋め合わせない。
- 推論中に次の画像が来ても待ち行列をためない。結果は処理した元フレームとの組で表示する。
- ROS、TF配信、FFB、速度制御、制動、自動走行は接続しない。元画像への上書きや解析画像ファイルの生成はしない。

## 表示する距離と仮定

表示値は **カメラ直下の床上点から、観測した支持点までの水平距離**。車体中心からの距離、前後Z、左右X、台座までの最短距離、接触距離とは区別する。

既存 L 字の固定4点からカメラ座標での床法線 `up` と高さ `h` を準備し、単位視線 `r` に対して `lambda = h / (-up・r)`、水平距離を `sqrt(lambda^2 - h^2)` とする。水平な床上での並進・旋回では床法線と高さがカメラに対して変化しない、という仮定を使う。背景の見かけの回転から移動量を推定する方式にはしない。

未解決の車体左右の定義を数値へ混ぜないため、4点には任意のローカル長方形座標を割り当てる。左右の物理的な対応が解決済みという意味ではない。

以下は補償・検出できないため、実験上の制約として残る。

- カメラ取付角・高さの変更、車体のピッチ／ロール、揺れ、段差、床勾配。
- 校正sessionから現在sessionへの取付状態の一致。画像サイズと内部パラメータのハッシュ照合だけでは物理的一致を証明できない。
- 支持点が本当の床接触点であること、動いている画像での検出安定性、端末間の撮影遅延。
- 同一コーンの継続追跡。複数候補は保留し、一意な候補でも同一個体と保証しない。

したがって `physical_metric_verified`、`floor_contact_verified`、`controlling_distance`、`usable_for_ffb`、`published_to_ros` は全て false。既存の静止経路を緩めた正式採用ではなく、独立した明示 opt-in の観測実験とする。

## 既存データによる検証

最新の結果は [verification_r02/summary.json](verification_r02/summary.json)、[テスト記録](verification_r02/tests.log)、[フレーム別CSV](verification_r02/cached_replay_metrics.csv)。r01 は31件時点の履歴で、r02 は校正準備の追加テストを含む37件。

| 確認項目 | 結果 | 限界 |
| --- | --- | --- |
| 新規単体・結合テスト | 37件成功 | 推論・通信の実機性能試験ではない |
| 大きく動く支持点／並進・旋回の合成幾何 | 更新・計算を確認 | 動画による走行試験ではない |
| 古い結果、切断、再接続、推論中の停止 | 保留・旧結果破棄を確認 | 実CUDA呼出しの中断は未確認 |
| 既存実画像＋そのフレームの保存YOLO枠 | 10枚中3枚で距離出力 | 新規YOLO推論なし、session間校正転用は未検証 |
| b559e424 f035562 | 1.006 m | 他のb559 7枚は引き続き保留 |
| df33e833 f061948 / f064232 | 0.979 / 1.954 m | 1m / 2m条件の画像だが、距離原点・校正転用を含む正式な精度評価ではない |

残る7枚は主に `colour_contour_reaches_roi_edge`。静止待ちを外しただけで支持点の取得失敗が直るわけではなく、連続した走行映像での表示率は未確認。数値の出ない画像を除外して「安定動作」とは扱わない。

再生の完了時刻は保存時刻＋模擬10msと明示している。別記のCPU処理時間はYOLO・通信時間を含まず、実機FPSや遅延の根拠にはしない。このPCには torch / ultralytics がなく、カメラ・CUDA・機体は起動していない。

## 既存4点から準備済みのファイル

[prepared_r01/motion_profile_r01.json](prepared_r01/motion_profile_r01.json) を受信側へ渡す。実行時に元PNGを再撮影／提出する必要はない。元画像・4点・入力・コードのハッシュは同フォルダの `input_provenance.json` に記録した。

- 校正画像: session `159c37ad534a4ac0b96ca69791713567`、f038231。
- 固定4点のみを使用。評価点Eとコーンの真値はフィットへ使わない。
- 任意座標の幅0.8 m×奥行0.8 m。主仮説 `ippe_0` の高さ0.5768 m、再投影RMSE 0.106 px。
- 別仮説 `ippe_1` も保持し記録する。表示の仮説間の差は誤差幅・信頼区間ではない。主仮説が使えないときに別解へ自動切替しない。
- 59 cmとの近さ／低い再投影誤差だけを理由に物理校正済みとはしない。

再現コマンド（新しい出力先を指定する）:

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepare_existing_reference.py \
  --output-dir /tmp/cone_motion_prepared_r01
/home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-09/cone_motion_evaluation_r01/verify_existing_data.py \
  --output-dir /tmp/cone_motion_verification_r01
```

## 受信・送信手順（後で実機を使えるとき用）

今すぐの追加撮影は求めない。新コード・設定・準備済みJSONをGPU PCへ反映してから使う。以下は**映像・測距だけの診断経路**で、従来の運転用RTCコマンドとは別物。

### GPU PC: 先に受信側を起動

同じ5002番ポートを使う既存の受信処理を同時に起動しない。

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"
MOTION_RUN="Experimental_results/2026-11-09/cone_motion_live_$(date +%Y%m%d_%H%M%S)"

./start_cone_distance.sh motion-receive \
  --weights "$HOME/Downloads/cone_distance_v03.pt" \
  --motion-profile Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json \
  --experimental-rigid-mount \
  --support-source upper \
  --target-roi 270 0 350 720 \
  --output-dir "$MOTION_RUN"
```

`--experimental-rigid-mount` は未検証の固定取付・平面床仮定を明示する指定で、精度の承認ではない。重みは既存の指定SHA-256に一致するローカルファイルを使い、別モデルの自動取得・CPUフォールバックは行わない。

ROIは**生画像の左魚眼**の検出枠中心で `x=270..350` の中央付近だけを対象にする例。外側は監視しない。現在のL字画像の赤コーンはこの外側なので、その配置にこの例をそのまま使うと検出対象外になる。前方全域を対象にする場合は `--target-roi 270 0 350 720` を省く（複数コーンが検出されたら保留）。狭いROIのまま左右を通過するコーンを追えるとは扱わない。

### matsunuc: 映像を送信

```bash
cd ~/theta_ws
export THETA_RTC_PYTHON="$PWD/theta-env/bin/python3"
bash src/start_theta_stream_rtc.sh --diagnostic \
  --receiver-ip 150.89.169.78 \
  --device /dev/video0 --fps 30
```

IP・デバイスは現場の接続に合わせる。`--diagnostic` は最初に1回だけ付ける。1280×720の生dual-fisheyeを使い、リサイズで別の画像座標系へ合わせる処理はしない。床モデルは起動時に読み込むため **Lキーは不要**。Sキーによる追加保存も動作条件ではない。

### 重要: 従来の運転用通信との違い

| 経路 | 映像の既定寸法 | 操縦信号 |
| --- | --- | --- |
| 従来 `webrtc_receive_ui.py` / `webrtc_stream.py` | 1920×960 | DataChannel `control` あり |
| 今回 `motion-receive` / 診断sender | 1280×720固定 | なし |

この2コマンドだけではG923から機体を操作できない。運転用受信画面と同じポートで並行起動したり、カメラを二重に開いたりしない。現在の校正は1920×960映像への流用も検証していない。走行操作が従来RTC経由なら、次は**既存の操縦経路を維持した受信フレーム接続と画像座標の一致**を実装・検証する。独立した走行操作経路がある場合のみ、今回の受信処理を観測側として組み合わせる余地があるが、本作業では機体を動かしていない。

ユーザーから「ROSで通信」「従来から映像と操縦を併用できている」と確認済み。既存コードにも `ROS /cmd_vel_joy → control DataChannel → ROS /cmd_vel` の中継がある。**次はこの既存構成を維持した受信画像の分岐を実装し、診断senderへの単純置換はしない。** ROSの操縦設定・起動中ノードは本作業で変更していない。以下は将来、推論追加後の構成差を調べる必要が生じた場合だけの読取りコマンドであり、映像と操縦の併用実績を再確認するための必須提出物ではない。

```bash
ros2 topic info /cmd_vel -v
ros2 topic info /cmd_vel_joy -v
```

`theta_driver_telemetry_node` は既存RTC sender内でこれらへ速度指令をpublishするノード。これが現在の操縦の中継元なら、診断senderへの単純な置換をしない。別publisherがあるだけでも操縦が独立している証明にはならず、普段の起動構成と合わせて確認する。直接ROSの経路が確認できた場合は、それを維持して測距の映像処理だけを組み合わせる。

Q / Ctrl+C は測距受信処理を止める操作で、機体の停止操作ではない。測距値を速度・ブレーキ・FFBへ接続してはならない。

## 出力

- `motion_distance_frames.jsonl`: 処理した各フレームの距離、保留理由、支持範囲、仮説別結果、受信後経過時間、推論時間。
- `motion_live_summary.json`: 条件、GPU・重み・ソースのハッシュ、処理数／出力数、終了状態。
- `motion_profile_used.json`: 実行で使用したプロファイル。

受信後経過時間は端末間の撮影→表示遅延そのものではない。GPU処理が固まった場合は停止後もネイティブ推論が残る可能性をsummaryへ記録し、停止済みの数値を再表示しない。

## 判断の根拠と次の優先順位

既存の `angular_fisheye_geometry.py`、`floor_reference_pose.py`、ネイティブRTC入力とローカル重みのCUDA推論を再利用した。新規依存・別の学習モデル・別キャプチャ経路を増やさず、CPU側は支持範囲と幾何だけに限定する。光軸座標と姿勢変換の基準は [OpenCV PnP公式資料](https://docs.opencv.org/4.x/d5/d1f/calib3d_solvePnP.html)、魚眼の画素と角度の関係は [魚眼モデル公式資料](https://docs.opencv.org/4.x/db/d58/group__calib3d__fisheye.html) を確認した。歪んだ生画素をそのまま通常のピンホール画素とみなす実装にはしていない。

次は、既存の映像・操縦経路を維持して、受信画像を測距workerへ分岐する接続を実装する（まだ未実装）。入力解像度と校正の整合を保ち、推論追加後のGPU処理時間・映像／操縦遅延・更新率・保留率を確認する。新しい床撮影や既存L字の精度監査、併用実績そのものの再試験は現在の着手条件にしない。新しい入力経路の実機確認は未実施なので、走行中の精度・安定動作の保証は残る。
