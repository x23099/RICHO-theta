# コーン測距・FFB開発 引き継ぎ資料

更新日: **2026-10-30（JST）**。対象リポジトリ: `RICHO-theta`。
この資料作成時の基準commitは **`5791a80`（1030v2、main）**。作成前の作業ツリーはclean、ローカルの`origin/main`参照も同commitだった。リモートへの再照会・pushはしていない。

> **2026-10-30 追記（引き継ぎ後の作業）**: [明示固定床モデルの隔離診断](Experimental_results/2026-10-30/floor_pose_fixed_mode_r01/README.md)を実施した。背景6平面に依存せず、session内の紙法線＋明示高さから条件付き水平距離を出す候補を`src/cone_fixed_floor_candidate.py`へ隔離実装した。新規12テストPASS、既存制御経路は未変更・未接続。frame1655の3モデルは既存比較値を1e-9 m以内で再現し、frame1259も補完shadow点(299,385)から1.404～1.527 mの範囲を得た。ただしモデル間差約12 cm、±1 px対照約4.7 cm、物理精度・接地点・yaw・ライブ連続出力は未確認のまま。`WITHHELD`、距離本判定、FFBは変更していない。次の判断は、このモードを既定OFFの比較ログへ接続するか、独立した物理基準を先に得るかである。


## 1. 最初に読む要約

**最終目標は、カメラでコーン等を検出し、位置・距離・相対運動から危険を判断して、G923へFFBで通知すること。現在の最優先は「静止状態でのコーン距離の継続出力」。まだコーン測距完成・走行FFB完成とは扱わない。**

引き継ぐ際に最も重要な区別:

| 項目 | 到達点 | まだ言えないこと |
| --- | --- | --- |
| 旧・青箱HSV→TTC→G923 | 停止試験と低速走行で物理振動を確認済み | すべての距離・TTCが正しい、コーンにもそのまま接続済み |
| YOLOコーン検出 | 自前単一クラスモデルあり。現GPU PCで実推論済み | 見えるコーンを全条件で検出・正しい床接点を特定できる |
| コーン距離の録画後再計算 | 条件付きの距離出力と比較結果あり | 録画間の幾何転用、現在の実機測距精度が保証される |
| 現在の静止リアルタイム経路 | 映像受信と実GPU推論まで確認済み | 距離表示の成立。10/30受領ログでは出力0/5,427件 |
| 新しい支持点候補 | 保存画像で改善。明示指定で比較ログへ保存・集計可能 | 本来の距離判定への採用、物理接地・距離精度の保証 |
| 次の主課題 | **支持点の物理的意味と、現sessionの床姿勢の与え方を分けて詰める** | 閾値を緩めれば解決、TFを足すだけで解決 |

直近の作業詳細は[比較ログ追加・連続回帰](Experimental_results/2026-10-30/cone_completion_logging_r01/README.md)。
古い資料に「未接続」とある場合は、その時点の状態である。**現在は比較ログに接続済みだが、本来の距離判定には未接続**という最新状態を優先する。

再開時は[AGENTS.md](AGENTS.md)を読み、まず`git status --short`と直近の結果を確認する。資料・コードは存在しても、録画・重み・venvは別PCへ自動的には移らない。

## 2. ここへ到達した流れ

### 2.1 青箱とFFB経路の開発（8～9月）

当初は青箱をHSVで抽出し、床投影から距離・追跡・TTCを計算した。録画の整合性検査、オフライン再計算、回帰登録、ワンコマンド解析を整備。カメラ取得は1280×720 MJPG・30 fpsへ統一した。

その後G923への物理FFBを段階的に導入。手動command→録画再生→実カメラ→疑似ODOM→実ODOMの順で、送信・停止・watchdog・体感を検証した。PC間の時計差でcommandが拒否される問題があり、receiver発行challengeを使う鮮度確認と独立relayへ移行した。

9/29のv12では、個々のtoken鮮度60 msとstream断200 msを分離した。80 msの古いtokenで送信を通す変更ではない。送信は見送るが、短い断だけで1秒の安定待ちをやり直さない。200 ms超の断やreceiver session変更では再安定化する。WARNING三連、UNKNOWN単発を実G923で確認した。

根拠: [9/29日報](Daily_reports/2026-09-29_daily_report.md)、[v12実装](Experimental_results/2026-09-29/phase5_v12_reliability_implementation.md)。

### 2.2 低速走行で「通信が通る」と「測距が正しい」を分離（10/6～7）

実Kobukiのdry-runとhardware試験を実施。録画評価窓ではactive配送欠落0・adapter fault 0、停止を確認した。一方でr03は距離・認識が乱れ、WARNING三連の正常再現とは異なる通知が出た。

床反射だけを原因と断定せず、輪郭・支持点・距離変化・追跡速度の整合を診断。**ハンコンが振動した実績と、正確な危険判断の成立を混同しない**ことが現在の切り分け方針につながった。

根拠: [10/6日報](Daily_reports/2026-10-06_daily_report.md)。

### 2.3 対象をコーンへ拡張、YOLO学習へ（10/12～15）

ユーザーの優先対象は赤コーンと将来の白線逸脱。黄色コーンも同じ`traffic_cone`クラスで維持する方針を確認した。自前のTHETA dual-fisheye画像で学習・レビュー・追加負例・検証を進めた。

共用GPU PCのdriverは変更せず、専用`yolo-env`内でtorchをdriverと互換な版へ変更。GPU PCは再起動後に利用可能となった。動作中の環境へsetupを不用意に再実行しない。

友人提供の`cone.pt`・白線`.pth`も受領したが、それを現在の標準モデルとして無条件採用していない。撮影条件・画角・定義の異なるモデルは別の検証対象。現在の起動は自前モデルのhashを要求する。

根拠: [10/12日報](Daily_reports/2026-10-12_daily_report.md)、[10/14日報](Daily_reports/2026-10-14_daily_report.md)、[10/15日報](Daily_reports/2026-10-15_daily_report.md)。

### 2.4 距離方式と校正を切り分け（10/15～21）

静止コーン、床のV字テープ、白紙7点、床とコーンを同じ姿勢で撮った録画を利用。ユーザー提案のbbox占有率、仮想ピンホール、既知幅37.5 cm・高さ73 cmも比較した。

- 占有率は`Z=k/sqrt(q)`を比較。別録画の名目2.00 mで約1.779 mとなり、遮蔽でも不安定なため、この単純方式は共通方式として見送った。占有率が常に劣ると一般化した結果ではない。
- 魚眼から仮想ピンホールへ変換しても、同じ校正・光線を使えば幾何は一致する。変換自体は校正・姿勢・物理点対応の誤りを解消しない。
- 既知寸法法は台座の向き、可視先端/下端が実寸の両端に対応するか、などが残った。
- 実A4格子から前方レンズのKB4角度モデルの内部校正候補を作成。紙だけのr01と、平らな板に貼ったr02/r03を区別した。
- 白紙基準から得た床回転は条件付き候補。別録画への無条件転用には偏りが残った。

根拠: [10/19日報](Daily_reports/2026-10-19_daily_report.md)、[10/21日報](Daily_reports/2026-10-21_daily_report.md)。

### 2.5 同じ録画の背景から姿勢を求める経路とリアルタイム化（10/22～28）

背景の鉛直構造に対応する線を単位光線へ変換し、方向を支持する平面群からカメラのup方向を推定する方式を診断。過去のみの2枚学習＋2枚検証、scene周期、非同期処理、最新フレームのみの受信、再接続・終了ログを整備した。

10/26の順序再計算では、床→コーン系列1,547フレーム中326件で条件付き距離を出力。静止1.3 m区間の出力中央値1.3259 m、2.0 m区間1.9743 mだった。ただし別の中央1.3 m録画は姿勢不足で0件。**一部録画での成功を全録画・実機へ一般化できない**。

matunucに接続されたカメラの映像をGPU PCへ送る既存RTC経路を流用。ただし距離用の診断経路は、通常の1920×960等の表示経路と混ぜず、native 1280×720を保持する別profileにした。

根拠: [10/23日報（10/22分を含む）](Daily_reports/2026-10-23_daily_report.md)、[10/26最新再計算](Experimental_results/2026-10-26/cone_distance_report_r03/README.md)、[10/27実行時修正](Experimental_results/2026-10-27/cone_distance_runtime_r01/README.md)、[10/28キャプチャ復帰処理](Experimental_results/2026-10-28/rtc_capture_recovery_r01/README.md)。

### 2.6 現USBキャプチャで実映像は復帰、距離は0件（10/30）

以前のNo Signal/長いread停止と、現在の距離保留は別問題。ユーザーが**USBキャプチャ機器のみ交換**したところ実映像が復帰した。THETA本体、取り付け、向きは変更していないとの確認済み。

受領した実GPUログの5,427処理フレームでは、YOLO推論まで成立したが距離出力0。主な独立阻害要因は次の2点だった。

1. 元の赤＋黄一括マスクで背景・床が混ざり、切り出し枠端に輪郭が触れる。枠端接触3,985件。
2. 背景からの姿勢初期化が0件。全5,427件で姿勢が得られていない。

ユーザーには床に既存チェック板を置いた2枚を提供してもらい、紙外周と同sessionのコーンを解析。小さい2画像だけでは内部校正誤差と角読取り・床姿勢誤差を分離できず、校正は変更しなかった。

色分離候補、さらに左右だけの枠接触を限定的に扱う候補を別系統で実装。**最後の作業で、その候補を比較ログと標準reportへ接続した**。本判定への昇格はしていない。

根拠: [実GPUログ解析](Experimental_results/2026-10-30/cone_distance_live_r01_analysis/README.md)、[床板解析](Experimental_results/2026-10-30/floor_board_pair_r01/README.md)、[直近の比較ログ実装](Experimental_results/2026-10-30/cone_completion_logging_r01/README.md)。

## 3. PC・実行環境・役割

| PC | 役割・path | 注意 |
| --- | --- | --- |
| `matunuc-NUC13ANHi5`、ユーザー`matunuc` | カメラ/Kobuki PC。`~/theta_ws`、`theta-env/bin/python3`。直近IP `150.89.169.201` | カメラ送信をここで起動。録画は従来`~/theta_ws/src/recordings/`の日付別もある |
| `hsr-Alienware-m16-R2`、ユーザー`hsr` | GPU/ハンコンPC。コーンrepo `~/yopi_ws/RICHO-theta`、ROS workspace `~/yopi_ws`。直近IP `150.89.169.78` | RTX 4070 Laptop GPU、driver535.309.01、torch2.7.1+cu118。モデル/RTC依存は専用`yolo-env` |
| 現在の解析PC `robo25` | `/home/robo25/theta_ws/RICHO-theta`。幾何/テスト用Python `/home/robo25/theta-env/bin/python3` | 学校の実機PCと混同しない。ユーザー申告RTX3070、ローカル推論環境もあるが直近は保存bboxを再利用 |

IP・device番号は過去の確認値なので実施時に確認。ROSを使う旧経路では両実験PCともdomain **88**。**現在のコーン距離診断はROS・ODOM・FFBを必要としない**。

重みの直近GPU PC配置例: `~/Downloads/cone_distance_v03.pt`。元の学習出力名は`runs/cone/train_ab_augmented_v03_local_20261014_r01/yolov8n/weights/best.pt`。名前やpathだけで同一と判断せず、下記hashを照合する。

## 4. 現行の仕組みとファイル対応

### 4.1 実行経路

```text
matunuc: THETA → USBキャプチャ → native 1280×720 MJPG取得
                 ↓ 映像専用RTC / VP8（通常profileとは別）
GPU PC: 最新の復号フレーム → YOLO bbox → 元の赤＋黄支持点抽出
                           ├→ 同session・過去のみの背景姿勢推定
                           ├→ 品質/姿勢/鮮度/床交点の条件 → 条件付き距離表示
                           └→ 色分離/左右補完候補 → 比較ログのみ（距離へ入れない）
```

YOLOは対象の枠を出す。OpenCVは色支持列、線・姿勢・幾何等を担当する。役割が異なり、どちらか一方を削れば同じ機能が軽量に残るという設計ではない。

実装上の床交点はKB4単位光線と変換行列による計算。仮想ピンホール比較は別診断にあるが、**現在のコーン受信CLIはROS tf2へ変換を問い合わせたり、測量済みbase_link TFを配信したりしない**。

旧青箱FFBは`bird_eye.py → intent → collision_ffb_relay.py → command → ハンコンPC adapter → G923`という別経路。旧経路の実績を新しいコーン受信CLIの機能として説明しない。

### 4.2 主要ソース

| ファイル | 読む箇所・役割 |
| --- | --- |
| [start_cone_distance.sh](start_cone_distance.sh) | `receive` / `replay` / `report`の入口 |
| [src/theta_rtc_frames.py](src/theta_rtc_frames.py) | native profile、最新フレーム、受信側ローカル時計 |
| [src/theta_rtc_diagnostic.py](src/theta_rtc_diagnostic.py) | 映像専用send/receive/probe。新しい撮影だけを送る |
| [src/run_cone_distance_live.py](src/run_cone_distance_live.py) | GPU受信、GUI、Sキー保存、終了summary、2つの比較フラグ |
| [src/cone_distance_worker.py](src/cone_distance_worker.py) | `YoloConePredictor`、latest-only処理、scene future、session/終了管理 |
| [src/cone_distance_core.py](src/cone_distance_core.py) | `load_config`、`select_front_boxes`、`observe_support`、`ConeDistanceEngine.measure` |
| [src/cone_scene_diagnostic.py](src/cone_scene_diagnostic.py) | `estimate_scene`、`infer_up`、`PastOnlyPose` |
| [src/cone_support_quality.py](src/cone_support_quality.py) | 画像支持列の3フレーム確認、欠測・変形・時間間隔の判定。物理接地の保証ではない |
| [src/cone_colour_support_candidate.py](src/cone_colour_support_candidate.py) | 上部seedで赤/黄を先に選び、色別に観測する比較候補 |
| [src/cone_support_completion_candidate.py](src/cone_support_completion_candidate.py) | 左右枠接触だけの二段階観測範囲。画像生成・下端補間はしない |
| [src/summarize_cone_distance_live.py](src/summarize_cone_distance_live.py) | ログ検査、条件付き距離/比較候補/終了状態を分離集計 |

### 4.3 固定条件・座標を変えない

[src/cone_distance_diagnostic_config.json](src/cone_distance_diagnostic_config.json)が基準。

| 条件 | 現状 |
| --- | --- |
| 入力画像 | 1280×720 uint8 BGR、dual fisheye、前方左レンズ。校正に合わせて画像をリサイズしない |
| 対象ROI例 | native `(270,0,350,720)`。bbox中心による対象選択であり画像cropではない。外側は監視しない |
| YOLO | 単一クラス`traffic_cone`、conf0.5、imgsz960、NMS IoU0.7、max_det300 |
| 重みSHA256 | `3a6e124adb15c16efd7d22c853406066371f48873c82f1d3cfc445b22ae5997b` |
| 内部校正候補SHA256 | `e3dede6d229bd2facfba2039f8ba541fba4563bb15a11eb44ef0f896e055da42` |
| 床変換候補SHA256 | `3b741f20ac22148e4f9f154940690d62c199467caa02037612e6aed90d55c465` |
| 出力座標名 | `paper7_ground_reference`。物理測量した`base_link`ではない |
| scene | 固定1秒周期。同方向を支持する独立6平面が必要。過去2枚学習＋後の2枚検証、方向一致2°以内 |
| pose有効期限 | 直近scene確認から1秒以内、直近結果が拒否なら出力保留。過去sessionの結果を流用しない |
| 画像品質 | 独立した支持列を3フレーム確認。0.2秒超の間隔などで再確認 |
| 撮影済み画像の送出鮮度 | 200 ms以内。これはFFB token鮮度60 msとは別の値 |
| 測距処理側の鮮度 | 受信側ローカル受信から処理完了まで500 ms以内。露光からのPC間遅延ではない |
| 診断距離範囲 | 0.2～4.0 m |
| 承認フラグ | `physical_metric_verified=false`、`floor_contact_verified=false`、`usable_for_ffb=false` |

`--colour-support-shadow`と`--support-completion-shadow`は既定OFF。明示指定すると候補とbboxをログに追加するだけ。比較の追加CPU時間も鮮度判定へ含む。候補が得られても元の`WITHHELD`を解除しない。

## 5. ユーザー確認済みの物理条件

追加で同じ質問を繰り返さず、次を基準にする。ただし申告値と画像からの推定を混同しない。

| 項目 | 確認済みの内容 |
| --- | --- |
| 距離原点 | カメラ直下／Kobuki中心として計測した、というユーザー説明 |
| レンズ中心高さ | 床から59 cm。録画設定にある58 cmと区別する |
| コーン全高 | 台座を含め床から先端まで73 cm |
| 台座 | 一辺37.5 cm。前後距離は車体側の辺まで |
| 左右±40 cm | 台座中心ではなく車体に近い内側の辺。軸に沿う配置で中心は±58.75 cm相当 |
| 白紙7点 | 車体に近い辺の**左端角**を指定座標へ合わせた。紙中心ではない |
| 10/30床板 | 白紙外周296×210 mm、格子20 mm、平らな板に貼付。板＋紙の厚さは概算15 mm |
| 10/30赤コーン距離 | 床タイル50 cmからの**概算約1.5 m**。誤差幅なし、精密実測なし |
| 取り付け | ポール・保持具で固定。写真提供・状態確認済み。高さ/傾き/固定を意図的に変更していない |
| キャプチャ交換 | USBキャプチャのみ。カメラ本体・位置・向きは変更していない |

10/30の紙2枚はsession `15ae673c24484d119952ae391df611aa`のframe1259/1655。背景の紙とコーンを同sessionで扱えるが、紙の4隅を使って推定したモデルを同じ4隅で独立精度検証したとは呼ばない。

## 6. 最新結果をどう読むか

### 6.1 現在の実機ログ

[10/30実GPUログ解析](Experimental_results/2026-10-30/cone_distance_live_r01_analysis/README.md)が実際のライブ結果。推論時間中央値6.742 ms、受信後処理完了中央値11.004 ms。一方で距離は0/5,427件だった。

このログは旧summary形式で詳細な終了メタデータがないため、現行reportでは`INCOMPLETE_CAPTURE`。終了情報を後付けして合格にしない。これだけで通信断・ログ欠損・GPU失敗を意味するわけではない。

### 6.2 同sessionの床板・幾何

[内部校正との整合監査](Experimental_results/2026-10-30/floor_board_pair_r01/intrinsic_consistency_r02/README.md)ではK/Dを固定した。

- 2枚の紙面を共有するモデルで、高さ自由なら紙面高さ545.9 mm・native再投影RMSE0.331 px。
- 外部申告高さ590−概算板厚15＝575 mmを入力固定するとRMSE0.600 px。
- 高さが約29 mm違っても予測画素の差は最大約0.642 px。この2枚で高さ・姿勢・内部校正誤差を十分に分離できない。
- 小さい紙が覆う角度は約31.9～46.7°。全画角校正を検証した結果ではない。

[同sessionコーン比較](Experimental_results/2026-10-30/floor_board_pair_r01/cone_same_session_r01/README.md)ではframe1655の候補から、床モデルにより水平距離約1.40～1.53 m。レンズからの斜距離や、測量済み車体前方距離と同じではない。概算1.5 mに最も近いモデルを選んでいない。

### 6.3 支持点の新候補とログ化

[限定的左右補完](Experimental_results/2026-10-30/cone_lateral_completion_r01/README.md): 237枠で既存225点→226点。既存点の消失/変更0。bbox±1 pxの2,133対照でも既存点の消失/変更0。人工bbox変動を新しい実撮影フレームとして数えない。

[現在の比較ログ実装](Experimental_results/2026-10-30/cone_completion_logging_r01/README.md)の最終結果:

| 確認 | 結果 | 解釈の制限 |
| --- | --- | --- |
| 関連回帰テスト | 211 PASS、失敗/エラー/skip 0 | 選択したソフトウェア試験。プロジェクト全機能・物理安全の合格ではない |
| 過去6録画 | 3,596フレーム、従来判定差0 | 同じ論理時計で比較。scene推定は未起動 |
| 新旧の点あり | 双方3,261フレーム | 実接地・距離成功数ではない |
| 点の消失/変更 | 0/0 | 元の点を維持する設計の確認 |
| 補完の試行/追加取得 | 0/0（この6録画） | 補完が必要な連続場面の評価ではない |
| その再生での距離 | 双方0件 | 姿勢未初期化。実機で0件だった試験とは別 |
| 現2画像をログ経路へ入力 | frame1259で新規`[299,385]`、1655で既存`[300,385]`維持 | 独立静止画、保存CPU bbox。連続実GPU検証ではない |
| 過去入力・凍結コードhash照合 | 346照合、不一致0 | 意図して変更した4ソースは変更前snapshotへ照合 |

正式な参照先:

- [連続再生summary r02](Experimental_results/2026-10-30/cone_completion_logging_r01/contiguous_replay_r02/summary.json)
- [現在の2画像 results](Experimental_results/2026-10-30/cone_completion_logging_r01/current_pair_r01/results.json)
- [検証 r02](Experimental_results/2026-10-30/cone_completion_logging_r01/verification_r02/verification.json)
- [候補点数の数値グラフ](Experimental_results/2026-10-30/cone_completion_logging_r01/contiguous_replay_r02/support_availability.png)

`contiguous_replay_r01/`は欠測終端の集計不具合があった旧版。修正後に全フレームを再実行したr02を使う。`verification_r01/`の207件から、終端集計の4テストを追加したr02の211件が最新。別の日の「211件」と同一の試験集合だとはしない。

## 7. 次担当が進める順番

### 7.1 最初の着手: 床姿勢を別問題として整理

支持点候補を取れても現背景では元のsceneが6平面に届かず、距離が止まる。この問題を候補ログの件数増加で解消したことにしない。

1. 現sessionの床板解析を読み、紙からの法線、外部実測高さ、車体yaw/原点、K/D転用を別々の証拠として一覧化する。
2. 現背景の自動姿勢を使う方式と、明示した固定床モデルを使う**別の診断モード**の成立条件を検討する。固定モードは未実装であり、既存ゲートの暗黙バイパスとして作らない。
3. 床板4隅・辺の読取り、複数姿勢解、板厚・高さ感度、同sessionコーン支持点の対応を既存データで追う。yaw不明なら、まず水平距離と車体前方成分を区別する。
4. 採用する入力の根拠・不確かさ・座標名・無効化条件・session/カメラ条件の対応を明文化してから、新しい距離候補を隔離実装する。実測に近い数値だけを選ぶモデル切替はしない。

ここは**未完了の次作業の提案**であり、上記モードが既に利用可能・安全承認済みという意味ではない。

### 7.2 支持点を本判定へ採用する前の評価

1. 既存の比較モジュールは当面ログ専用に維持する。
2. 保存済みの実bbox・原画素で、補完が必要な連続場面、黄色＋同色床、小さい/遮蔽/上下枠接触/複数候補を区別して評価する。未保存bboxは当時の値として推測しない。
3. 必要なら既存録画へ新たなオフライン推論を行うが、CPU再推論・GPUライブ・人手枠の出所を分ける。新推論を過去のライブ出力そのものと扱わない。
4. 支持点が実際の台座/床接点とどこまで対応するか、利用可能な物理基準で評価する。時系列で滑らかという理由だけで正しい接地点と認定しない。

#### 7.2.1 保存データのみの支持点評価（2026-10-30 実施）

[支持点の物理的意味の評価 r01](Experimental_results/2026-10-30/support_point_physical_eval_r01/README.md)を、保存済みCSV/JSONと保存済み投影だけで実施した。新しいYOLO推論・画像再デコード・HSV再抽出・校正/姿勢fitは行っていない。`verification_r01`は`PASS_SAVED_DATA_ONLY`（focused 27テスト、入出力ハッシュ・flags・ライブ経路非変更を確認）。

- **同一session床基準との相対対応は支持できる。** 10/15は床V先端と同じX列で、1.30 mが+1 px（-1.9 cm相当）、2.00 mが0 px（+0.8 cm相当）。10/19紙角とコーン下辺は同一列で同一画素`(313,371)`。C130の参照は床候補`(310,416)`であり、コーン候補`(310,417)`と別列で保持する。
- **絶対幾何は未検証。** 支持点が名目距離の床接点だと仮定した含意レンズ高さは、10/15連続が589.9/592.7 mm、10/15静止0.80/1.30/2.00 mが531.7/502.0/446.1 mm、左右1.30 mが538.3/490.4 mm、10/19紙＋コーン2.00 mが330.6 mm。連続の590 mm一致は名目距離との整合の再表現であり、独立した高さ測定ではない。
- 10/15静止2.00 mを590 mmに合わせるには+0.645 m必要で、台座一辺0.375 mを超える。基準点の定義差だけでは説明できないが、支持点だけの誤差とも断定しない。0.80/1.30 mのoffsetは辺長以内で分離不能。
- **滑らかさは正しさではない。** 連続2.00 mの隣接frame中央値0.60 mmに対し、静止2.00 mも2.56 mmで滑らかだが446.1 mmを示す。
- 10/30固定床モデルの条件付き範囲の和集合1.403–1.528 mには概算1.5 mが入るが、590 mm入力時の1 px制御はどの単一モデルも1.5 mを含まない（primary 1.428–1.476 m）。モデル間一致でも接地証明でもない。黄色コーンは赤部分で救済せず保留のまま。
- 単一支持画素では「床からの高さ」と「奥行き」を分離できない。同一光線上の床マーカーは必要条件だが十分条件ではない。

`physical_metric_verified=false`、`floor_contact_verified=false`、`usable_for_ffb=false`を維持し、支持点・補完shadowを距離本判定へ昇格していない。次に絶対精度を進めるなら、台座基準点の測量または既知寸法対象など、独立した物理基準が必要になる。再録画・実機操作・ROS/FFB・Git pushは別承認とする。

### 7.3 リアルタイム・走行・FFBへ進む順序

1. 静止・実GPUで入力画像/選択bbox/支持点/床モデル/姿勢/鮮度の理由を同フレームで記録。
2. 静止状態の距離継続出力と、独立した実測基準に対する誤差・欠測・外れ値を評価。
3. 走行中の画像・姿勢・距離変化・処理遅延を、物理出力なしで評価。
4. TTC・危険状態・UNKNOWN・遮蔽復帰をdry-runで評価。
5. 実機条件・停止・安全ゲートを別途確認した後に、低強度のhardware FFBへ接続。

#### 7.3.1 同一フレーム証拠ログ（2026-10-30 実装、実機未実施）

[同一フレーム証拠ログ r01](Experimental_results/2026-10-30/live_frame_evidence_r01/README.md)として、7.3 step 1の記録項目を既定OFFの`--frame-evidence`へ実装した。選択bbox、支持点と下包絡、姿勢理由・up、床モデル識別子（config/camera/floor候補のSHA-256）、鮮度理由を`distance_frames.jsonl`の同一行へ記録する。距離・姿勢・接地判定は変更せず、要約は不正なbbox・支持点・承認flagを拒否する。新規11件、関連111件のテストがPASS。

**実機の静止キャプチャは未実施。** 解析PCには`/dev/video*`がなく、設定要求checkpoint `3a6e124a...`も不一致（`~/Downloads/cone.pt`は`39c94a4b...`）。GPUと`theta-yolo-env`は利用可能。実行はcheckpoint・カメラが揃うGPU PCで行い、解析PCからの遠隔操作を前提にしない。手順は[RUNBOOK.md](Experimental_results/2026-10-30/live_frame_evidence_r01/RUNBOOK.md)、変更の運搬は`transfer/frame_evidence.patch`（SHA-256 `c296d0f3...`）を使う。返送後は`flatten_evidence.py`でフレーム単位に展開する。

**現時点でユーザーに直ちに再録画を依頼する必要はない。** 保存経路・設定・座標系・同一録画の対応を調べ、既存映像から得られない物理情報が残ったときだけ、その不足に限定して相談する。録画依頼を繰り返すことをユーザーは避けたいと希望している。

白線逸脱は後段。右境界は外周二重白線の内側という意図があるが、左境界の定義は未決定。実装前に相談する。今はコーンを優先し、勝手に白線や人検出へ主題を移さない。

## 8. 再開・確認用コマンド

### 8.1 解析PC: 現状と既存結果を見るだけ

```bash
cd /home/robo25/theta_ws/RICHO-theta
git status --short
git log -3 --oneline
sed -n '1,100p' Experimental_results/2026-10-30/cone_completion_logging_r01/verification_r02/verification.json
```

成功済みの211件や全3,596フレームは、同じ入力・コードなら再利用できる。資料を読むだけのために再実行しない。

### 8.2 解析PC: ソース変更後に関連試験を再実行する場合

```bash
cd /home/robo25/theta_ws/RICHO-theta
HANDOFF_RUN_ID="$(date +%Y%m%d_%H%M%S)"
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-30/cone_completion_logging_r01/verify.py --output-dir "Experimental_results/2026-10-30/cone_completion_logging_r01/handoff_verify_${HANDOFF_RUN_ID}"
```

この検証器は旧証拠とのhash対応・保護対象も検査する。意図したソース変更でhashが変わった場合、内容を監査し、新しい検証manifestへ記録する。過去のmanifestを新しいhashで上書きして通さない。

### 8.3 既存データで再生比較を再現する場合（実機不要）

```bash
cd /home/robo25/theta_ws/RICHO-theta
HANDOFF_RUN_ID="$(date +%Y%m%d_%H%M%S)"
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-30/cone_completion_logging_r01/replay_contiguous.py --output-dir "Experimental_results/2026-10-30/cone_completion_logging_r01/handoff_replay_${HANDOFF_RUN_ID}"
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-10-30/cone_completion_logging_r01/check_current_pair.py --output-dir "Experimental_results/2026-10-30/cone_completion_logging_r01/handoff_pair_${HANDOFF_RUN_ID}"
```

これは保存検出の再利用であり、新たなYOLO推論ではない。必要なローカルデータ:

- `recordings/2026-10-15_cone_static_distance_intake_r01/`内の6session（`raw.avi` / `detections.csv` / `metadata.json`）。
- `Experimental_results/2026-10-15/cone_static_distance_r01/inference_r01/`の`frames.csv` / `predictions.csv` / `provenance.json`。
- `Experimental_results/2026-10-30/floor_board_pair_r01/originals/`の2 PNGと、同フォルダ`cone_same_session_r01/inference_f001259/` / `inference_f001655/`の`audit.json`。

### 8.4 後日の実機比較ログ採取時だけ（今すぐの作業指示ではない）

カメラ/Kobuki PC（matunuc）で映像だけを送る:

```bash
cd ~/theta_ws
export THETA_RTC_PYTHON="$PWD/theta-env/bin/python3"
bash src/start_theta_stream_rtc.sh --diagnostic --receiver-ip 150.89.169.78 --device /dev/video0 --fps 30
```

GPU/ハンコンPC（hsr）で距離診断を受ける。受信側を先に待機させてよい:

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"
HANDOFF_RUN_ID="$(date +%Y%m%d_%H%M%S)"
./start_cone_distance.sh receive --weights "$HOME/Downloads/cone_distance_v03.pt" --target-roi 270 0 350 720 --colour-support-shadow --support-completion-shadow --output-dir "Experimental_results/2026-10-30/cone_completion_live_${HANDOFF_RUN_ID}"
```

日付は実施日に合わせる。別受信プロセスと同じ5002番ポートを同時利用しない。USB機器を確認し、`/dev/video0`を固定の事実と思い込まない。`bird_eye.py`と送信器による同じカメラの同時占有も避ける。

Sキーは元画角の**無加工の復号画像**を保存する。距離表示画像やセンサーの無圧縮原本ではない。Q/Ctrl+Cで停止し、終了summaryを確認する。

同じGPU PCで集計（`HANDOFF_RUN_ID`が受信時と同じターミナル変数として残っている場合）:

```bash
./start_cone_distance.sh report --input-dir "Experimental_results/2026-10-30/cone_completion_live_${HANDOFF_RUN_ID}" --output-dir "Experimental_results/2026-10-30/cone_completion_report_${HANDOFF_RUN_ID}"
```

別ターミナルなら、**実際に生成された入力フォルダを明示する**。`--input-dir`は受信で生成された`distance_frames.jsonl`と`live_summary.json`がある既存フォルダ。`--output-dir`はこれから集計を作る未使用フォルダ。PC間転送の方向を指定する引数ではない。

## 9. よくある誤解・再発防止

- 画面の`WITHHELD`は、必ずしも映像/YOLO不通ではない。`blockers`、`colour_reason`、`scene_reason`、`pose_reason`を順に見る。
- `--target-roi`は対象選択。輪郭用bbox拡張範囲とは別であり、広げても輪郭端問題が直るわけではない。
- YOLO bboxの下端を床接点と見なさない。黄色コーンを赤いステッカーで救済しない。欠測を0 mや前回値で埋めない。
- 2枚の紙で得た法線、59 cmという申告、paper7変換は、それぞれ別の根拠。既知の正解へ合わせて校正・高さ・向きを同時fitし、独立検証と称さない。
- キャプチャ交換で内部校正が壊れたとも、同解像度だから完全に同一とも断定していない。
- RTCの`ICE completed`は接続成立であり、有効なカメラ内容の保証ではない。No Signal文字を含む映像もフレームとして流れ得る。
- native診断は1280×720。通常起動の`start_theta_stream_rtc.sh`と診断起動を混ぜず、`--diagnostic`を重複指定しない。
- 送信側のread停止許容時間と、古い画像を出さない鮮度上限は別。read timeoutを延ばしても古い画像を許可しない。
- G923の`output_active=true`はソフト側の適用記録で、物理振動の計測ではない。体感・bag・停止確認を分ける。
- reportの終了完了は距離精度のPASSではない。`worker_stopped=true`だけでscene job停止完了とは言えない。
- 過去の「未学習」「未接続」「未実施」は当時の履歴。上書きせず、最新資料との差を説明する。

## 10. 保存・Git・ユーザーとの進め方

- 結果は`Experimental_results/YYYY-MM-DD/`、日報は`Daily_reports/`。日報作成依頼があれば当日の根拠と未完了事項をまとめ、索引も更新する。
- 生録画・bag・checkpoint・dataset・venvは原則Git外。ローカル録画は`recordings/`、原archiveは`Downloads/`等。Driveにもあるが、必要ファイルの場所・hashは個別に確認する。
- 毎日の代表資料は原則2～4点。カメラ画像は切抜き・縮小・注釈・補正しない。数値グラフは生成可。
- ユーザーの明示依頼で作る距離表示付き解析画像は、別ファイルへ保存して「録画後の再計算」と明記し、無加工元画像を残す。
- 未確認画像・未保存予測をコーンなしの負例へ自動変換しない。赤/黄は現行単一クラスのまま。
- 共用GPU PCのdriverやグローバル環境を不用意に変更しない。新しいモデル・依存導入・他repo・実機操作へ範囲を広げる場合は影響を説明する。
- リモート作業時に学校のカメラやハンコンを操作できる前提にしない。操作手順には必ず「どのPCか」を書く。
- 今回の依頼は**引き継ぎ資料作成のみ**。実機起動・ソース変更・commit/pushを含まない。

### 次担当へそのまま渡せる再開依頼

> `HANDOFF.md`と`AGENTS.md`を読んで再開してください。現在は自前YOLOによる静止コーン測距の診断段階です。新支持点は比較ログに接続済みですが距離本判定へ未採用、現背景の床姿勢未成立も独立した問題です。最新根拠は10/30の`cone_completion_logging_r01`（最終replay r02、211テスト）と`floor_board_pair_r01`。まず既存データで床姿勢・支持点・座標・不確かさを分離し、明示した条件付き床モデルの診断が成立するか検討してください。元の6平面・鮮度ゲートを緩めたり、別録画の姿勢を暗黙転用したりしないでください。既存映像から得られない物理情報が残った場合だけ、その不足に限定して相談してください。録画・学校PC操作・ROS/FFB出力・Git pushは別の依頼として扱ってください。
