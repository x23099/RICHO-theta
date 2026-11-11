# コーン測距・FFB開発 引き継ぎ資料

更新日: **2026-11-11（JST）**。対象リポジトリ: `RICHO-theta`。

## 11/11後続：比較内の診断コピーを削減、GPU r03の速度確認待ち

[最新手順](Experimental_results/2026-11-11/guarded_compact_compute_r01/README.md)。既存の通常APIは独立したdeepcopy・両bbox policyを維持し、比較stream内部だけがcompact経路を選ぶ。毎回元画素から新規抽出した同一呼出し内の診断graphを読み取り専用で共有し、half-pixel以外の未使用policy・不要な深いコピーを省く。棄却は別top-level dictへ行う。主ログ観測・前フレームの借用や、比較頻度・thread数の変更ではない。engineの結果コピー、stream外へ返す所有権、500ms鮮度、参照失効、主行再現・自己領域棄却、主測距・操縦・ROS・FFB未接続を維持。

元8画像のfull/compact全値一致、CPUカーネルP50 60.31→50.26ms（16.7%短縮）、P95 74.97→61.67ms。最大値87.90→107.20msで一律改善ではない。8ケースの再帰を含むdeepcopy呼出し128156→28794、画像観測は8→8のまま。接続後の関連290テスト全成功、GPU r02の比較320行（数値40）を新runtime＋模擬時計で全再現。実子／pipe／比較threadの元8画像再生も主8/8一致・比較1.142471541888944m・別session拒否・元画素不変・正常終了。正式記録は同フォルダbench_r01／checks_r01／gpu_rows_replay_r01／pipe_replay_r01。

GPU効果・30fps達成は未確認。次は今回の8ファイル限定 `recordings/2026-11-11/guarded_compact_update_r01.patch`＋manifestをGPU PCへ反映し、既存CUDA試験を新しい `recordings/2026-11-11/guarded_cuda_gpu_r03` へ保存する。旧r01/r02は保持。旧パッチ再適用不要。同じ更新がGitで既に入っていれば重ねず、reverse --checkで確認。手順はスマート引用符を避ける絶対パス表記へ変更した。カメラ・matunuc・ROS・走行・画面録画は不要。

今回runtime4ファイルに比較専用compact経路を追加。主測距の既定observer・距離式は変更なし。このPCで実CUDA・実機は起動せず、commit/push・日報作成なし。前回GPU r02監査の未commit変更は保持。旧コードSHA固定の監査結果は履歴として扱う。

## 11/11後続：二重抽出削減のGPU効果を確認、比較ONは約23.9件/秒

[最新GPU監査](Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r02/README.md)。ユーザーが `guarded_cuda_gpu_r02.tar.xz` を提出。開始HEAD `882c6ae`（1111v3）、clean。元入力25・依存24を照合し、前回との差は予定したruntime2ファイルだけで、更新の反映を確認できた。パッチ適用／Gitのどちらで反映したかの再質問や重ねての適用は不要。

今回の主640＋setup4＋warmup8＋比較322行と両pin画素・参照・終了を照合。今回のOFF/ON320組は検出枠・主判定一致。前回r01との比較でも検出枠・主判定640/640、比較の値・理由・flags322/322が一致。主640は保留画像の反復で全件保留、比較40数値は元14922の1.142471541888944mだけ。独立精度検証ではない。両writer正常終了、slot上書き／tap失敗なし。

GPU上の比較ONの主処理P50は45.69→33.51ms、P95は67.23→55.59ms、測定blockの件数/秒は20.05→23.86。33.33ms超過は201/320→166/320（51.88%）。比較service P95は64.45→34.96ms、入力から比較完了までP95は177.46→93.67ms。OFFは主処理P50約22.51ms・29.74件/秒でほぼ同じ。改善は確認したが、比較ONの30fps維持や通信込みの実遅延は未認定。

次は保存データで残る辞書コピー等の仕事量・比較実行頻度を調べる。**追加撮影、同じ未変更コードのGPU再試験、パッチ再適用は今は不要。** 現時点で実機が必須になったとはしない。比較側の負荷対策後にGPU確認→現在カメラの静止映像へ進む。今回runtime・主表示・ROS・FFB・環境の追加変更なし、commit/push・日報作成なし。rawは `recordings/2026-11-11/guarded_cuda_gpu_intake_r02/`、根拠は上記results_r01。監査parserは明示r02 root対応を追加し、関連11テスト成功。

## 11/11後続：比較の同一フレーム二重抽出を削減、GPU速度の再確認待ち

[最新手順・根拠](Experimental_results/2026-11-11/guarded_compute_reuse_r01/README.md)。比較関数で元画素から独立に得た現在観測をbaseline距離の再現にも使い、比較側だけの上側補完抽出を2回→1回に削減した。主ログ観測や前フレームの再利用ではない。`MotionRangeEngine.measure` にper-call observerを追加し、通常主測距は既存defaultを維持。frame順序・500ms鮮度・box選択・幾何・主行との再現照合、参照pin/load/失効、自己領域棄却は残す。主表示・操縦・ROS・FFBへの比較接続なし。

このPCの8画像CPUカーネル測定ではP50 103.88→61.78ms、P95 127.41→78.57ms、観測呼出し16→8回。GPU PCでの改善量・30fps達成ではない。新候補の8ケース完全一致を確認し、runtime接続後の関連276テストを再実行して全成功。GPU提出比較320行（数値40行）を新runtime＋模擬時計で全て再現。実子／pipe／比較threadの元8画像再生も主8/8一致・比較1.142471541888944m・別session拒否・元画素不変・正常終了。正式記録は同フォルダprofile_r02、checks_runtime_r01、gpu_rows_replay_r01、pipe_replay_r01。

次はGPU PCへ今回の6ファイル限定 `recordings/2026-11-11/guarded_compute_reuse_update_r01.patch`＋manifestを反映し、既存CUDA試験を新しい出力先 `recordings/2026-11-11/guarded_cuda_gpu_r02` で実行してもらう。既に反映済みなら重ねてパッチを適用しない。カメラ／matunuc／ROS／走行／画面録画は不要。旧r01は保持し、コード変更後の速度・主判定一致・比較鮮度を再確認する。未変更試験の無意味な繰返しではない。

今回実CUDA・機体の起動、commit/push・日報作成なし。前回監査と資料の未commit変更を保持。GPU提出監査の「runtime変更なし」は監査当時の記録で、今回の比較側変更と区別する。既存古いhash固定監査を変更後ソースでそのまま再実行して一致すると案内しない。

## 11/11後続：実CUDA再推論を照合、比較ONは約20件/秒で負荷対策が先

[最新のGPU監査](Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r01/README.md)。ユーザーが `guarded_cuda_gpu_r01.tar.xz` を提出。開始HEAD `84173b3`（1111v2）、clean。主640行、setup4、warmup8、比較322行と両pin画像を直接照合。元入力25／依存24のSHA再確認、新しい検出枠による異なる8入力のCPU幾何を全主行・比較結果へ照合。OFF/ONの320組は検出枠・主判定とも一致。主640行は保留標本なので全て保留、比較数値40行は元14922を反復した1.142471541888944mだけ。40独立実測ではない。両比較writer正常終了、slot上書き／tap失敗なし。実CUDAはGPU提出記録で確認、このPCでモデルを起動したわけではない。

**性能合格ではない。** 主処理P50/P95はOFF22.69/27.07ms、ON45.69/67.23ms。測定blockの件数/秒はOFF29.58、ON20.05。33.33ms超過は3/320対201/320。最後のOFFで戻るが、GIL／OpenCV thread／CPU等の原因分離は未了。tap単体はP95約0.033msで、比較の仕事量・同一プロセス資源共有を先に監査する必要がある。元画像を変えたり主判定を緩めたりしない。

次は**追加撮影ではなく保存画像で比較側の負荷内訳・重複計算を調べ、対策候補を検証**。今すぐmatunucや静止カメラを要求しない。今回と同じ未変更GPU試験の再実行やパッチ再適用も不要。対策後にGPU再検証、その後現在カメラの静止負荷確認。以下の「実CUDA待ち」「次は初めてカメラ」は準備時点の履歴で、この性能結果を優先する。

監査の新規9テスト成功、rawは `recordings/2026-11-11/guarded_cuda_gpu_intake_r01/`、根拠JSON／CSVは上記成果物results_r01。運転runtime・主表示／ROS／FFB／制御・環境の変更なし、今回commit/push・日報作成なし。

## 11/11後続：保存画像の実CUDA再推論試験を準備（GPU実行待ち）

[最新手順](Experimental_results/2026-11-11/guarded_cuda_replay_r01/README.md)。本日はこのPC＋GPU PCのみ、matunuc使用不可。GPUの保存枠再生は完了しており再実行不要。次は新規standaloneの `cuda_replay.py` で保存native8枚を毎回YOLOへ通す。既存CUDA専用predictor／主測距engine／比較workerを使用し、運転runtimeの変更なし。OFF→ON→ON→OFF各160回、warmup8＋setup4は別記録、上限30回/秒。元画素は変更しない。新しい再生IDのみ除外して座標／confidence／主判定を対応比較する。

ローカルは合成predictor＋実threadの新規22テスト成功と元8枚の事前照合まで。実CUDA／カメラ／ROS／車体操作は未実施。正式記録は同フォルダ `checks_r02`、実データ事前照合は `recordings/2026-11-11/guarded_cuda_preflight_r02/summary.json`。既存198テスト成功は対象ソースSHAで再利用し、再実行扱いにしない。GPU PCへは新規6ファイルだけの `recordings/2026-11-11/guarded_cuda_update_r01.patch`＋manifestを渡す。以前の13ファイルパッチは再適用しない。主／比較JSONLとpinを含むGPU出力フォルダ全体を提出してもらう。

この試験で物理精度、通信込み遅延、実カメラでの負荷は認定しない。実CUDA結果を確認後に現在カメラの静止映像が必要になる。比較値を主表示・ROS・FFB・制御へ接続しない。今回commit/push・日報作成は未依頼のため未実施。

## 11/11後続：GPU PCの再生も成功、matunucは本日使用不可

[GPU提出物の監査](Experimental_results/2026-11-11/guarded_gpu_cached_audit_r01/README.md)。ユーザーはこのPC＋GPU PCのみ使用可能。matunucがないのに送信や実カメラpinを依頼しない。GPUで実行した非同期比較の保存データ再生を提出し、主ログOFF/ON計16行・bridge16行、主判定8/8一致、元入力SHA23・依存SHA13、両子／I/O終了を照合した。比較writerも8行・snapshot1枚・正常終了を記録。比較約1.1424715mはsummary記録と検証済みソースが一致するが、比較側JSONL／pin PNGは今回archiveにないため直接読取り認定はしない。追加提出は不要。

summaryのFileNotFoundErrorは意図的な別session参照拒否試験。実処理失敗ではない。GPU PCの再生は完了で、再実行・パッチ再適用を求めない。実CUDA／実カメラは未実行。さらにカメラなしで進める場合は、保存画像の実YOLO再推論・追加負荷確認を別試験として準備可能。実映像確認はmatunucが使える日に行う。

今回開始時のHEADはユーザー側で整理された `8e5172b`（1111）、worktreeはclean。以下の未commit／未push・GPU未反映は作業時点の履歴。監査でruntime変更・新たなcommit/pushなし。

## 11/11：比較専用workerの接続と保存画像の実pipe検証を完了

[最新実装・正式検証](Experimental_results/2026-11-11/guarded_async_comparison_r01/README.md)、[GPU PC反映・実カメラの静止手順](Experimental_results/2026-11-11/guarded_async_comparison_r01/live_procedure.md)を優先する。ユーザーは「カメラが必要な段階まで」の継続を依頼し、GPU PCは使用可能と回答済み。GPU PC／カメラ／ROS等をこちらから起動してはいない。

`--motion-comparison-dir`で既定OFFの専用daemonへ、主結果のpipe送信後に元画素と不変JSONLを渡す。最新待ち1枚、別比較ログ、端末pin/load/invalidate/status、保存／ログ／要求上限・終了を追加。load完了前に受信済みの待ち画像も使わない。主表示・主IPC・操縦／ROS／FFBへの比較値接続はなし。GPU子内でCPU資源を共有するため実機の負荷はまだ未確認。

正式198テストPASS、実子・pipeによる保存8画像の比較OFF/ONで主結果8/8一致、比較は後続14922対応の1.1424715mだけ。別session load拒否、元画素不変、両子／I/O・比較writer終了確認。保存枠による明示的オフライン再生であり、新規YOLO推論・実カメラ・実機走行ではない。r02が正式記録、r01は追加試験／状態表示の補強前の履歴。

次はGPU PCへの反映後、現在カメラ接続を静止状態で通常受信し、端末pinで天板境界の読めるnative1枚＋同名JSON／statusを取得する。校正マーカー・実測・走行は今は不要。pin後は同接続を維持して現在の参照JSONを用意しloadする。過去参照のsession書換え転用はしない。

今日はGit commit/push未実施。GPU反映用13ファイル限定パッチ `recordings/2026-11-11/guarded_async_update_r02.patch` とmanifestを用意し、基準49f5c40への正向きdry-runと現worktreeへの逆向きdry-runを確認する。`git pull`だけで本日の機能が入ると案内しない。別作業collision_risk.py／test_collision_gradient.pyは保持・対象外。日報は終了依頼時に作成する。

## 11/10終業：日報・Git保存と明日のリモート再開

ユーザーの終了依頼により研究作業を終了し、[本日日報](Daily_reports/2026-11-10_daily_report.md)・[代表資料4点](Experimental_results/2026-11-10/report_assets/README.md)・最新の監査／prototype／テスト結果をcommit・push対象に整理した。最終commit IDとpush成否はGit履歴／終了報告を参照。以下の各作業時点の「commit/push未実施」は履歴である。別作業 `src/collision_risk.py` と `tests/test_collision_gradient.py` は保持し対象外。

明日はこのPCで比較専用worker・pin/loadイベント・別JSONLの非同期接続と保存画像再生から再開でき、直ちに実機必須ではない。実装／再生完了後にGPU PCへ反映し、まず静止実映像の追加負荷を確認、その後現地監視下で低速走行。GPU PCへの遠隔接続と元ログ／画像／重み／環境の保持を準備する。カメラを使える状態なら静止確認まで進められるが、無人遠隔走行は前提にしない。主測距・操縦・ROS・FFBの接続範囲は変えない。

## 11/10後続：比較ストリームの参照管理を実装、live接続は次段階

[実装・検証・次の接続範囲](Experimental_results/2026-11-10/guarded_stream_lifecycle_r01/README.md)。新規 `src/cone_guarded_stream_comparison.py` は単一ownerの状態管理prototypeで、live entry pointへ未接続。同じ接続で明示pinした元画素と参照PNGのSHA／復号画素を照合し、activateより後のframeだけ比較する。入力途切れ・再接続・鮮度切れ・比較失敗で失効。元判定・操縦・ROS・FFBは変更しない。旧オフライン依存コードのSHAも維持。

新規25＋既存関連54＝79テスト成功。既存16,929行の元時刻によるID受付は16,928、起動時遅延1行を拒否。実画素8枚では参照前6枚と当該14604には数値なし、後続14922だけ1.1424715m。14604で参照読込み可能だったと仮定した録画後の模擬ストリームで、実機の読込み時刻・実時間性能を証明しない。未保存画素の再計算なし、後の参照による遡及適用0。

次は容量1の比較専用worker、pin／明示loadイベント、別JSONLへの非同期接続と保存データ再生。主測距IPCとRTC／操縦threadへ比較の重い処理を入れない。追加撮影やユーザー操作は今は不要。Git commit/pushなし。別作業collision_risk.pyとtest_collision_gradient.pyは保持・対象外。

## 11/10後続：GPU PCの録画後比較も一致を確認

[提出結果の監査](Experimental_results/2026-11-10/guarded_gpu_result_audit_r01/README.md)。ユーザーがGPU PCで既存17:12録画の比較手順を実行し、summary／比較JSONLを提出。JSONLはこのPCとバイト一致、summaryはPC固有パス以外一致。入力23・解析コード8の記録SHAと、このPCの対応実ファイルの再hashも一致。元判定8/8再現、比較候補は14922の1.1424715mだけ。**この比較コマンドと依存コードのGPU PC実行は確認済みであり、以下の「GPU PC未反映」は追加当時の履歴。** GPU PC全体のGit状態や別の終了待ち修正の反映までは未確認。

同じ録画後比較の再実行・追加撮影は不要。改良候補はリアルタイム表示へ未接続で、物理精度・接地・制御の承認ではない。次は主測距を維持した比較専用リアルタイム経路の設計・接続検証。同session参照の取扱いと失効を明示し、新sessionへ参照を書換え転用しない。既存データ／模擬入力から進める。今回Git commit/push・実機操作なし。別作業のcollision_risk.py変更は保持した。

## 11/10後続：独立した録画後比較ログのコマンドを追加

[最新の比較ログ・手順](Experimental_results/2026-11-10/guarded_comparison_log_r01/README.md)。新規 `src/run_guarded_recording_comparison.py` が、正常終了した自動保存画像と元ログを読み、別の新規出力先へ `comparison_frames.jsonl`／summaryを作る。**リアルタイム比較ではない。** 録画中の起動では`--wait-sec`でwriter終了まで待ち、その後一度だけ比較。受信UI／測距workerにhookやimportを追加していない。

同じindex・元ログで検証された参照session/frame/PNG SHAを必須にし、新sessionへの自動転用・書換えbindingを禁止。profile/config／baselineを再現し、不完全保存・参照不一致・入力変更・出力上書き等を拒否。別session混在行は比較距離なし。元画像／ログを書き換えず、比較値は画面／IPC／ROS／制御へ返さない。

提出済み8組で8baseline再現・1比較数値（14922、1.1424715m）を確認。前の6画像には後の参照を使った `reference_used_posthoc=true` を明記。新規24テストPASS。**GPU PCへ未反映、commit/push未実施。** 既存の17:12提出物はこのPCで処理済みなので、同じ検証のための追加撮影は不要。新sessionの参照対応を必要に応じて通常の自動保存画像から確認することと、実機の正式表示へ適用することを混同しない。

## 11/10後続：自己領域棄却＋bbox下端半画素の統合候補

[最新の統合比較](Experimental_results/2026-11-10/guarded_lower_edge_shadow_r01/README.md)。新規 `src/cone_guarded_lower_edge_shadow.py` はオフラインのみ。既存のseed／閉鎖輪郭／空間support条件を維持し、左右・上端は元bbox内、下端だけ `y2 < point_y <= y2+0.5` の場合に限定して候補を得る。baseline／候補の両方を自己領域棄却に通し、元点・距離・校正を変更しない。新規15テストPASS、liveからのimportなし。

境界から離れた19保留は全てframe14922～14942内、候補点[312,407]、下端不足0.0476～0.4673px。直前・直後の元数値も全19件で同じ点・同じ計算値1.1424715m。前後は検証専用で候補生成に使っていない。元画像があるのは14922のみで、残り18件はログ条件一致まで。保存8画像の統合再計算では天板に隠れた5枚を保留し、14922の候補だけ残した。

全16,929行のログ上の影響は既存数値9,325維持＋189自己領域棄却、新規候補19、比較数値合計9,344。未保存189行を誤測距、未保存18候補を実測正解と断定しない。次は同session参照を明示した比較専用出力への接続準備であり、正式表示・制御への適用ではない。**距離判定は今回もlive未変更。GPU PCへ未反映、commit/push未実施。**

## 11/10後続：8.13秒の数値／保留交互区間を確認し、終了待ちを局所修正

[最新時系列・終了待ち検証](Experimental_results/2026-11-10/motion_boundary_timeline_r01/README.md)。frame14172～14416の連続244処理行に、天板境界近傍の数値189件＋同境界近傍での保留55件がまとまり、source差8.1333秒、数値→保留／保留→数値が各10回。全244行をbridgeが採用。直後14417で境界から離れた数値へ戻る。GUI点滅時間や実物の運動を測ったわけではない。別の19境界保留は境界から離れた候補を持つが、元画像があるのは14922だけで、全面救済は未採用。

終了点検では、子がstdoutの応答を返さずSIGTERMを無視／終了処理が遅い場合、I/O threadのreadが戻らずfinallyのtimeoutへ進めない経路を模擬で再現。`src/driver_motion_bridge.py` のcloseを2秒grace＋対象の測距子だけkill＋1秒waitへ局所修正し、強制終了・未完了をsummaryで明示。模擬3条件とも停止確認、新規終了8を含む関連80＋時系列8＝88テスト成功。実際の17:12実行の終了原因を確定したものではない。

**GPU PCへ未反映、commit/push未実施。距離の計算・保留条件・操縦／ROS通信は未変更。** 自己遮蔽・bbox丸めの候補は引き続きオフライン。旧資料の「runtimeを一切変えていない」は解析時点の履歴で、今回の終了待ち局所修正と区別する。

## 11/10後続：自己遮蔽の棄却専用比較を追加（live未適用）

[自己遮蔽と座標境界の分離](Experimental_results/2026-11-10/self_body_boundary_shadow_r01/README.md)。同sessionの台座が見えるframe 14604から、天板上端の暫定native座標をx=260～380だけ明示。元画像は変更せず、別JSONで参照PNG SHAと範囲を固定。新規 `src/cone_self_body_shadow.py` はオフラインの棄却専用で、全support列をチェックし、別session／未照合／範囲外では救済しない。新規15テストPASS。

保存8画像×3候補×余白0/1/2/4/8px＝120組で、現行は0→0数値、半画素候補5→1、外向き整数化候補6→1。天板に隠れた5枚を通さず、14922の1.1424715m候補は点・値とも維持（正解距離ではない）。現行の全数値9,514件にも同じ境界を読み取り適用し、189件（frame14172～14416、約0.6227～0.6506m）に境界近傍の支持列を確認。ただし数値行の元画像は未保存で、189件を誤測距／遮蔽と断定しない。

**live測距・操縦は変更していない。** 近距離の一律cutoff、隠れた接地点の補完、過去値による穴埋めは未追加。次はこの既存ログの189数値行と保留列の時間対応、およびbridge終了summaryのタイミング点検を進められる。今回の参照は汎用自動検出でも独立接地正解でもないため、そのまま実機へ適用しない。

## 11/10 17:12実行：自動保存8組を実データで検証済み

[最新解析](Experimental_results/2026-11-10/driver_motion_171250_review_r01/README.md)。ユーザーがGPU PCで保存ONを実行し、session `4c34c8c3d6d44949afb2e921e819e563` の測距ログと別フォルダの保留画像を提出。画面録画なし。16,929件・29.824件/秒、輪郭境界78件＝8保存＋70間隔skip。8組全ての元ログ／PNG／sidecar／復号画素照合と保存writer正常終了を確認。下記の「GPU PC未反映」は準備時点の履歴であり、再度未導入扱いにしない。ただしbridge summary時点では子・I/Oの停止未確認で、writer完了とは区別する。

現行観測を8/8完全再現。座標境界の比較候補は5～6枚に数値を出すが、うち5枚は台座手前側が天板に隠れ、候補点y=459が遮蔽境界付近に並ぶ。**数値増加だけを根拠に丸め候補をlive採用しない。** 14922は台座の見える比較例として別扱いするが実測正解なし。次は追加撮影ではなく、この保存8枚で自己遮蔽とbbox画素境界の扱いを分離するオフライン検証、およびbridge終了summaryのタイミング点検。距離・操縦のruntimeコードは本解析では変更していない。

## 11/10後続：走行中測距確認と保留frame保存の準備

[実走行ログ解析](Experimental_results/2026-11-10/driver_motion_live_analysis_r01/README.md)を参照。ユーザーが通常の運転画面で走行し、session `7f33c225af3948c2aa61d66d52765c2e` の全55,906処理ログを提出。走行録画対応569件では29.89件/秒、数値549件、支持輪郭境界による保留20件。19個の表示値がログと一致した。実測誤差・操縦遅延は未認定。下の「実走行未確認」は実装時点の履歴。

追加撮影なしで20保留の座標境界／下側拡張を比較したが、liveの判定緩和は未採用。次の不足入力は保留frameの未展開画素であり、再校正や追加寸法測定ではない。[既定OFFの保留frame PNG＋判定JSON保存](Experimental_results/2026-11-10/withheld_frame_evidence_r01/README.md)を実装し、新規24＋回帰48＝72テスト成功、保存ONの実ローカルpipe再生で10/10同値・7組の画素／ログ照合と正常終了を確認した。新しい実カメラ撮影・CUDA推論・実機操作は行っていない。

有効化はGPU PC受信コマンドへの `--motion-withheld-evidence-dir recordings/...` の明示追加。既定は輪郭境界の保留のみ、最大40組、間隔1秒、PNG＋JSON計128MiB。今回の変更はまだGPU PCへ反映・Git commit/pushしていないため、先にコード反映が必要。sender／操縦／距離の値と保留条件は維持する。初回再生r01の終了不備は修正済みで、正式記録はr02。次担当は上記手順・検証を優先し、古い静止校正や追加撮影の依頼から再開しない。

## 11/10の再開後：運転映像から測距への分岐を実装

[最新の実装・手順・検証](Experimental_results/2026-11-10/driver_motion_bridge_r01/README.md)を先に読む。昨日「未実装」だった運転用受信映像からの分岐を、既定OFFの `--motion-distance` として追加した。別GPUプロセスへ最新の生画像だけを渡し、運転画面とは別の数値欄に元session/frame・受信後経過時間を表示する。senderは運転用control/telemetryを維持する `--motion-native`。旧コマンドと操縦／ROS速度指令の処理は維持する。

送受信の明示opt-inではネイティブ1280×720を要求し、既定の1920×960へ校正をリサイズ流用しない。既存画像10枚＋保存YOLO枠を実ローカルpipeへ通し、昨日の距離／保留理由と全件一致した。詳細は上記の検証記録を参照する。距離の出力は引き続き3枚、保留7枚であり、検出精度を改善した結果ではない。

実機・ROSノード・カメラ・RTC待受け・CUDAは起動していない。次は推論追加後の実GPU負荷・映像／操縦遅延・走行時の更新率／保留率の確認。新しい録画を開始の前提にしない。距離の物理精度・接地・姿勢変動補償は未確認で、制御・FFBには接続しない。本日の開始依頼ではGit commit/pushはしていない。

## 11/9最終追記：現在の優先順位

途中の引き継ぎ依頼は不要となり研究を継続した。その後、本日の終了・日報・commit/pushを依頼された。以下の旧第0章は途中時点の履歴であり、特に「来歴確認→静止幾何→走行」の順序を現在の着手条件にしない。

- 追加撮影は一旦なし。現在フレームの支持点から水平距離を出す実験用 `motion-receive` を追加し、37テスト成功。既存画像＋保存検出枠は10枚中3枚で距離出力、7枚保留。実機走行・CUDA連続動作は未確認。
- [最新の日報・第13章](Daily_reports/2026-11-09_daily_report.md)、[走行向け実装・検証・手順](Experimental_results/2026-11-09/cone_motion_evaluation_r01/README.md) を先に読む。
- 映像送受信とハンコン操縦の併用はユーザーが実施済み、通信はROSとの回答済み。併用実績そのものの再確認を求めず、距離推論を追加した負荷・遅延・動く支持点の更新を対象にする。
- 次は**既存の運転用受信画像を測距へ分岐する実装**。現時点では未実装。独立した診断用受信器による運転経路の置換ではない。従来の既定1920×960と校正済み1280×720の座標整合を、リサイズによる仮定なしで扱う。
- 制御・ROS速度指令・FFBへの距離接続は行わず、カメラ固定と局所平面床を仮定した表示／記録実験に限定する。精度・接地点・左右は未承認のまま保持する。
- 本日の関連解析・実装・日報をGit保存対象に整理。raw録画・重み・venv・別作業の赤のみ評価を新規追加しない。push結果は終了報告とGit履歴を参照する。

## 0. 11/9途中時点の再開入口（履歴）

ユーザーはここで実験解析を終了し、別の作業場所／チャットで継続できるよう本資料の更新と日報を依頼した。**今この資料を読んだだけで実機を起動せず、再開の依頼を受けてから下記へ進む。** 11/2以前の追記や第7～8章は履歴・参考であり、現在の最初の作業指示ではない。

- 最新の日報：[2026-11-09](Daily_reports/2026-11-09_daily_report.md)。
- 最新の結果：[外角・点順・背景移動・同一画像4点の追加検証](Experimental_results/2026-11-09/wide_floor_geometry_r01/continuation_report.md)。
- 初回の床4点計算：[初回幾何診断](Experimental_results/2026-11-09/wide_floor_geometry_r01/README.md)。最初のP0姿勢を後半へ固定した結果で、最新の同一画像4点計算とは別条件。
- 撮影済みの手順と提出対応：[撮影手順](Experimental_results/2026-11-09/wide_floor_reference_capture_r01/capture_procedure.md)、[画像来歴](Experimental_results/2026-11-09/wide_floor_reference_capture_r01/p0_outer_corner_intake.md)。**P0～P4は撮影済み。再撮影を最初の作業にしない。**

### 0.1 現在できたこと／まだできていないこと

小さいA4紙1枚の4隅では高さ・遠方距離が1pxの読み取りに敏感だったため、既存データと提出アーカイブを調べた。新しい独立床基準が増えなかったので、ユーザーの選択で、広く離したL字4点A～Dと独立検証点Eを撮影した。

**静止コーン測距完成・走行・FFB接続の承認ではない。** 今回の対象は床マーカーの静止画像で、YOLO推論・コーン支持点の接地認定をこの試験で検証したわけではない。

|到達点|留保|
|---|---|
|P0～P4の5条件、各2枚、計10 PNGを受領。全て1280×720、同一session|PNGはWebRTC復号画像。連続動画やセンサの無圧縮RAWではない|
|KB4を固定し、固定4点だけで床姿勢を計算。Eはfitに入れない|画像点は解析者の暫定候補。物理外角・固定点IDの独立レビューは未完|
|近傍の凹頂点を除き、凸頂点へ候補を限定する追検証|凸でも測った外角と証明できるわけではない|
|同一画像の4点を使う診断では中央1.40m→1.3936m、2m→1.9833m|**未確認の光線x反転仮説H2・IPPE解0**の値。実機の反転確定・精度合格ではない|
|初回と後半の背景にも約2pxの移動を確認|物理的な機体移動の証明ではない。同sessionだけで幾何不変と仮定しない|
|全24対応・両IPPE解を保持して診断|どの対応も採用していない。生光線の点順変更だけでは左右を含むEが同時に合わない|
|後半の関連66テストPASS、元画像SHA不変|選択した合成・回帰テストであり、プロジェクト全機能や実機安全の合格ではない|

### 0.2 確定した撮影・座標条件（再質問しない）

- session：`159c37ad534a4ac0b96ca69791713567`。対象は**画像左側のレンズ**。
- **全ての左右は、前進方向を向いたときの車体左右**。Eも固定点も同じ定義。ユーザーへ複数回確認済みで、観察者が向かい合った左右として解釈し直さない。
- 測った位置は**L字の2本が合流する曲がり角の外側の尖った頂点（外角）**。内角・腕の自由端・中心線へ勝手に変更しない。初版の「内角」指示は更新済み。
- 手前L字は約10cm、奥は約15cmとの申告。テープの実寸を距離の物差しに使う方式ではない。長さの違いだけで貼り直しを要求しない。
- 原点は車体中心の床投影位置。カメラ直下との一致は未測量。操作者座標はX右・Z前。既存ソルバの床座標はx前・y左・z上なので `(x,y,z)=(Z,-X,0)`。
- 固定点の予定位置：A=(−0.40,1.00)、B=(+0.40,1.00)、C=(−0.40,1.80)、D=(+0.40,1.80)m。各位置の測量不確かさは未申告。画像にA/B/C/Dラベルはなく、個々の画像点の物理IDは仮説として区別する。
- 高さ59cmは以前の申告の持越し。当日再測定やモデルfitの固定値にはしない。

### 0.3 提出PNGの対応（元ファイル名を維持）

共通名は `decoded_159c37ad534a4ac0b96ca69791713567_fNNNNNN.png`。解析PCでは `/home/robo25/Downloads/` にある。

|条件|frame番号2枚|E外角のX右,Z前（m）|
|---|---|---|
|P0：固定4点|020063、020493|Eなし|
|P1：中央|038231、038464|0, 1.40（指示への提出として受領）|
|P2：中央2m|043924、044053|0, 2.00（2mとの回答あり）|
|P3：車体左|051180、051342|−0.20, 1.40（車体左と回答済み）|
|P4：車体右|054907、055094|+0.20, 1.40（車体右と回答済み）|

初期の002502/002700も存在するが、旧配置の確認用で、正式10枚と混ぜない。入力SHAは `wide_floor_geometry_r01/results_r01/input_provenance.json` から確認できる。

### 0.4 ソース・結果・依存環境

同じ解析PCであればGPU・カメラなしで既存結果を読める。Pythonは `/home/robo25/theta-env/bin/python3`。別PCへはDownloadsの10 PNGやvenv、古い実験データがGitだけで自動転送されないことに注意。

|段階|コード（`Experimental_results/2026-11-09/wide_floor_geometry_r01/`内）|出力|
|---|---|---|
|初回、P0固定姿勢|`analyze.py`|`results_r01/`|
|凸角・全24点順|`audit_corner_identity.py`|`corner_identity_r01/`|
|背景移動・同じ画像の4点|`audit_same_frame_pose.py`|`same_frame_pose_r01/`|

これらは**オフライン解析専用**で、Lキー互換の承認済み床モデルを生成しない。`selected_solution=null`、`physical_metric_verified=false`、`usable_for_ffb=false`。原画像は変更しない。依存ソースと結果はハッシュ照合されるため、過去のmanifestを現コードのhashへ書き換えて通さない。

後半のテストは `tests/test_wide_floor_reference_audit.py`（8件）、`tests/test_wide_floor_corner_identity.py`（11件）と、既存の床姿勢・angular・床板・導出の47件、計66成功。成功済みの同一入力を日報作成のためだけに再実行しない。

### 0.5 次担当が最初に行うこと

1. `git status --short`、本節、最新レポート、11/9日報を読む。11/9後半の解析コード・CSV・テスト・本更新は未commitのまま。今回commit/push依頼はない。既存HEADは `3e680dc`（commit名`20261108`、記録日時11/9）。既存の変更を消したり一括stageしたりしない。
2. 既にユーザーへ依頼した **`intake_summary.json` と `received_frames.csv`** が届いているか確認する。まだ届いていなければ今回PNGを保存したGPU PCの同じフォルダから取得してもらう。手順の予定先は `~/yopi_ws/RICHO-theta/recordings/2026-11-09/floor_reference_wide_r01/`。実際の出力先を優先する。受信中ならQで正常終了するとsummaryが生成される。画像の再提出・追加録画は不要。
3. `intake_summary.json` のprofileと `source_sha256` をこのrepoの `src/theta_rtc_diagnostic.py`・`src/theta_rtc_frames.py` と照合する。未知のhashを一致扱いしない。CSVは今回sessionと10 frame、1280×720、時刻の対応を確認する。なおsummaryは受信器の来歴で、送信器や機器の反転設定の証明ではない。
4. 現在のローカル診断send→receive→S保存には明示的左右反転が見つからないが、学校PCと同じコードで動いたかは未確認。上記で解決しない場合のみ、THETA／キャプチャ側の反転設定等の**不足している具体的事実**に確認を絞る。ユーザーの「全て前進方向基準」という回答は再度尋ねない。
5. 外角の物理対応・画像座標系・現在のカメラ幾何を確定してから、静止コーンのライブ比較へ戻る。H2が距離に近いという理由だけで反転をruntimeへ追加しない。走行／TTC／FFBへはまだ進めない。

**左右の不整合の扱い**：H1（Eの左右対応を固定点にも仮定・生光線）は床下の解。H2（光線xだけを反転する診断仮説）は数cm以内の条件付き再現。ただし反射行列をTFの回転行列として通すこと、負の高さを絶対値にして採用すること、Eの正解値で高さ・角・モデルを同時fitすることは禁止。まだ「撮影が鏡像だった」とも断定していない。

読み取りだけの再開確認例（解析PC）：

```bash
cd /home/robo25/theta_ws/RICHO-theta
git status --short
git log -3 --oneline
sed -n '1,180p' Experimental_results/2026-11-09/wide_floor_geometry_r01/continuation_report.md
```

以下の10/30～11/2の長い追記は履歴として残す。現在の作業入口は本節0.5。

> **11/2終業整理**: [日報](Daily_reports/2026-11-02_daily_report.md)、[正式成果物索引/Git保存方針](Experimental_results/2026-11-02/README.md)、[代表資料4点](Experimental_results/2026-11-02/report_assets/README.md)を作成。ユーザーの終業依頼により日報・コード・正式成果物をcommit/push対象にした。それ以前の各段階にある「Git未実施」は作業時点の記録で、最終結果はGit履歴と終了報告を参照。再生成可能な大きい派生JSONLと途中版はローカル保持、赤のみ評価フォルダ/テストは今回も対象外。最終393テストPASSはソフト検証であり、実モデルの正のライブ連続出力・物理精度は未確認。

> **11/2 手順3：比較GUIを実装（実機成功ではない）**: [表示仕様・合成例](Experimental_results/2026-11-02/fixed_floor_display_r01/README.md)。既存fixed-floorオプション使用時のみ、映像下に260 pxの別パネルを追加。主判定はそのまま、`UNVERIFIED COMPARISON ONLY`、水平camera-foot範囲、候補の最小～最大/有効件数とbundle順先頭4件を表示し、省略件数も明記する。世代/hash/session/画像frame・受信時刻と、描画開始時500 msを再確認し、読込み中/失効/不正/古い結果の数値を残さない。GUI1280×980に対しS保存は無加工1280×720の元frameのまま。新規17件を含む関連393テストPASS、合成88行表示・実別session 1,689行の数値0を確認。保存例はすべて合成。変更は新規rendererとlive受信GUI呼出しだけで、core/worker/モデルゲート/RTC/FFBは前段から未変更。GUI変更前snapshotで旧hashを保持。実モデルと同sessionの後続データ不足は残り、実カメラでの連続測距・独立物理精度・走行は未確認。撮影/実機操作/GPU/ROS/FFB/Git commit/pushは未実施。

> **11/2 手順2：実モデルの正の連続評価は未完了と判明**: [実ログ負例＋合成入力の機能検証](Experimental_results/2026-11-02/fixed_floor_lifecycle_replay_r01/README.md)。モデル生成に使ったsession `15ae...`は保存PNG1259/1655のみで、調査したローカル録画ログに同sessionの後続行なし。2枚を複製して3frameにせず、別sessionへ転用もしなかった。実r02 `f860...`の1,689行は3要求すべてsession不一致で拒否し比較出力0・元項目差0。新規合成セッション180行ではモデル導出→正規validator→読込み→品質確認→数値→遮蔽/600 ms/不正読込み/入力断の保留を検証し、正式88行で比較値、新規16テストPASS。既存360件は使用ソースhash一致を確認して再利用（再実行ではない）。正式結果`results_r04`・検証`verification_r02`。実機の距離精度・ライブ連続出力の成功ではなく、手順2全完了とも扱わない。今日は撮影不可なので再録画依頼はしていない。不足は同接続で床基準より後に取得したコーン観測。撮影なしでさらに進めるなら、比較専用GUI（手順3）を実機検証と区別して実装できる。既存runtime/校正/FFB/元画像は未変更、Git commit/pushは未実施。

> **11/2続報：手順1「床画像→モデル作成→L読込み」を接続**: [導出コマンド・手順](Experimental_results/2026-11-02/fixed_floor_derivation_r01/README.md)。新規`derive_fixed_floor_live_bundle.py`は既存KB4/IPPEを再利用し、明示床板ROI内の格子、または保存PNG/hash/観測四隅/実寸のJSONから未選択の平面候補を作り、Lキー互換ファイルまで出力する。格子不検出で自動fallbackしない。外部高さと紙面推定＋板厚は別条件、辺対応と複数平面解も保持する。旧PNG2枚から16候補を生成し、旧4隅法の8平面解を1e-9未満で再現。同session読込み・別session拒否・再接続失効を仮想frameで確認、新規21件を含む関連360テストPASS（[正式検証](Experimental_results/2026-11-02/fixed_floor_derivation_r01/verification_r03/verification.json)）。旧3モデルの更新や物理精度改善ではない。元画像・既存runtimeは未変更。仮想GUIテストのasyncio executor終了待ちだけを即時stubへ修正し、旧テストhashはsnapshotで保持。次は手順2の保存時系列で読込み前後の比較挙動を評価する段階。格子経路の実床板でのライブ成功、比較GUI描画、独立した物理精度は未確認。追加撮影・実機/GPU/ROS/FFB・Git commit/pushは行っていない。

> **11/2後半：同接続内のモデル読込みを実装**: [実装・手順](Experimental_results/2026-11-02/fixed_floor_live_load_r01/README.md)。既定OFFの`--fixed-floor-reload-file`＋GUI Lで、別途導出済みの同session床モデルを非同期読込みし、保存PNG/config/camera/hash/未承認flagを照合する。読込み完了後に受信した処理対象画像からだけ、既存3フレーム品質・500 ms条件で比較ログへ適用する。推論中に最新slotが進んでも古い処理対象画像へ遡及適用しない。再要求・再接続・入力途切れ/鮮度切れ・終了では旧モデルを失効し、失敗しても戻さない。元の距離・支持点・scene・RTC・校正・FFBは未変更。**床モデルの推定そのものや比較距離のGUI描画は今回の範囲外**。来歴の一致は床/接地点/絶対距離の正しさではない。新規26件を含む関連309テスト、旧ログ1,547行の読取り、旧実画像2枚の来歴付与・別session拒否を確認（[最終検証](Experimental_results/2026-11-02/fixed_floor_live_load_r01/verification_r04/verification.json)）。実機/GPU/ROS/FFB・撮影・Git commit/pushは行っていない。次は同接続で保存する床画像からのモデル導出手順を接続し、その後に実GPU静止確認と独立した物理精度評価を行う。今日は撮影不可、赤のみ別作業は未変更。

> **11/2前半の履歴：撮影なしの連続実画像検証**: [同session・過去限定の固定床再生](Experimental_results/2026-11-02/fixed_floor_contiguous_replay_r01/README.md)を実施。10/15既存1,547frameの過去4姿勢（学習62/152、検証272/302）からモデルを10.178秒以後に限定して凍結。固定床＋元支持点で1,107、同床＋補完支持点で1,120frameに条件付き水平距離。補完のみの追加13、逆の消失0。元の動的scene判定326frameは別の前方成分・別条件で、改善率にはしない。成功既知sessionの開発検証であり実機/絶対精度/独立holdoutではない。この時点は関連283テストPASS、src変更0。受信は再起動でsessionが変わるため、床撮影→モデル作成→再起動だけではつながらないことを確認し、[同じ受信接続内のモデル受入れ](Experimental_results/2026-11-02/fixed_floor_contiguous_replay_r01/next_live_model_lifecycle.md)を設計した。この時点では未実装だったが、上の後半追記のとおり実装済み。今日は撮影不可との回答済み、追加撮影・Git commit/pushは実施していない。赤のみ評価の作業ファイルも未変更。

> **最新追記：固定床の比較ログ接続**: [固定床shadow統合](Experimental_results/2026-10-30/fixed_floor_shadow_logging_r01/README.md)を実装。既定OFFの`--fixed-floor-models`、明示support source、session/hash/3フレーム品質/500 ms条件を持ち、モデルごとの水平距離を元の距離と別項目へ保存・集計する。最新r02全1,689行で元判定差0、旧床モデルは別sessionなので全数保留。同session保存2枚も連続3フレームを捏造せず保留。数値が出る経路は合成データで確認し、関連271テストPASS。次は現在の取り付け状態と床モデルの来歴・session拘束をどう対応させるか、および不足する独立物理基準を整理する。本判定・実機測距の成功・FFB接続の承認ではない。日報は[10/30日報](Daily_reports/2026-10-30_daily_report.md)。別作業中のred_only_support_evalとそのテストは今回のGit対象外。

> **最新追記：実機r02の候補評価（2026-10-30）**: [候補の全行・時系列評価](Experimental_results/2026-10-30/cone_support_live_review_r01/README.md)を実施。色別1,636点を完全維持し、追加35件は赤の左枠接触のみ、2拡張範囲で同じ成分/支持列を確認。残る18件は上部seedの赤/黄混在（赤75.0～86.96%）で保留。支持点の隣接変化はp95 1 px・最大7 px（最大変化は既存候補にも存在）。保存3 PNGは当時の候補と完全一致するが、追加35/保留18の当該画像はなく物理接地を認定していない。正式結果`results_r02/`、関連112テストPASS、実行系124ファイル変更0。次は固定床候補の比較距離ログ設計へ進めるが、別session床モデルの暗黙転用・shadowの本採用はしない。元の支持点0・姿勢0・距離0、FFB未接続は維持。
初版の基準commitは **`5791a80`（1030v2、main）**。今回の後半統合前の基準は **`9392487`（1030v4）**。後続の固定床比較ログ、実機r02解析、日報を追加整理している。実際の最終HEADとpush結果はGit履歴および終了報告を参照する。

> **2026-10-30 追記（引き継ぎ後の作業）**: [明示固定床モデルの隔離診断](Experimental_results/2026-10-30/floor_pose_fixed_mode_r01/README.md)を実施した。背景6平面に依存せず、session内の紙法線＋明示高さから条件付き水平距離を出す候補を`src/cone_fixed_floor_candidate.py`へ隔離実装した。新規12テストPASS、既存制御経路は未変更・未接続。frame1655の3モデルは既存比較値を1e-9 m以内で再現し、frame1259も補完shadow点(299,385)から1.404～1.527 mの範囲を得た。ただしモデル間差約12 cm、±1 px対照約4.7 cm、物理精度・接地点・yaw・ライブ連続出力は未確認のまま。`WITHHELD`、距離本判定、FFBは変更していない。次の判断は、このモードを既定OFFの比較ログへ接続するか、独立した物理基準を先に得るかである。

> **2026-10-30 追記（7.2 / 7.3 step 1）**: [支持点の物理的意味の評価](Experimental_results/2026-10-30/support_point_physical_eval_r01/README.md)で、同一session床基準との相対対応は支持、絶対幾何は未検証と整理した（`PASS_SAVED_DATA_ONLY`、27テスト）。続く[同一フレーム証拠ログ](Experimental_results/2026-10-30/live_frame_evidence_r01/README.md)を実装し、実機60秒を2回取得した。[r01](Experimental_results/2026-10-30/live_frame_evidence_r01/analysis_r01/README.md)は1,656フレーム、[r02](Experimental_results/2026-10-30/live_frame_evidence_r01/analysis_r02/README.md)は1,689フレームで、いずれも基準支持点0、姿勢0、距離0。r02で接触辺を特定し、**ベージュ床がS≈81で黄色マスクに入り赤コーンと連結**していることを保存PNGで確認した。支持点0はコーン下端の不在ではなく、unionマスクの分離不良。赤のみshadowは1,636点を持つが昇格していない。`physical_metric_verified=false`、`floor_contact_verified=false`、`usable_for_ffb=false`を維持し、ROS/FFB/Git pushは行っていない。


## 1. 最初に読む要約

**最終目標は、カメラでコーン等を検出し、位置・距離・相対運動から危険を判断して、G923へFFBで通知すること。現在の最優先は「静止状態でのコーン距離の継続出力」。まだコーン測距完成・走行FFB完成とは扱わない。**

引き継ぐ際に最も重要な区別:

| 項目 | 到達点 | まだ言えないこと |
| --- | --- | --- |
| 旧・青箱HSV→TTC→G923 | 停止試験と低速走行で物理振動を確認済み | すべての距離・TTCが正しい、コーンにもそのまま接続済み |
| YOLOコーン検出 | 自前単一クラスモデルあり。現GPU PCで実推論済み | 見えるコーンを全条件で検出・正しい床接点を特定できる |
| コーン距離の録画後再計算 | 条件付きの距離出力と比較結果あり | 録画間の幾何転用、現在の実機測距精度が保証される |
| 静止リアルタイム経路 | 11/4に同接続固定床の比較値を実GUI/ログで確認。11/9は床マーカーのオフライン検証 | 距離本判定の完成、現カメラの絶対精度、走行FFBの承認ではない |
| 新しい支持点候補 | 実機r02の色別1,636・補完追加35・保留18を全行評価済み。比較ログ専用 | 物理接地・距離精度の保証なし。本判定へ未採用 |
| 次の主課題 | **既存の運転用受信画像から走行向け測距へ分岐し、推論追加後の負荷・遅延・更新を確認する** | 追加撮影や静止監査を先行条件にすること、映像・操縦の併用実績自体を再確認すること、未承認の値を制御へ使うこと |

直近の作業詳細は[11/9追加検証](Experimental_results/2026-11-09/wide_floor_geometry_r01/continuation_report.md)、[11/9日報](Daily_reports/2026-11-09_daily_report.md)。10/30の資料は支持点・実GPU初期経路の履歴として参照する。
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

### 2.7 固定床比較GUIの実機確認と、旧紙角の再評価（11/4～11/9前半）

11/4はL読込み後のGUIのtuple/list差を修正し、同sessionの比較数値を実機で確認した。upper支持点比較も記録したが、物理精度は未承認だった。11/9は既存6画像を人がレビューし、同じ自動支持点のまま紙角だけを替えると旧1/1.5/2m系列が約0.995/1.482/1.984mとなった。一方、小さな紙角の1px対照で遠方1.911～2.064mとなり、高さの不整合も残った。

サブピクセル処理や同配置の別画像で再現性が上がっても精度の独立証明にならなかった。ユーザー提出の14アーカイブ・166通常メンバーも全件が既存内容と一致し、独立した床基準は増えなかった。診断受信はS保存PNGであり、連続元動画を常時保存する実装ではなかったことも区別した。

根拠：[11/4日報](Daily_reports/2026-11-04_daily_report.md)、[人の確認座標](Experimental_results/2026-11-09/reviewed_coordinate_audit_r01/README.md)、[紙角の感度](Experimental_results/2026-11-09/paper_corner_sensitivity_r01/README.md)、[全アーカイブ照合](Experimental_results/2026-11-09/archive_reference_intake_r01/complete_batch_report.md)。

### 2.8 広いL字床基準へ移行、左右・画像間幾何を分離（11/9後半）

十字PDFの案を作った後、ユーザーがL字テープを選択。測った点が外角であると判明したため、指示の内角へ貼り直すのでなく、画像でも同じ外角を読む方針へ変更した。固定4点と別のEを分け、5条件10枚を取得した。

Eの物理左右と画像上の左右に不整合があり、角の凸性・全24点順を調べても反転なしで全Eを説明できなかった。またP0から後半には背景も約2px変化。同じ画像の固定4点から求めた床姿勢を使うと、未承認の光線x反転仮説では中央1.4m→1.3936m、2m→1.9833mとなった。成功と断定せず、受信summary/CSVによる実際の保存経路照合を次の作業として停止した。詳細は第0章。

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

## 6. 過去結果をどう読むか（10/30時点・最新結果は第0章）

### 6.1 10/30の実機ログ

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

## 7. 次担当が進める順番（旧段階の詳細・最新入口は0.5）

以下は10/30～11/2時点の支持点／固定床の開発順序。実装済み部分も含むため、この章だけを見て再実装・再録画しない。11/9の再開は0.5の既存ファイル照合から行う。

### 7.1 最初の着手: 床姿勢を別問題として整理

支持点候補を取れても現背景では元のsceneが6平面に届かず、距離が止まる。この問題を候補ログの件数増加で解消したことにしない。

1. 現sessionの床板解析を読み、紙からの法線、外部実測高さ、車体yaw/原点、K/D転用を別々の証拠として一覧化する。
2. 現背景の自動姿勢と、明示した固定床モデルを使う別の診断モードを区別する。固定床の隔離計算と比較ログ接続は実装済み。残るのは現在の取り付け条件と床モデルの来歴・session対応・物理精度であり、既存ゲートを暗黙バイパスしない。
3. 床板4隅・辺の読取り、複数姿勢解、板厚・高さ感度、同sessionコーン支持点の対応を既存データで追う。yaw不明なら、まず水平距離と車体前方成分を区別する。
4. 採用する入力の根拠・不確かさ・座標名・無効化条件・session/カメラ条件の対応を明文化してから、新しい距離候補を隔離実装する。実測に近い数値だけを選ぶモデル切替はしない。

固定床モードの最新状態は冒頭追記を優先する。比較ログの実装済みという意味であり、実機連続出力や安全承認済みという意味ではない。

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

#### 7.3.1 同一フレーム証拠ログ（2026-10-30 実機60秒まで実施）

[同一フレーム証拠ログ r01](Experimental_results/2026-10-30/live_frame_evidence_r01/README.md)として、7.3 step 1の記録項目を既定OFFの`--frame-evidence`へ実装した。選択bbox、支持点と下包絡、姿勢理由・up、床モデル識別子（config/camera/floor候補のSHA-256）、鮮度理由を`distance_frames.jsonl`の同一行へ記録する。距離・姿勢・接地判定は変更せず、要約は不正なbbox・支持点・承認flagを拒否する。新規16件、関連111件のテストがPASS。

**実機ログを2026-10-30 18:18に取得した**（[解析](Experimental_results/2026-10-30/live_frame_evidence_r01/analysis_r01/README.md)）。GPU PCのRTX 4070 Laptop、60.02秒、1,656フレーム、`live_cuda_yolo`、checkpoint `3a6e124a...`一致、clean shutdown。全行に証拠ブロックが入り、選択bboxは1個/全frame（中央値47.25×88.08 px、中心`(292.2,343.9)`、jitter 1～2.7 px）。

結果は**基準支持点0/1,656、姿勢0/1,656、距離0/1,656**。主理由は`colour_contour_reaches_roi_edge` 1,655、背景は`fewer_than_six_distinct_planes` 1,656、初回のみ976 msで`frame_processing_too_old`。色分離shadowは1,430点、左右補完shadowは1,645点（追加215）を持つが、制御支持点ではないため採用していない。接触辺は輪郭boundsを記録していないため未確定（bboxと4 px拡張から左・下を含む複数辺が候補）。

取得後に、engine内の鮮度記録とworkerの最終`frame_age_ms`が約0.02 msずれる不整合を見つけた。workerで再同期するよう修正し、検証側は取得済みログを再録画せず解析できるよう1 ms差を許容した。再取得は不要。

r02拡張（crop境界・マスク寸法・輪郭bounds・接触辺の記録）を実装し、2026-10-30 18:53に60秒再取得した（[解析](Experimental_results/2026-10-30/live_frame_evidence_r01/analysis_r02/README.md)）。1,689フレームで、接触辺は左100%、右89%、下93%、上0%。cropは中央値55×97 pxで、輪郭は左端から右端・下端まで0 pxで接していた。保存PNG（frame635）では下端19 pxがすべて黄系Hue≈18・S≈81–83で、床のベージュが黄色範囲のS下限80をわずかに超えて赤コーンと連結していた。**支持点0はコーンに下端が無いためではなく、unionマスクが床と分離できていないため**であり、棄却自体は現行規則どおり。赤のみshadowは1,636/1,689点を持つが、7.2評価前なので制御支持点へ昇格しない。姿勢は引き続き`fewer_than_six_distinct_planes`で独立に不成立、距離は0/1,689。

次は、赤のみ候補を7.2の評価対象として保存データで検証するか、unionマスクの背景除去を設計するか、姿勢側を先に進めるかの判断。HSVしきい値を距離に近づけて調整すること、shadowをそのまま採用することはしない。新規16テスト、関連111件PASS、全866件では既知の`oit_interfaces` ImportErrorのみ。

**現時点でユーザーに直ちに再録画を依頼する必要はない。** 保存経路・設定・座標系・同一録画の対応を調べ、既存映像から得られない物理情報が残ったときだけ、その不足に限定して相談する。録画依頼を繰り返すことをユーザーは避けたいと希望している。

白線逸脱は後段。右境界は外周二重白線の内側という意図があるが、左境界の定義は未決定。実装前に相談する。今はコーンを優先し、勝手に白線や人検出へ主題を移さない。

## 8. 再開・確認用コマンド

### 8.1 解析PC: 現状と既存結果を見るだけ

```bash
cd /home/robo25/theta_ws/RICHO-theta
git status --short
git log -3 --oneline
sed -n '1,180p' Experimental_results/2026-11-09/wide_floor_geometry_r01/continuation_report.md
cat Experimental_results/2026-11-09/wide_floor_geometry_r01/same_frame_pose_r01/summary.json
```

成功済みの後半66テストなどは、同じ入力・コードなら再利用できる。資料を読むだけのために再実行しない。以降の8.2～8.4は過去処理の参考であり、11/9再開時にカメラを起動する指示ではない。

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
- 11/9の終了依頼は**引き継ぎ資料の更新と日報作成**。解析をここで止め、実機起動・追加解析・commit/pushを含めない。Git操作は別途明示依頼があるまで行わない。

### 次担当へそのまま渡せる再開依頼

> `AGENTS.md`と`HANDOFF.md`の第0章、11/9日報、`Experimental_results/2026-11-09/wide_floor_geometry_r01/continuation_report.md`を読んで、11/9の続きから再開してください。session `159c37ad534a4ac0b96ca69791713567`のL字床基準P0～P4・計10枚は撮影済みで、このPCのDownloadsにあります。全左右は前進方向を向いた車体基準、測った点はL字の曲がり角の外角です。P3=051180/051342は車体左20cm、P4=054907/055094は右20cmで、再質問・反転訂正しないでください。元画像・runtimeは未変更。外角候補の凸性と全24点順を監査し、P0と後半の背景に約2pxの変化を確認しました。同じ画像の固定4点で求めた未承認の光線x反転仮説では、中央1.4m→1.3936m、2m→1.9833mですが、鏡像と物理精度の確定ではなく、全解・全仮説を未採用のまま保持しています。最初は既に依頼した同じ撮影フォルダの`intake_summary.json`と`received_frames.csv`が届いているかを確認し、受信ソースhash・profile・session/frameを照合してください。まだ無ければこの2ファイルだけを依頼し、追加撮影や学校PC起動を先にしないでください。関連66テスト成功の記録は再利用可能です。未commitの解析・テスト・資料を消さず、Git操作・live反転追加・走行・ROS/FFBは別依頼として扱ってください。
