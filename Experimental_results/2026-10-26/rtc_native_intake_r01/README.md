# WebRTCを流用する静止測距：映像入力の分離（2026-10-26）

## 今回できた範囲

既存の `start_theta_receive_rtc.sh` / `start_theta_stream_rtc.sh` へ、
明示的な `--diagnostic` 起動を追加した。通常起動の経路・引数・車体操作は変更していない。
診断時は既存と同じ aiortc・VP8・HTTP `/offer`（標準ポート5002）の構成を用いるが、
別の映像専用エントリーポイントに切り替わる。ROS・車体操作・FFBのコードをimportしない。

**今回は映像入力まで。YOLO、場面内の鉛直推定、支持範囲判定、距離計算・数値表示は未接続。**
画面にも `INTAKE ONLY` / `Distance: NOT CONNECTED` を表示する。
これは測距完成・実機合格の報告ではない。

## 分離した理由・確認した根拠

- 既存送信シェルは1920×960を要求するが、採用中の角度校正候補は1280×720。
  単純リサイズして同じ校正を使うことはしない。診断送信はMJPG・1280×720を要求し、
  実際の全フレーム形状も送受信で検査する。不一致は停止。解像度一致だけで光学系の一致を証明はしない。
- 既存 `webrtc_stream.py` は制御DataChannelから `/cmd_vel_joy` と `/cmd_vel` へ送信する。
  診断には不要なため新経路ではDataChannelを作成しない。受信側へ来たDataChannelも閉じる。
- 既存送信はcaptureが更新されなくても送信時のPTSを更新できる。
  診断は新しいcaptureだけを取り出し、送信トラックの取り出し時点で読み取り復帰から200 msより古い画像を拒否する。
  読み取り停止・トラック停止は接続を終了する。これはセンサー露光時刻の測定ではない。
- 受信側は展開・BEV変換**前**の1280×720 BGRを容量1のスロットへ格納する。
  アプリ側の未処理フレームは最新に上書きし、独自の滞留キューを作らない。
  WebRTC codec・OS・ネットワーク内部のバッファや所要時間までゼロになる保証ではない。
  最終受信から500 ms超で表示を消し、切断・再接続では古いsessionの画像を再利用しない。
- VP8/YUVは非可逆。受信後PNGは「受信デコード画像」であり、カメラ生画像と同一とは呼ばない。
  校正座標の大きさを合わせても、輪郭・測距精度がそのまま移ると断定しない。
- NTPや2台の時計の差を使わない。CSVの時間は受信PC内のmonotonic時刻。
  `receive_to_consume_ms` は受信処理から表示側取り出しまでの時間であり、**カメラ→GPUの遅延ではない**。

実装参照：`src/webrtc_stream.py` / `src/webrtc_receive_ui.py` の既存経路と、
ローカルに導入済みのaiortc 1.14.0の `RTCPeerConnection`・`VideoStreamTrack`・VP8 codec API。
新しいパッケージ・ドライバ・モデルのインストールは行っていない。
既存送信シェルの `15M` 指定や通常画面のレイアウトは診断モードへ引き継がない。
帯域・実効FPS・画質・距離精度・遅延の改善はまだ測定していない。

## 実行する場合の手順

実機・2台間ネットワークでは未確認。まだ追加の録画や学習は不要。
まず接続して元の全画角の受信を確認するための手順。
車体を静止させ、通常の送受信を終了してから行う。同じカメラ・ポート5002を二重起動しない。
ハンコン、Kobuki起動、ODOM、ROS_DOMAIN_ID設定はこの映像専用モードには不要。

### 1. GPU PC（受信側）

RICHO-thetaの更新を反映後、そのリポジトリのルートで実行する。
普段のWebRTCが動作するPython環境を有効にする。
`~/yopi_ws/start_theta_receive_rtc.sh` など**別リポジトリの古いシェルではなく**、
今回更新したRICHO-thetaの `src/` 配下を使用する。

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_RTC_PYTHON="$(command -v python3)"
"$THETA_RTC_PYTHON" -c 'import cv2, numpy, av, aiortc, aiohttp; print("RTC imports OK")'
bash src/start_theta_receive_rtc.sh --diagnostic \
  --output-dir Experimental_results/2026-10-26/rtc_native_intake_r01
```

上の出力先は**新規**ディレクトリを指定する。再試験時は `r02` などへ変え、既存の結果は消さない。
GUIを出せない場合は `--headless --duration-sec 20` を追加できる。
headless時は表示とキーによるPNG保存はない。
`THETA_RTC_PYTHON` は任意のPython選択用で、未設定なら `python3`。
この段階はYOLO/GPUを使用しないため、YOLO専用venvに切り替える必要はない。
importに失敗した場合、共用環境を変更せず普段WebRTCで使用しているPythonのパスを確認する。

### 2. matunuc / Kobuki PC（送信側）

こちらも更新したリポジトリのルートで実行する。これまでの配置が `~/theta_ws` なら以下。
GPU PCのIPは現物で確認する。既存シェルのデフォルト値を現在のIPだと仮定しない。

```bash
cd ~/theta_ws
export THETA_RTC_PYTHON="$(command -v python3)"
"$THETA_RTC_PYTHON" -c 'import cv2, numpy, av, aiortc, aiohttp; print("RTC imports OK")'
read -r -p "GPU PCのIPv4アドレス: " THETA_GPU_IP
bash src/start_theta_stream_rtc.sh --diagnostic \
  --receiver-ip "$THETA_GPU_IP" \
  --device /dev/video0 \
  --fps 30
```

通常の `start_theta_stream_rtc.sh` と異なり、診断引数は `--receiver-ip` 等の名前付き引数。
**両側とも `--diagnostic` が必要**。通常送信のofferは診断受信側で拒否する。
旧受信側は新しいprofileを返さないため、診断送信側も接続を終了する。
LAN内の直接接続専用でSTUN/TURNは使用しない。信頼したLAN以外へ公開しない。

### 3. 確認・終了・提出するもの

- GPU PCで、左右の魚眼が含まれる1280×720の全画角を確認する。展開済み映像ではない。
- `native_transport_only_distance_not_connected` が正常な**入力確認中**の状態。
  距離が表示されないのは今回の未接続範囲であり、検出失敗の判定ではない。
- キーボードの `S` で、その時の受信デコード画像を無注釈PNGへ保存できる。
  画面上の説明文は別の表示用コピーで、保存PNGへ入れない。
  同じフレームのPNGは上書きしない。画像名のsession/sequenceをCSVへ対応付ける。
- matunuc側をCtrl+Cで終了すると、受信側は古い映像を維持せず黒背景・停止理由へ切り替わる。
  GPU PC側は `Q` またはCtrl+Cで終了する。
- GPU PCの `received_frames.csv`、`intake_summary.json`、任意の `decoded_*.png` が確認資料。
  元のカメラ録画を代替するファイルではない。
- `intake_summary.json` のstatusは入力診断の種類を示すだけであり、距離・実機・FFBのPASS判定ではない。

## 次の実装

ネットワーク受信loopとは別の処理workerへ、既存の校正・現在フレームのYOLO結果・台座支持範囲・
同一sessionの過去のみで初期化する場面姿勢を接続する。
結果は使用フレームのsession/sequenceと結び、古い結果を新映像へ重ねない。
初期化未了、場面推定処理中・期限切れ、支持範囲不成立などは数値を出さず理由を表示する。
現在の受信コードへ同期的にYOLO/場面解析を足してイベントloopを停止させない。
この接続後に、静止した実カメラ入力の距離と処理時間を確認する。
FFB接続や走行確認はその後の別段階。

## カメラなし検証

再現コマンド（ROSノード・カメラ・HTTP listener・実通信は起動しない）：

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 \
  -m unittest discover -s tests -p test_theta_rtc_diagnostic.py -v
bash -n src/start_theta_receive_rtc.sh src/start_theta_stream_rtc.sh
```

プロファイル拒否、実解像度拒否、コピー/無注釈保存、容量1の上書き、古い画像・重複PTS拒否、
切断/再接続、遅れて戻る旧session、capture停止、既存シェルの明示分岐、ROS等への非依存を検証する。
実際のaiortc VP8 encoder/decoderもメモリ内で確認し、寸法とメディア時刻（90 kHz換算で最大1 tickの丸めを許容）
が保持される一方で画素値は一致しないことを確認する。PTSを送信元capture番号や2台間の絶対時刻として扱わない。
ネットワーク・GPU・カメラ・光学系・測距精度の実験結果としては扱わない。

今回の最終結果は新規26テスト＋既存capture-property 2テストがPASS、Python構文・シェル構文・
`git diff --check` がPASS。詳細と検証したファイルのハッシュは `verification.json` を参照。
