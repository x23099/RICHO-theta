# 運転用受信映像への測距接続 r01（2026-11-10）

> 後続の実験記録：[静止／走行画面録画レビュー](../driver_motion_live_review_r01/README.md)、[提出ログ55,906件の解析](../driver_motion_live_analysis_r01/README.md)。走行録画対応569件では29.89件/秒、数値549件、保留20件を確認した。以下の実機未確認は実装時点の検証範囲。現在の到達点は後続記録を参照し、物理精度・操縦遅延の保証と混同しない。

**既存の運転用受信器に、測距を既定OFFで接続した。** 新しいRTC受信器への置換ではなく、同じ受信画像を描画前に別の推論プロセスへ分岐する。操縦・速度指令・telemetry/control DataChannel・ハンコン／キーボードの処理は維持する。

ユーザーが従来から映像とハンコン操縦を併用できている事実は確認済み。今回の対象は、その経路へ距離推論を追加する変更であり、併用実績の再試験や追加撮影を着手条件にしていない。

**ソフトウェア接続の検証まで。実GPU・実カメラ・実機走行の確認、操縦遅延・測距精度の保証は未実施。** 機体、ROSノード、カメラ、RTC待受けは本作業で起動していない。

## 接続した経路

```text
既存sender（映像＋telemetry/control） ── 既存driver受信器 ── 従来の運転映像
                                           │ 展開前の生画像への参照
                                           ▼
                                      最新1フレーム
                                           │ 専用I/Oスレッドのpipe
                                           ▼
                                      別GPUプロセス
                                           │ 元session/frame付きの数値
                                           ▼
                                 運転画面下の独立テキスト欄
```

別プロセスへ分け、運転UIのPythonとGPU推論のPythonも別に指定できる。RTC／UIループでYOLOを呼び出したり、推論終了・pipe送信・結果の読取りを待ったりしない。モデルの初期化失敗・異常終了・推論中断は距離だけを保留し、運転側へ例外を伝播させない。

推論側から1枚要求された時点の最新画像だけを送るpull型。推論中に画像が進んでも過去のフレームをキューへ積まない。カメラの二重取得・追加RTC待受け・画像ファイルへの書出しはしない。受信コールバックは画像の参照とメタデータだけを更新し、画像コピーとpipe I/Oは専用スレッドで行う。

プロセス間の標準入出力接続は[Python subprocessの公式仕様](https://docs.python.org/3.10/library/subprocess.html)に従う。CPU処理を同じPythonスレッドへ載せる場合の制限は[threading公式資料](https://docs.python.org/3.10/library/threading.html)で確認した。新規依存はなく、標準ライブラリと既存のnumpy/OpenCV/RTC/CUDA環境を利用する。**プロセス分離でもCPU・GPU・メモリ帯域は共有するため、操縦遅延が増えないという保証ではない。** 追加コピー・通信・推論の負荷は実GPU PCで別途測定する必要がある。

## 校正と画像座標の扱い

必須ファイル・Pythonの指定不足や、起動引数の画像寸法の不整合はROS起動前に拒否する。起動後のモデル初期化・推論・受信プロファイルの問題で距離だけを保留する挙動とは区別する。

- 従来コマンドの既定1920×960は変更しない。
- 今回の測距を使うときだけ、運転用senderを `--motion-native`、受信側を `--motion-distance` で起動する。両側1280×720を明示し、リサイズで校正へ合わせない。
- native senderは既存の撮影readerを再利用し、撮影の読取り完了から200ms以内の新しいフレームだけを渡す。古いキャプチャの繰返し送信をしない。これはセンサ露光時刻や端末間遅延の測定ではない。
- senderの明示プロファイル、実際の受信画像寸法、PTS・受信時刻の単調性を検査する。不一致でも操縦接続を拒否せず、距離だけを保留する。
- 内部校正・床法線・高さは11/9に準備済みの実験用プロファイルを再利用する。元のPNG・床4点を新たに撮る必要はない。
- 機体固定、局所平面床、高さ・傾き一定を仮定する。ピッチ／ロール、上下動、床勾配や、取付状態のsession間一致を検証・補償したものではない。

## 表示と失効

出力はカメラ直下の床上点から可視支持点までの水平距離。車体中心からの距離、前後Z、接触距離とは異なる。距離は運転画像に点・枠として重ねず、別欄へ `source <session> frame <番号> | receive-age <ms>` と表示する。元画像や前方展開画像の現在のフレームと、過去の推論結果の対応を偽らない。

受信から500ms超、接続の切替・切断、画像／時刻の不正、推論側の異常では数値を保留する。古い数値を平滑化や保持で埋めない。複数コーンでは一意に選べず保留する。必要ならnative画素のROIを明示できるが、範囲外を監視できるという意味ではない。

運転映像の描画・操縦を距離の更新待ちで止めない。距離プロセスの停止も機体の停止命令ではない。距離をROS速度指令・ブレーキ・FFBへ接続していない。

## 検証結果

正式な記録：[verification_r03/summary.json](verification_r03/summary.json)、[テストログ](verification_r03/tests.log)、[全10画像CSV](verification_r03/cached_pipe_metrics.csv)。r01は依存ソースの来歴記録を拡張する前、r02はUI Pythonの明示指定を優先する追加試験の前の検証履歴。

|確認|結果|限界|
|---|---|---|
|今回の接続テスト|48件成功|合成画像・偽の推論器・モック通信による検査|
|関連回帰を含む合計|134件成功、失敗・エラー・skip 0|全プロジェクト・実機安全の合格ではない|
|遅い推論中にframe 1→2→3→4を受信|推論は1→4、2と3をキューへ残さない|実GPUの時間測定ではない|
|子プロセスの停止・異常、切断・session変更|距離を保留し旧結果を破棄|実機操縦の遅延は未測定|
|既存の操縦・速度指令・DataChannelの主要11構文木|commit `142aadf` と一致|処理負荷による挙動変化はこの照合では分からない|
|旧shellコマンド本体2本|バイト一致|新しいopt-in分岐は別途検証|
|既存10画像＋同frameの保存YOLO枠を実pipeへ送信|10/10で昨日の値・保留理由と一致|新規YOLO推論・実走行ではない|
|b559 f035562|1.006457m|他のb559 7枚は輪郭の探索端到達等で引き続き保留|
|df33 f061948 / f064232|0.979063 / 1.954426m|校正転用・物理精度は未検証|
|送受信の実プログラムのhelp／shell構文|成功|ROS／カメラの起動には進めない検査|

10画像は連続した走行動画ではなく、過去の疎な保存画像を使うソフトウェア比較。元のsession/frameと、新しい**オフライン再生用**session/frameをCSVで区別した。保存YOLO枠は復号画素のSHAと紐付け、他の画像へ枠を取り違えない。校正を異なる撮影へ転用した精度の認定には使わない。

元PNGはメモリ・ファイルSHA不変。運転画面のスクリーンショットや加工カメラ画像は作っていない。昨日の7枚の保留を解決したとは扱わず、経路追加が距離の結果を変えていないことを確認した。

## 後で実機を使うときのコマンド

以下はユーザー本人が実行するための手順で、本作業では実行していない。既存の停止・安全手順を維持し、**まず静止・停止状態で**表示と入力を確認する。新たな録画やSキー保存は必須でない。運転用sender／受信器は1組だけ起動し、昨日の `motion-receive` や `--diagnostic` を並行起動しない。

### GPU PC：普段の運転用UIのROS環境を使う

普段の運転UIで使用しているPythonを `THETA_UI_PYTHON` に指定する。明示した場合は旧 `src/theta-env` への自動再実行を無効にしてその指定を優先する。`yolo-env` にROS／PySide6を追加インストールする前提にはしない。必要な依存を持つGPU Pythonは別に指定する。

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_UI_PYTHON="$(command -v python3)"
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"
MOTION_OUT="Experimental_results/2026-11-10/driver_motion_live_$(date +%Y%m%d_%H%M%S)"

bash src/start_theta_receive_rtc.sh --motion-distance \
  --motion-python "$THETA_DISTANCE_PYTHON" \
  --motion-weights "$HOME/Downloads/cone_distance_v03.pt" \
  --motion-profile Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json \
  --motion-output-dir "$MOTION_OUT" \
  --motion-experimental-rigid-mount
```

重みは以前と同じ指定SHA-256のローカルファイル、実推論はCUDAのみ。モデルの自動ダウンロードやCPUへの暗黙fallbackはしない。`--motion-experimental-rigid-mount` は未検証の仮定への明示指定で、物理精度の承認ではない。

例は前方の左魚眼全体を対象にする。複数コーンで `ambiguous_front_cones` となる場合は、対象の枠中心が入るnative画素範囲を `--motion-target-roi X1 Y1 X2 Y2` で指定できる。左右は画像の座標で、車体左右ではない。ROI外を通過した物体は監視しない。動くコーンの追跡・全障害物への最短距離算出は今回の実装範囲ではない。

### matsunuc：通常の操縦DataChannelを残すsender

普段のsenderと同じROS環境を使い、今回の動画分岐に対応したコードを反映してから実行する。IP・デバイスは既存接続に合わせる。

```bash
cd ~/theta_ws
export THETA_RTC_PYTHON="$PWD/theta-env/bin/python3"
bash src/start_theta_stream_rtc.sh --motion-native \
  --receiver-ip 150.89.169.78 --device /dev/video0 --fps 30
```

**今回は `--diagnostic` ではない。** `--motion-native` は既存 `webrtc_stream.py` のcontrol/telemetry経路を使う。両側の画像サイズを1280×720に一致させる。展開後の表示は従来の描画関数をその寸法で生成するため、実機で見え方の確認も残る。

距離用の床モデルはGPU子プロセスが起動時に読むのでLキー不要。新しい距離用のキー入力も設けない。WASD等の既存キーは操縦機能なので、測距操作のつもりで押さない。Q／画面を閉じる操作は従来の運転UIの終了で、独立した機体停止の代用ではない。

## 出力・障害の見方

`$MOTION_OUT` に以下を保存する。カメラ画像は保存しない。

- `motion_distance_frames.jsonl`：元のsession/frame、支持点、全仮説、距離・保留、受信後経過時間と推論時間。
- `motion_bridge_events.jsonl`：戻った数値が現在sessionと500ms条件を満たしたか。古い推論結果が計算ログに存在しても表示採用したとはみなさない。
- `motion_engine_summary.json` / `motion_profile_used.json`：GPU、重み、config、実際の床プロファイル。
- `driver_motion_summary.json`：終了時の処理件数、破棄数、子プロセス・I/Oスレッドの終了状態。
- `motion_worker_stderr.log`：GPU依存やモデル初期化のエラー。ここに問題があっても操縦プロセスを自動再起動しない。

画面に `motion_native_sender_profile_missing_or_mismatch` が出た場合、旧senderや診断senderのままである可能性がある。運転接続はそのまま距離のみ保留する。寸法・時刻不正で失効した場合は、そのsessionを黙って復旧させず、新しい正規接続で再確認する。

## 再現

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-10/driver_motion_bridge_r01/verify.py \
  --output-dir Experimental_results/2026-11-10/driver_motion_bridge_r01/verification_r04
```

新しい出力先を指定する。内部の `--cached-worker` はこの検証専用の保存枠再生であり、運転用コマンドの推論fallbackではない。正式な実行経路は `src/driver_motion_process.py` のCUDA推論のみ。

次の実機確認は推論追加による負荷・操縦／映像遅延、走行中の更新率と保留率。まだ距離の接地・精度・動的な傾き補償を完了していないため、距離を制御・制動・FFBへは接続しない。今回はGit commit/pushは実施していない。
