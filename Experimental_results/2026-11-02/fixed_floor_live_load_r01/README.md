# 同じRTC接続内で固定床の比較モデルを明示読込み

2026-11-02。撮影できない日のオフライン実装。**距離の本判定・物理精度・走行・FFBの承認ではない。**

同日続報：[床画像からのモデル導出コマンド](../fixed_floor_derivation_r01/README.md)を追加した。下記は導出済みモデルを包む従来手順として残す。新規の格子画像または明示四隅JSONから、`derive_fixed_floor_live_bundle.py`で直接`prepared_floor.json`まで作れる。実機成功・物理精度は引き続き未確認。

## 何が変わったか

以前は、床画像を保存してモデルを作っても、受信を再起動するとsessionが変わり、そのモデルが拒否された。[先行の設計](../fixed_floor_contiguous_replay_r01/next_live_model_lifecycle.md)に対し、既定OFFの`--fixed-floor-reload-file`とGUIの**Lキー**を追加した。

- 同じ接続を維持したまま、ローカルファイルを明示的に一度読む。ファイル変更の自動監視やネットワーク書込みAPIはない。
- 読込みは非同期・最大1件。読込み済みバイト列を使い、適用時に変更後のファイルを読み直さない。
- session、camera/config、既存モデルの型・hash・未承認flag、同じ受信フォルダにSキーで保存した無加工PNGのframe/名前/hashを検査する。
- モデル完了後に**受信された処理対象画像**からだけ適用する。推論中に最新画像が進んでも、先に受信した画像へ遡及適用しない。
- 既存支持点の3フレーム品質確認と500 ms上限は維持。基準距離と別の`fixed_floor_shadow`に比較値を記録する。
- 新しいL要求で旧モデルを直ちに失効。読込み失敗でも旧モデルへ戻らない。再接続・入力途切れ/鮮度切れ・終了時も失効する。

| 状態 | 比較モデル | 操作・遷移 |
| --- | --- | --- |
| waiting | 未適用 | 同接続で床PNG・候補モデルを準備してL |
| loading | 未適用 | 非同期で最大512 KiBの通常JSONと最大16枚のnative PNGを検査 |
| ready | 未適用 | 読込み完了後に受信した画像を待つ |
| active | 比較専用 | 毎frameの支持点品質・鮮度を別途検査 |
| rejected | 未適用 | 理由を確認し、必要なら明示的に再要求。自動復帰しない |

**ファイル・sessionの照合は、床が正しいことの証明ではない。** 板の平置き・剛性・カメラ静止は操作者の申告であり、画像から自動認定しない。モデル・接地点・絶対距離の物理検証、base_linkへの実測変換は未完了。`physical_metric_verified=false`、`floor_contact_verified=false`、`usable_for_ffb=false`を維持する。

## 実装範囲と未実装の境界

読込み・worker境界での適用・来歴記録・標準report検査を追加した。元の距離式、支持点抽出、scene推定、RTC、校正、ROS/FFBは変更していない。指定しなければモデル読込みthread/eventファイルを作らない。

**この機能は床モデルを推定する機能ではない。** `prepare_fixed_floor_live_bundle.py`は、別途導出済みの同sessionモデルへ保存PNGの来歴を付けるだけで、法線fit・高さ推定・sessionの付替えは行わない。現在の実機用モデルが自動的に用意されるわけではない。

比較値はJSONL/report専用。既存GUIの主距離が`WITHHELD`のままでも、この比較ログとは矛盾しない。比較距離の画面描画は今回追加していない。

## 後日使う場合の手順（今日は実行しない）

前提：静止したカメラ、同接続の床根拠、専用GPU環境。古いモデルのsessionを現在値に書き換えて使わない。

### GPU/ハンコンPC：受信を先に開始

未使用の出力フォルダを使う。指定モデルファイルは起動時には存在しなくてもよい。`--headless`とは併用不可。別受信器を同じ5002番ポートで起動しない。

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"
FLOOR_RUN="Experimental_results/2026-11-02/floor_load_live_$(date +%Y%m%d_%H%M%S)"
./start_cone_distance.sh receive \
  --weights "$HOME/Downloads/cone_distance_v03.pt" \
  --target-roi 270 0 350 720 \
  --colour-support-shadow --support-completion-shadow --frame-evidence \
  --fixed-floor-reload-file "$FLOOR_RUN/prepared_floor.json" \
  --output-dir "$FLOOR_RUN"
```

日付は実施日に変更する。matunuc側の映像送信コマンドは変更なし。両側を停止/再接続するとsessionが変わるので、その場合は新しい根拠が必要。

### カメラ/Kobuki PC（matunuc）：映像を送信する（11/4追記）

**受信を起動しただけではカメラ映像は届かない。** 受信側はそのまま待機させ、以下を`matunuc-NUC13ANHi5`のターミナルで実行する。GPU/ハンコンPCや解析PCでは実行しない。機体は静止のまま、ROS/FFBは起動しない。

以下はGPU受信PCのLAN側IPが以前と同じ`150.89.169.78`、キャプチャdeviceが`/dev/video0`の場合。違う場合は実際の値へ置き換える。

```bash
cd ~/theta_ws
export THETA_RTC_PYTHON="$PWD/theta-env/bin/python3"
bash src/start_theta_stream_rtc.sh --diagnostic \
  --receiver-ip 150.89.169.78 \
  --device /dev/video0 \
  --fps 30
```

受信PCのIPは**GPU/ハンコンPC**で`hostname -I`、deviceは**matunuc**で`v4l2-ctl --list-devices`により確認できる。別PCに接続されたカメラや、同じキャプチャのmetadata用deviceを選ばない。`bird_eye.py`や別の送信器で同じカメラを同時占有しない。

`--diagnostic`は先頭に1回だけ指定する。通常モードでは1920×960等へ経路が変わるため、この1280×720距離診断とは混ぜない。既定の接続ポートは5002。送信側の`ICE completed`だけでなく、GPU側のウィンドウに実際の映像が出ることを確認する。まだモデルを用意していなければ`WITHHELD`や比較パネルの待機表示は想定内で、Lはまだ押さない。

**上記の旧受信例を既に実行した場合**、受信を止め直す必要はない。現在のモデル読込み先は`$FLOOR_RUN/prepared_floor.json`である。[後続の導出コマンド](../fixed_floor_derivation_r01/README.md)で`$FLOOR_RUN/floor_model_r01/prepared_floor.json`へ生成した場合は、コマンド成功後、GPU側の別ターミナルで同じ既存`FLOOR_RUN`を指定し、未使用の読込み先へバイト同一で複製する。

```bash
cp -n -- "$FLOOR_RUN/floor_model_r01/prepared_floor.json" "$FLOOR_RUN/prepared_floor.json"
cmp -- "$FLOOR_RUN/floor_model_r01/prepared_floor.json" "$FLOOR_RUN/prepared_floor.json"
```

symlinkではなく通常ファイルを使う。`cp -n`は既存ファイルを上書きしないため、`cmp`で不一致になった場合はLを押さず確認する。今はまだ生成前なので、この複製操作は不要。別ターミナルでは`FLOOR_RUN`を新しい日時で再生成せず、受信中の実際のフォルダへ合わせる。保存先の日付prefixが旧日のままでも、修正のために接続を切らず、終了後に11/4実施分として索引・解析先を整理する。

### 同じ受信接続を維持してモデルを用意

受信GUIでSを押し、床基準のnative PNGを保存する。**受信は止めない**。別ターミナルで、その画像から別途導出・確認したモデルを準備する段階が必要（今回のexporterは導出を代行しない）。

その後、同じGPU PCの別ターミナルで以下の形式を使う。`FLOOR_RUN`は実際の既存受信フォルダ、`SAME_SESSION_MODEL`と`FLOOR_PNG`は実在する同sessionのファイルへ置き換える。2枚以上なら`--evidence-png`の後に列挙する。

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"
"$THETA_DISTANCE_PYTHON" src/prepare_fixed_floor_live_bundle.py \
  --models "$SAME_SESSION_MODEL" \
  --evidence-png "$FLOOR_PNG" \
  --board-on-floor --rigid-board --static-camera \
  --output "$FLOOR_RUN/prepared_floor.json"
```

3つの確認flagは事実を確認してから使う。出力は新規ファイル限定で、既存ファイルを上書きしない。再試験時に同じ名前を再利用するなら、旧ファイルを別名で保管してから、新規出力する。

### Lで受入れ、ログを確認

受信GUIにフォーカスしてLを押す。ターミナルに`load_requested`、`ready`または`active`が出る。readyは短時間なら表示を飛ばすことがある。失敗時は`reason`と`detail`を確認する。

保存先：

- `fixed_floor_model_events.jsonl`：要求・受入れ・失効・拒否・終了、generation、bundle hash、根拠frame、受入れframe/時刻。
- `distance_frames.jsonl`：処理frameごとの`fixed_floor_load`、受入れ後の`fixed_floor_shadow`。比較値は支持点品質/鮮度不成立なら保留。
- `live_summary.json`：終了状態。読込みjobが残れば`model_load_running=true`、`shutdown_complete=false`で未完了と記録する。

Q/Ctrl+Cで終了後、従来のreportコマンドを実際の受信フォルダへ実行できる。reportの状態件数は**処理frame数**であり、Lを押した回数ではない。要求回数はeventsを確認する。読込み受入れと物理距離のPASSは別。

## 検証の範囲

正式結果は[verification_r04/verification.json](verification_r04/verification.json)：**309件PASS、failure/error/skipとも0**。新規26件を含む。元画像/モデルの入力hash、意図した4ファイル以外の既存src、変更前snapshot、旧再生のhash、旧1,547行の読取りはすべて一致した。

`verification_r01`は途中で中断、`r02`は309テスト成功後に検証器自身の相対パス処理で停止したため、最終判定に使わない。パス処理を修正した`r03`が全チェックPASS、その後のsummary有効flagの整合修正も含めた`r04`を正式版とする。過去のmanifestは上書きしていない。テスト中の意図した不正引数・未完了cleanup・欠落入力のERROR/WARNING出力は負例試験であり、結果表のfailure/errorは0。

新規テストは、既定OFF・二重要求・不正ファイル・別session/config/hash・画像改変・完了後frame限定・推論中の最新frame更新・再接続・失効・終了・GUI L経路を、合成画像/仮想入力で確認する。実worker threadも通すがGPU/実カメラではない。

保存実画像2枚（旧sessionのframe1259/1655）は**元バイトを変更せず**、既存3床モデルと来歴付きbundleを作れるかだけ検査する。別sessionでは拒否される。新しい床推定・独立した距離正解・ライブ測距成功の検証ではない。

再現コマンド（新しい出力先を指定）：

```bash
cd /home/robo25/theta_ws/RICHO-theta
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-02/fixed_floor_live_load_r01/verify.py \
  --output-dir "Experimental_results/2026-11-02/fixed_floor_live_load_r01/verification_$(date +%Y%m%d_%H%M%S)"
```

今回意図して変更した4ソースは`source_snapshot/`に変更前を保存。古い再生manifestは書き換えず、そこに記録された旧hashはsnapshotに照合する。他の既存srcファイルは基準commit`ccf5665`のままであることも確認する。

今日は撮影・実機操作・依存導入・Git commit/pushを実施していない。作業中の赤のみ評価フォルダとテストも変更していない。
