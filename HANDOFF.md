# コーン測距・FFB開発 引き継ぎ資料

最新作業枠: **ユーザー指定の2026-11-18扱い**。対象リポジトリ: `RICHO-theta`。OS/Git時刻と過去の実験日時は変更していない。

## 11/18最新：実回線・通常映像共存の採取手順を準備、323テスト成功

ユーザー「進めましょう」、非同期確認でmatsunuc/GPUPC両方使用可能との回答。[次の実行手順](Experimental_results/2026-11-18/network_coexistence_r01/README.md)、[計画](Experimental_results/2026-11-18/network_coexistence_r01/implementation_plan.md)。新collect.pyはstdlibのみ。最初は両PCでinspectを1回ずつ実行し、各output内submission.tar.xzを提出する。GPUPCは/home/hsr/yopi_ws/RICHO-theta、matsunucは普段src/start_theta_stream_rtc.shを実行するrepo直下。追加撮影/走行/画面録画/推論不要、映像の新規起動も不要。Git反映はユーザー側、こちらでpush/pullなし。

inspectはIPv4/interface/default route/iperf3 version/helpをローカル採取、明示peerがあればroute getのみ。既存launcherの固定IPを流用しない。MAC/SSID/環境変数/プロセス一覧/画像は採取せず、install/sudo/firewall/remote接続/listener/ping/能動負荷/PC時計同期なし。iperf3未導入やnetlink権限エラーを記録し、成功した回線測定へ偽装しない。解析PC smoke_r02ではnetlink permission deniedとiperf3未導入を正しく保存（GPUPCの結果ではない）。roleは操作者申告で機材認証ではない。smoke_r01は修正前でroleをgpuとしたため採用せず、原記録は残す。

optional observeは確定interfaceのmonotonic差分カウンタを1〜60秒、通常30秒受動採取する。全interface量であり映像専用bitrate/fps/空き容量/遅延とは呼ばない。既存output上書き拒否。次に両PCのIP/経路を照合し、有限UDP負荷を映像なし/ありで比較する予定。5→25→50Mbps各10秒・単一stream案であり、まだ能動実行コマンドは確定せず、実通信未実施。50Mbpsでは10Hz必要量80.98Mbpsを検証できず、5Hz40.49Mbpsにも映像/実overhead別。UDPをPNG/SCTP/DTLS実証へ読み替えない。

新15testと旧308を合わせ323成功/失敗skip0/15.68秒、正式network_coexistence_r01/verification_r01。旧codec/runtime/UI/操縦/画像/実験sourceのSHA不変を前段検証manifestから照合。PNG live採用・制御・FFB・ROSは未変更。最初の提出2archiveが届いたら、機体停止のまま実経路に限定した観測試験へ進む。

## 11/18前段：GPUPC PNG結果を受領、全40対不変・受信最大52.97ms、308テスト成功

ユーザー提出lossless_packet_gpu_20261118_r01.tar.xz、SHA95e6c09440360498319e75cb046a3e1e5cb094f76a213ad52116eda3ffdb67e1。[実測報告](Experimental_results/2026-11-18/lossless_packet_gpu_r01/submission_report_r01.md)、正式submission_audit_r01/submission_verification_r01。原archive/JSON5点をrecordings/2026-11-18/lossless_packet_gpu_intake_r01へ保持。開始時HEAD3b8d2d5/clean、前段はユーザーcommit済み。コード/manifest/config/profile/weights/4原PNG SHA一致、24warmup除外/80測定/40対、全pair/画像別/全体統計・false権限・局所時刻算術を再集計一致。

全80推論画素SHAが原画に一致、全40PNG packetのwire SHA/bytes/候補/復号を原画から再現、全80保存GPU bbox＋既存支持点/幾何も再現。candidateはloggerのsort_keysでkey順が変わるため元SenderFrameMotion生成順で復元し、wire差を人為的に作らない。新CUDA/YOLOなし、画像保存/加工なし。5186は元/PNG各10/10数値、支持点[232,409]・1.1892693049mで10対差0。他3画像は元/PNG各10/10 colour_contour_reaches_roi_edge保留。保留→数値/数値→保留/検出/理由/支持点/支持観測変更0。絶対真値誤差0・保留解除・実域精度保証ではない。

RTX4070/PyTorch2.7.1+cu118/OpenCV5.0.0/Ultralytics8.4.175実測。PNG側中央値/最大ms: encode30.90/40.06、送信初片前準備11.25/13.98、再構成検査11.59/13.55、decode検査copy24.85/25.47、CUDA6.54/7.47、支持点幾何1.68/4.22、初片→幾何完了49.09/52.97、encode開始→完了92.09/98.95。初片・全体とも100/200ms超過0。ただし無通信・同じGPUPC内の同期経路、実network/queue/IPC/表示/5・10Hz/運転映像共存なし。PyTorch peak allocated60,697,088/reserved98,566,144bytes元/PNG同一、GPU全体使用量/使用率ではない。

fragment込み中央値1,012,229bytes→5Hz40.49Mbps/10Hz80.98Mbps（実overhead/通常映像別）。仮想15/30/100Mbpsの理想直列化中央値539.86/269.93/80.98ms、初片後処理を加えた200ms内0/40・0/40・40/40。実回線実測ではない。GPUPC encodeをNUCの速度に転用せず、前段500ms初片前遅延の鮮度問題も解消したとしない。全source/物理/接地/制御/FFB/ROS false。

新audit_submission.py/check_submission.py、新11テストを追加、関連308成功/失敗skip0/15.60秒。テストfixture重複keyとhash試験の入力不正化を修正、実験採否/旧source/原画/過去結果不変。Git/ネット/日報/実機操作なし。同じGPU再比較・追加撮影・画面録画は不要。次は実回線容量/遅延・通常映像との共存を観測専用で確認する準備。PNG live採用やG923接続はまだ行わない。

## 11/18前段：GPUPCの保存4画像PNG/CUDA一括計測手順を準備、297テスト成功

ユーザー「では準備お願いします」。[実行手順](Experimental_results/2026-11-18/lossless_packet_gpu_r01/README.md)、新run.py/check.py/tests/test_lossless_packet_gpu.py。正式verification_r01/run_manifest.jsonでrunner/旧src/config/profile/weights SHAと4原画/ROIを固定。開始時HEAD894e7b4/clean、前段はユーザーcommit済み。旧runner/PNG codec/fragment/runtime/UI/操縦は不変。

GPUPCで新しい追加分をユーザー側Git経由で反映した後、run.py check --weights /home/hsr/Downloads/cone_distance_v03.pt → READY_NOT_MEASURED/CUDA tensor pass、次にrun。recordings/Experimental_resultsを有界探索し既知4原PNG SHA/native照合、5186だけROI200..280、他3枚270..350。入力/manifest/weights不一致や不足はCUDA/model前に停止。checkは実CUDA tensorまで・モデルなし・outputなし。CPU fallback/パッケージ変更なし。

runは既存モデル1個で元/PNG/PNG/元×5反復×4枚、24warmup除外・80測定40対。毎回実PNG→fragment→有界再構成→実復号/画素一致→既存CUDA/支持点幾何。encode/初片前検査/再構成/decode/copy/CUDA同期/支持点・幾何/実初片→完了を分離。原PNG不変・派生画像保存なし。受理初片200msは不変、復号まで遅ければ失敗、推論後200ms超は診断値に記録し適格false。原画fixture/no-odomで露光や実源鮮度の復元なし、FFB/制御/ROS false。

成功時のoutput=recordings/2026-11-18/lossless_packet_gpu_r01、提出1点=/home/hsr/Downloads/lossless_packet_gpu_20261118_r01.tar.xz。archiveはsummary/samples/pairs/per_image_summary/run_manifestのJSON5点のみ、画像・重み・設定は除外。失敗pack拒否・既存output/archive上書きなし。カメラ/映像送信受信/録画/走行/matsunuc不要。実GPU結果はまだ未取得。

解析PCでは実保存4原画と実PNG/既存幾何＋保存bboxの明示テストpredictorで80測定40対、固定入力の原判定維持を確認。新21含む297成功/失敗skip0/12.70秒。actual_CUDA_inference=falseを明示、synthetic結果と実GPU結果を混同しない。全旧src/元画像/過去manifest不変。Git/ネット/カメラ/GPU/実機操作なし。

次はユーザーがGPUPCで上記2コマンドを実行しarchive提出。返却後にPNG画素/コード/固定ROI/各pair/画像別集計と処理時間を監査し、仮想回線モデルのCPU仮定との差を評価。実回線容量/通常映像共存・元鮮度・接地・車体基準・FFBは別試験。GPUPCのencode時間をmatsunuc側の実測と呼ばない。PC時計同期必須へ戻さない。

## 11/18前段：PNG送信pending制限と11条件の連続負荷モデル、276テスト成功

ユーザー「進めてください」。[結果](Experimental_results/2026-11-18/lossless_sender_load_r01/README.md)、正式results_r01/verification_r01。新src/driver_lossless_frame_sender.pyはworker同期PNG検査、1 active + 1 latest pending、sender capture age200ms・channel buffer上限・source order/PTS/scope検査。新入力で進行を毎回中断せず、待機だけ最新へ置換。満杯時も期限破棄、invalid/閉鎖/時計逆行で旧値救済せず。送出済みbytesを取り消せないことを明記。旧VP8/runtime/UI/操縦・前段PNG codec/fragment/原画像はSHA不変、実通信へ未接続。

保存4原画のPNG payloadを循環し5/10Hz×15/30/100Mbpsを4秒入力、1ms仮想tick・buffer32KiB・capture/decode各active1+latest待機1。実scheduler/packet/fragment/復号で元画素一致、候補は合成capture/no-odom。CPUは前段解析PCの画像別中央値を使用（送信79.91〜88.22ms、受信65.56〜71.38ms）。毎回の新画像encode連続実測、GPUPC/送信側計測ではない。受取数は数値測距の件数ではない。

15/30Mbpsでは5Hz0/20、10Hz0/40。100Mbpsは20/20・40/40で受信初片→take最大153ms。100Mbps10Hzの0.6秒停止34/40復帰、127片ごと欠損21/40（19片欠損、部分受理なし）、受信CPU2.5倍0/40（待機16置換/24期限破棄）、送信CPU2倍0/40（capture待機15置換/25出力送信未完）。sender wire最大2,016,257bytes/2slot、decode wire2,049,144bytes/2slot、channel32768bytes以内。

重要：一方向全片500ms遅延でも40/40が受信初片期限内になり、simulation oracle capture→take最大744ms。通常100Mbpsでも最大244ms。両PCの各ローカル200msはend-to-end200msを意味しない。時計同期や元鮮度の認定ではなく、oracleはモデル内だけの診断。source_freshness/物理/接地/制御/FFB/ROS falseを維持し、live採用しない。

新20 sender＋8 model、旧221と旧VP8 flow27を含む276成功/失敗skip0/12.37秒。初回小単色PNGの圧力fixture前提ずれ1失敗は大きい合成PNGに修正しproduction条件不変。原画/前段結果不変、先行未commit成果保全。追加撮影/GPU/実機/ネット/Git操作なし。

次はGPUPC保存画像のPNG経路（encode/検査/fragment/復号/既存CUDA測距）の実測手順を準備し、解析PCモデル値と区別して取得する。その後に実帯域/遅延/運転映像共存の観測専用試験。初片前遅延を含む元鮮度は別検証、PC時計同期必須へ戻さない。現時点のユーザー撮影/走行/操作不要。

## 11/18前段：PNG専用atomic packet/有界fragmentをoffline実装、20/20一致・221テスト成功

ユーザー「進めてもらって問題ないです」を受け、[PNG packet結果](Experimental_results/2026-11-18/lossless_frame_packet_r01/README.md)を作成。正式results_r02/verification_r01。src/driver_lossless_frame_packet.pyとdriver_lossless_frame_fragments.py、新27テストを追加。旧VP8/flow/channel/runtime/UI/操縦/原画像はSHA不変、接続変更なし。PNG別magic/schema、既存checked_candidate共用。native RGB8 IHDR/IDAT/IENDだけ、CRC/deflate出力/PNG末尾/画素SHA/候補媒体PTS検査、payload2MiB/header8KiB/fragment16KiB/初片200msを維持。1packet有界再構成、欠損/重複/改変/入替/oldscope/sequence再生・新packet置換・時計逆行、復号前後/take期限・one-shot/旧値消去を確認。SHAは認証や撮影-運動の物理対応証明ではない。

元GPU4画像×5回20/20で画素/候補/元保存bboxの全支持点・幾何判定一致。新YOLOなし、数値1枚・保留3枚を保存しただけで絶対精度認定なし。候補はoffline合成fixture/no-odomで保存撮影の実運動を復元していない。関連221成功/失敗skip0/8.04秒。原本・過去結果不変、前段未commit成果保全。実機/ネット/GPU/G923/Git操作なし、全source/物理/接地/制御/FFB/ROS false。

解析PC CPU中央値fullpacket1,006,745.5bytes、59..63fragment（中央値62）、fragment込み1,012,201.5bytes。encode検査61.84ms、fragment生成/再構成検査43.18ms、decode検査copy45.54ms、初片からtake67.28/最大94.92ms。fragment段階は初片前の送信側検査も含み、初片後と単純加算しない。5/10Hz単純量40.49/80.98Mbps（SCTP/DTLS/IP/通常映像除外）。仮想15/30Mbpsは転送のみ0/20、100Mbpsは20/20、初片後CPUを保守加算しても100Mbps20/20。回線実測・連続pacing/queue・GPU/送信側期限ではない。results_r01は初片前送信検査まで加算した旧モデル19/20を保持、r02で計測区間を修正し期限は緩和せず。

次はofflineでPNG用の有界sender/backpressure/5・10Hz連続処理の有効率を評価する。旧VP8channelへPNGを偽装して流さない。実帯域とGPUPC/送信側負荷・通常映像共存の計測条件をその後整理。追加撮影・GPUPC操作は現時点不要。live未採用、take後推論/IPC/表示にも同じ初片deadlineを継承する必要がある。

## 11/18前段：可逆圧縮で4枚の元判定維持を確認、PNG試作候補。ただし帯域約10倍

ユーザー「すすめてください」。[比較と判断](Experimental_results/2026-11-18/frame_packet_preservation_r01/README.md)、正式results_r03。GPU実提出4原画像（5186＋28980/37696/44793）で現VP8/PNG既定/PNG level3/zlib level1を5反復、80試行。原PNG/code/元GPU推論画素・保存検出枠を照合し、圧縮復号はメモリ内のみ。新GPU/YOLOや画像保存なし。losslessが元GPU入力と全画素SHA一致した場合だけ元bboxを使用し、既存支持点・幾何を再計算。VP8はpacket側GPU bboxを使用しwire/画素も再現。HSV/ROI/元判定を緩めていない。

可逆3方式は各20/20全画素一致・最終判定維持、保留→数値0。VP8は画素0/20一致、最終判定5/20維持（37696の保留維持）、保留→数値10/20、5186は数値/支持点変化。最終判定は採否/reason/整数支持点/距離/モデル値。補助support_observation一致は別欄、数値末尾差のみ1e-10許容、画素は厳密SHA一致。元数値の絶対精度や接地正解を保証するものではない。

解析PC CPU中央値: VP8 fullpacket98,212bytes/encode34.23/decode15.94ms、PNG既定payload1,005,464bytes/37.79/20.11ms、PNG3=837,660bytes/111.61/21.99ms、zlib1=1,140,940bytes/63.33/15.20ms。時間範囲はVP8 packet検査込みvs候補payloadのみで同等ではなく、GPU/matsunucの速度としない。5Hz単純量VP8=3.93Mbps、PNG既定=40.22、PNG3=33.51、zlib1=45.64。PNG既定10Hz=80.44Mbps、現VP8比約10倍。仮想15/30/100Mbpsの理想直列化536/268/80msで、15/30Mbpsなら転送だけで200ms窓超過。回線実測でなく、実SCTP/DTLS/queue/運転映像共存の認定なし。

次の候補はPNG既定。ただし**まだlossless packet/runtimeは未実装・ライブ未採用**。次は独立offline packetでsource metadata/画素を束ね、サイズ/PNG寸法/破損/codec識別/旧scope/初片200ms/バックプレッシャーを評価する。既存VP8 channelへPNGを黙って流さず、上限や期限・5/10Hzを広げて通さない。現時点の追加撮影/GPU再試験/機体操作不要。

新11を含む関連194成功/失敗skip0/6.75秒、verification_r01。PNG IHDRとzlib出力量/EOF/余剰/未消費データ拒否、native/2MiB上限、wrong-pixelsへのbbox流用拒否、全80行集計、既存runtime SHA不変。results_r01/r02はfloat末尾のhash過小計数・補助観測と最終判定を混同した集計の履歴で、正式r03へ定義明示。過去結果を上書きせずruntime判定不変。先行未commit成果を保全。全source/物理/接地/制御/FFB/ROS false、Git操作/日報/実機起動なし。

## 11/18最新：3画像GPU結果で保留→数値が2枚、圧縮画素による境界判定変化を特定

[最新報告](Experimental_results/2026-11-18/frame_packet_saved_suite_r01/submission_report_r01.md)、submission_audit_r01。packet_recompression_multi_gpu_20261118_r01.tar.xz SHA3823324d6fc12b5855134f00c24621f9003f914a67130c61a5842f671e7a83d0、raw archive/JSON5点はrecordings/2026-11-18/packet_recompression_multi_gpu_intake_r01へ保持。GPU既存recordings/2026-11-13/guarded_motion_evidence_r02で原本が見つかりinputpack不使用。18warmup除外/60測定/30対、全summary/pair/画像別集計、旧runner/suite/src14/weights/config/profile/PNG SHA一致。全30packet wire/candidate/bytes/推論復号画素・元画素と全60支持観測/幾何を再現。新GPU推論・撮影なし。

元画像は3枚ともcolour_contour_reaches_roi_edgeで各10/10保留。packetで28980は10/10数値1.610814531m/支持点[306,384]、37696は10/10保留維持、44793は10/10数値0.983259329m/[305,419]。保留→数値20対、共通数値対0。距離差0/精度改善/真値と解釈しない。以前の5186の3cm差を今回全域の保証に拡大しない。

画像×元/packet bboxを入替える4通り事後診断で、変化2枚は元画像ならどちらのbboxでも保留、packet画像ならどちらでも数値。YOLO枠差より圧縮画素/固定HSV mask変化で説明される。元bbox固定の輪郭診断では28980の左端min x288→289で接触消失、44793のmax y421→419で下端接触消失。37696はmax y387で下端接触維持。元保留が過剰だったかpacket数値が不適切か物理根拠なしで断定せず、改善/安全認定しない。補完経路の追加採用でなく通常色輪郭で受理された。

packet receiver段階中央値/最大msは28980=15.364/16.414、37696=15.143/16.318、44793=15.435/15.770。全30中央値15.303/最大16.414ms、100/200ms超過0。PyTorch allocator peak allocated60,697,088/reserved98,566,144bytes双方同一。実通信/queue/IPC/表示/運転映像共存の時間でなく、処理が短いことと判定安定性は別。全source/物理/接地/FFB/ROS false。

次は**実通信採用を保留し、保存画像だけで輪郭判定/圧縮方式の安定性候補を評価する**。元数値維持・保留維持・新規数値を区別し、HSV/ROIを都合よく変更して今回だけ通さない。追加撮影/同じGPU再試験/環境再導入は不要。その判断後に通常映像と共存する既定off実通信試験へ進む。現在操縦・G923利用を指示しない。

新監査と新8テスト、checker/資料だけを変更、src/旧runner/suite/元画像/過去manifest不変。新8を含む関連183成功/失敗skip0/5.74秒、verification_r03（r02はfixture tuple/listの期待ずれ2失敗履歴、JSON往復fixtureへ修正しproduction条件不変）。開始時HEAD3257016/clean、前回分はユーザー側commit済み。今回Git操作/日報/実機起動なし。

## 11/18最新：追加の既存3画像をGPUで一括比較する手順を準備

ユーザー「どんどん進めたい」。[一括手順](Experimental_results/2026-11-18/frame_packet_saved_suite_r01/README.md)、新run_suite.pyは完了済み5186を繰返さず、前段でSHA確認済み11/13の28980/37696/44793だけを扱う。元画像をview_imageで確認し、保存bbox中心も検査、3枚ともROI270..350を明示固定。遠方の人/遮蔽2枚と近方1枚で、保留維持/変化も評価対象。1/1.5/2m実測対応と推測しない。GPUの新検出でROIを広げたり保存bboxで救済しない。

GPUPCのrecordings/Experimental_resultsから固定名を有界探索し既知SHAだけ使用、足りなければGPU/output作成前に停止。解析PCにbyte同一PNG3枚の入力packも準備済み：recordings/2026-11-18/packet_saved_suite_inputs_20261118_r01.tar.xz、2,563,792bytes、SHA86692750b6130c6a76b6a0a955cdf9e7646efbe4f7b6ec04c956e167d583b512。原本がGPUPCにない場合だけDownloadsへコピーし--input-archiveを指定。原画像Git追加なし、派生画像加工/保存なし、安全なallowlist読出し・一時コピーのみ。

旧run.py SHA00111723…を凍結再利用し、src/codec/YOLO/支持点/幾何/操縦不変。CUDA model1個で3枚、18warmup除外・60測定・30対を1起動で処理。全体summaryに加え画像別summaryとsuite_manifestを追加し、元結果/画像を含めず1archiveへ。途中失敗・集計不足はfailedにして圧縮せず、既存output/archive上書きなし。合成predictorによる実原画/VP8/幾何60測定30対とpack往復を検証、新10を含む関連175成功/失敗skip0/5.03秒、verification_r01。最初1件の空ログfixture期待ずれを修正しproduction条件は維持した。

次は今回の追加分をユーザー側GitでGPUPCへ反映し、READMEのrun_suite.py runを実行。output recordings/2026-11-18/packet_recompression_multi_gpu_r01、archive /home/hsr/Downloads/packet_recompression_multi_gpu_20261118_r01.tar.xz。追加撮影/走行/画面録画/映像送信/matsunuc不要。**実CUDAの3枚比較結果は未取得**。提出を解析後、通常映像との実通信共存へ進む。source/物理/接地/車体TF/FFB/ROSの未認定を保つ。Git操作・日報・実機起動なし、先行未commit成果を保全。

## 11/18最新：GPU再圧縮r02受領、双方10/10数値・差約3.0cm、採用時receiver段階最大17.271ms

[最新報告](Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/submission_report_r02.md)、正式gpu_r02_audit_r01。packet_recompression_gpu_20261118_r02.tar.xz SHA ec639c64f215514c315c02e601c40d5a89ab4154e38309f66fc69c5679d72b93、原archive/JSON3点はrecordings/2026-11-18/packet_recompression_gpu_r02_intake_r01へ保持。画像5186/weights/config/profile/runner/src14SHA一致、6warmup除外/ABBA5反復/20測定10対、全行/対/summary再集計一致。packet wire/candidate/bytes/推論画素と既存ROIでの全measurementも再現した。

今回はGPUPCでROI200..280を明示して実際に測定し、元/packetとも10/10数値。元1.1892693049m→packet1.1590857906m、差-0.0301835143m、支持点[232,409]→[232,411]で全対同一。variant内検出/距離は各1種類、採否/理由変更0。r01の事後診断に一致するが、今回は事後ROI変更で作った値ではない。1枚追加再圧縮の前後差であり絶対精度や全域3cm以内保証ではない。

CUDA同期predict中央値元6.693/packet6.704ms、支持点・幾何1.797/1.774ms、packet復号/検証/copy7.453ms。receiver段階合計中央値元8.513/packet15.980ms、最大8.898/17.271ms。100/200ms超過双方0。encode中央値18.947ms、encode+receiver中央値35.021/最大41.900ms。PyTorch allocator peak allocated60,697,088/reserved98,566,144bytes双方同一。候補なし早期returnではなく支持点・幾何まで通った予備負荷確認ができた。実network/queue/IPC/表示/運転映像共存、機体側encode、5/10Hz pacing、end-to-end期限は未測定。全物理/接地/元鮮度/制御/FFB/ROS flags false。

提出監査のr02対応は明示--protocolでroot/ROIを分離し旧r01条件維持。新2を含む関連165成功/失敗skip0/4.88秒、verification_r03。既存src/runner/画像/過去manifest不変、前回未commit成果保全。Git操作/日報/実機起動なし。

**同じ1枚のr03再実行は不要。** 次は距離・位置/保留状態の違う既存保存画像へ比較を広げる。既存4画像のGPUPC所在と対象ROIを先に確認し、暗黙の範囲拡大や都合のよい入力選択をしない。その後、既定off実通信経路で通常映像との共存負荷へ進む。追加撮影/走行やlive/FFB採用はまだ指示しない。以下r01/r02再試験の指示は履歴で、今回の結果を優先する。

## 11/18最新：GPU再圧縮r01受領、ROI案内ずれを特定。保存検出の事後差は約3.0cm

[提出解析](Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/submission_report_r01.md)。packet_recompression_gpu_20261118_r01.tar.xz SHA ba4fe5a6b64742a53be07f7b9283458ed377bee9200b4f1cfcfd9f15778257ec。原本とJSON3点をrecordings/2026-11-18/packet_recompression_gpu_intake_r02に保持。正式submission_audit_r02（r01は数値overflow拒否追加前）。GPUは実CUDA/codec完走、6warmup除外・20測定・10対、code/config/profile/weights/PNGと各pair/summary再集計一致。しかし元/packetとも全10件no_candidate、数値距離対0。raw検出はあるが中心x=239.340/239.306が案内したROI270..350の外だった。ユーザー撮影/操作不備ではなく、こちらの試験ROI指定が不適切だった。

実CUDA同期predict中央値元6.694ms/packet6.582ms、packet decode/validate/copy7.465ms、receiver段階中央値元6.749/packet14.059ms、packet最大17.554ms。encode中央値16.959ms、encode+receiver中央値31.047ms。PyTorch peak allocated60,697,088/reserved98,566,144bytes両方同一。候補なし早期returnで支持点/距離を処理していないため、採用時の負荷や実通信/5・10Hz期限を確認済みとしない。

保存された**実GPU bbox**と同一の推論画素を再現できたので、追加YOLO/撮影なしで事後距離を計算。全10packet wire SHA/candidate/bytes/decodedpixel一致、元画素も一致。明示posthoc ROI200..280で全10対同一、支持点[232,409]→[232,411]、元1.1892693049m→packet1.1590857906m、差-0.0301835143m（約-3.0cm）。提出measurementを改変した実測値ではなく事後幾何。絶対誤差、全域精度、補正ROIでのGPU全処理時間の結果ではない。物理/接地/元鮮度/制御/FFB/ROS false。

新audit_submission.pyと新8テスト、準備checkerの監査追加だけ。新8を含む関連163成功/失敗skip0/4.67秒、verification_r02。既存src/runner/画像/過去manifest不変。開始時HEAD22687a7/cleanで前回準備はユーザー側commit済み。Git操作/日報/実機起動なし。

次は**同じGPUPC反映済みrunner**で `--target-roi 200 0 280 720` を足し、output recordings/2026-11-18/packet_recompression_gpu_r02、archive /home/hsr/Downloads/packet_recompression_gpu_20261118_r02.tar.xzへ同画像試験。ROI補正後の支持点・距離まで実際に走った負荷を確認するためで、同条件の無意味な再実行ではない。新Git反映/追加撮影/走行/送受信/画面録画は不要。[r02手順](Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/README.md)。実通信採用/FFB接続にはまだ進めない。

## 11/18最新：GPUPCのCUDA復旧、保存画像packet再圧縮のGPU比較runnerを準備

ユーザー報告でGPUPC HEAD39e1e67（1118v2）、PyTorch2.7.1+cu118/PyAV16.1.0/OpenCV5.0.0、weights `/home/hsr/Downloads/cone_distance_v03.pt` と `recordings/2026-11-16/body_guard_live_r01/decoded_e52bb32f03d6488ebf37d769f46ec37a_f005186.png` の所在を確認。最初CUDA unknown errorで利用不能だったが、nvidia-smiはRTX4070/driver535.309.01を認識、CUDA_VISIBLE_DEVICES/NVIDIA_VISIBLE_DEVICES未設定、/dev/nvidia*も存在。GPUPC再起動後CUDA True/RTX4070 Laptop GPU/tensor計算1.0へ回復した。原因を特定したとせず、依存/driver再導入・module reset・時計設定変更なし。以上はユーザー端末報告で、こちらからGPUPCを操作していない。

[GPU比較手順](Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/README.md)、新run.pyは保存原本と現行packet VP8再圧縮後へ既存YoloConePredictor/observe_upper_completion/MotionRangeEngineを適用するCUDA専用offline試験。既知4PNGを名前/SHA/native寸法で照合、指定画像だけを使い、原本変更/派生画像再保存なし。最初は所在確認済みpin5186の1枚で6warmup＋20測定、ABBA5反復/10対。検出・支持点・採否・理由・距離差・原画像の反復変動、encode/decode/同期込みpredict/幾何時間・CPU時間・PyTorch allocator peakを保存。片方保留を誤差0と扱わない。GPU全体使用率/機体側encode負荷/5Hz・10Hz実pacing/通信期限は測定しない。

幾何は明示offline合成zero-age、packet identity/timeもreplay fixtureでodom未観測null。実測receiver段階時間と100/200ms超過を別集計し、遅い試行の幾何を黙って落とさない。元鮮度/物理/接地/制御/FFB/ROS全false、body-display guard/同接続pin-load/実network/走行は今回対象外。既に受信圧縮済み画像への追加圧縮で、camera原画からの直接packetと同一履歴ではない。1枚の完走を全域の絶対精度やlive採用としない。

新16を含む関連155成功/失敗skip0/4.29秒、verification_r01。実VP8＋実幾何＋合成predictor試験。保存実画像4枚のcodec往復/SHA/寸法/原本不変も別確認。前段runtime code SHA全不変。実CUDA YOLO/精度・負荷結果はまだ未取得。今回変更は実験専用runner/check/README/計画・テスト・この追記のみ、srcと過去manifest不変。日報/Git commit/push/pull・実機起動は行っていない。

次はユーザーがこの追加分をGitでGPUPCへ反映してREADMEのGPU用コマンドを実行。新規 `recordings/2026-11-18/packet_recompression_gpu_r01`、成功時のみ結果archive `/home/hsr/Downloads/packet_recompression_gpu_20261118_r01.tar.xz` を新規作成して提出。既存output/archiveを上書きせず、失敗ならERROR/summaryを確認してからr02で再試行。追加撮影/送受信/走行/画面録画/matsunuc操作は不要。下記「runtime接続直後」の未準備記述より本項を優先する。

## 11/18最新：既定offのpacket測距入力を実runtimeへ接続、397試験成功

ユーザー「進めてください」で[opt-in runtime接続](Experimental_results/2026-11-18/frame_packet_runtime_r01/README.md)を実装。新src/driver_frame_packet_runtime.pyはsenderの既存native reader共有＋追加の観測専用odom subscription＋全callback履歴、独立source/stream、5/10Hz、厳密HTTP offer/ackとapplied SDPのMID/cap一致、独立unordered/no-retry channel1本を束ねる。`--frame-motion-packets`既定off、motion-native必須。receiverは`--motion-input packet`を明示した場合だけ測距入力をpacketへ切替え、表示RTP/telemetry/controlは維持。通常は`rtp`のまま。片側だけ/不一致/再利用streamでは測距保留、RTPへfallbackしない。

PacketMotionBridgeが従来GPU process/pipe1本を再利用し、元stream/capture sequenceをNativeFrameへ保持。inflight1組のcandidate/SHAだけを同identityで返った結果へ結合しmotion_bridge_events.jsonlへ保存。child rawログはpacket入力marker、summaryはmode/200ms/code SHA。受信初片からの200msをdecode/pipe/inference前後/受理/表示まで延長せず適用。sender側read-return200msとは別窓でありnetwork/元鮮度を認定しない。panelに独立packetと表示RTPが同一frame未認定である旨を追記。全物理/接地/元鮮度/FFB/ROS権限false。

正式results_r02で新22を含む関連**397成功、0失敗/skip、12.52秒**。実codec＋actual receiver offer handler＋実local pipe＋既存MotionRangeEngine（predictor/支持点/画像/odomは合成）、元723番とv=-.2/ω=+.1のcandidateが一致し期限内受理true。代表結合JSONとraw認識JSONを保存。実network/camera/ROS/CUDA/G923は未起動、距離1.23599mは合成値で実測精度ではない。旧peer遅延disconnect/旧inflightが新scopeへ混ざらない、重複channel/ack/型偽装で測距だけ無効、CLIで余分なmodel/pipeを作らない等を確認。

今回既存5source（webrtc_stream、receive_ui、driver_motion_camera、bridge、process）へ意図したopt-in差分あり。過去の「runtime byte不変」は前段履歴で今回へ流用しない。before/afterは新監査へ保存し過去SHA不変。操縦関数/TelemetryNode/keyboard/legacy cameraの固定AST一致。旧12componentのbridge/process2は意図した変更、幾何/支持点/body guard/IPCなど10はSHA一致。前段packet/fragment/worker、odom/clock/telemetry/FFBは未変更。初期fixtureのbase_linkをbase_footprintへ直し、async executor終了待ちを自試験中断後に有限done pollへ変更。production gate/FFB停止要件を緩めず全再実行。results_r01はCLI試験追加前の396成功履歴。

sender終了は既存worker doneの有限poll（新executorなし）、receiver finite join、GPU childは従来grace/forceを再利用。停止未完了を成功と偽らない。Git操作/日報/実機操作なし、先行未commit成果を保全。次はGPUPC環境で保存native画像をpacket再圧縮→YOLO/色支持点/測距へ通し、採否/数値/負荷を比較してから双方の実通信手順を提示。追加撮影/走行はまだ不要。PC別手順や実保存先を決める前にlive起動しない。車体TF/車幅/点の意味とrisk-gradient/FFBは別gate、PC間時計対応必須へ戻さない。

## 11/18最新：保存画像の実encode併走負荷を測定、追加30Hzを見送り

ユーザー「進めましょう」により[保存画像load比較](Experimental_results/2026-11-18/frame_packet_load_r01/README.md)を実施。解析PC8 logical CPU、aiortc1.14/PyAV16.1、native BGR1280×720/30Hzの持続Vp8Encoder（比較用target1.5Mbps固定）と、前段実FramePacketChannelSenderの独立keyframe encodeを併走。fake sink即時drain、実peer/socket/ROS/camera/G923/受信decode/YOLO/操縦負荷なし。既存runtime/private RTP等は未変更。

11/16 pin5186＋11/13同sessionの保存evidence28980/37696/44793の4原本を既存監査SHAへ照合。file/画素不変、画像加工/再保存なし。static_repeat1枚反復とdiscontinuous_cycle4枚切替（実連続走行ではない）、追加0/5/10/30Hz、warmup0.5秒＋測定3秒、逆順を含む2反復の16試行。replay admission時刻/odom/seqは合成で実画像の観測ではない。source/物理/FFB/ROS flags false。

正式results_r01のencode1,977行・offer/send1,010行とprogressを保存、analysis_r02で完了間隔も含め全再集計整合。static: video178/180/179/180、packet5Hz30/30、10Hz59/60、30Hz83/180。切替: video全180、packet30/30・60/60・64/180。5Hz合計60/60、10Hz119/120、30Hz147/360。10Hz生成packet7.892〜8.162Mbps、30Hz23.694〜24.487Mbps（ネットワーク測定でなく、送れないencodeも含む）。CPUcore相当static0/5/10/30Hz=.735/1.002/1.318/1.849、切替=.965/1.234/1.557/2.130。

30Hzの損失は通信でなく現在のlatest-only完了公開policy。成功分P95が短くても遅い仕事を落とした選別バイアスで改善とはしない。10Hz破棄1件はstatic反復1 seq28、encode102.877ms中にseq31がoffer。期限/buffer待ちではない。videoのbaseline置換2件もあり追加encodeだけに全欠落原因を帰さない。完成間隔最大static5/10/30Hz228.90/186.11/566.03ms、切替217.12/125.12/297.57ms。5Hzの名目200msもありFFB期限達成とはしない。

新12含む関連270成功/0失敗/skip0、4.38秒、verification_r01。前段src/channel/既存8runtimeと保存codec/source SHA不変。先行の実験assert（streaming PTS1tick丸め）とcv2 distribution metadata採取エラーは実験器だけ修正し全16試行を再実行、sourcepacketの厳密gateは緩めていない。analysis_r01は完了間隔追加前の履歴。今回日報/commit/push/pullなし、前段未commitを保全して今回もローカルのみ。

判断: 現方式の追加30Hzを実接続候補から外し、次の比較を10Hz上限候補/5Hz低負荷比較へ絞る（ライブdefault/FFB rate承認ではない）。次はsender capture/odom履歴・接続scope・receiver認識入力へ既定offのopt-in接続を設計し、入口が準備できてからmatunuc/GPUPC実負荷確認手順を提示。現在の追加撮影/走行/GPUPC操作不要。車体TF/車幅/点と元鮮度/FFBは別gate、PC間時計同期必須へ戻さない。

## 11/18最新：独立channelのworker・上限・終了をfake接続で検証

ユーザー「まだ進めてください」により、[独立packet channel接続部](Experimental_results/2026-11-18/frame_packet_channel_r01/README.md)を実装。開始時worktree clean、HEADはユーザー側commit **33feb17（1118v1）**で、以下の以前の日報/packet/flowの未commit記述は当時の履歴。今回はcommit/push/pullや日報作成なし。

新src/driver_frame_packet_channel.pyは明示remote SDP MID/local能力から保守的にmessage上限を算出（省略64KiB、0は無制限でもapp16KiB上限）。独立unordered/maxRetransmits0の明示channel objectを要求し、producer外コピー/検査→専用encode worker→owner pump/send、受信callback非待機有界inbox→専用再構成/decode worker→一回消費を実装。既存flowはworker準備済みplanの内部入口だけ追加し、従来wire検査を維持。callbackでcodec/SHA/JSON/画像copy/disk IOなし。

overflow/lock競合/codec異常はinstance退役、send例外/閉鎖は当該独立channelだけclose。queue待ちとdecodeを初片期限へ含め、処理時刻とarrival時刻を交互にassemblerへ入れない。closeは有限joinで、hung codecは停止未完了falseとし、daemonの遅延結果を公開せず終了後解放。強制停止/sandboxやハード実時間保証ではない。

正式results_r01で**新34を含む258成功/0失敗/skip0、4.26秒**。実thread/VP8 codec＋fake channel、clock10.05秒系→700,000秒系で候補/符号/保留維持、owner/最新待機/入力copy、上限/不正SDP、実public aiortc capability、失敗/詰まり/期限/finite close/再接続等を確認。実peer/socket/ROS/カメラ/G923起動なし、既存8 runtime sourceと距離/表示12 source、11/17 packet/source保存SHA不変。新flow SHAは新監査へ保存し過去結果を書き換えない。今回は合成画像/運動のみ、カメラ画像加工なし、全鮮度/物理/FFB/ROS認定false。

これは実offer/answerやruntime入口の接続完了ではない。明示MID/channel/sender/streamと同じfragment上限を両端へ束ねる入口はまだなく、labelは一意性/認証ではない。bufferedAmountは他traffic/SCTP全体の遅延保証でもない。

次は既存video encodeと追加packet encodeを保存画像で併走してCPU/処理時間/生成bytes/置換を計測し、rate/方式を選ぶ。その後にcapture/odom履歴・接続scope・GPU認識入力へのopt-in接続。実負荷前に共存可能と断定しない。現時点のGPUPC反映/追加撮影/走行/時計設定/G923試験不要。車体TF/車幅/障害物点とrisk-gradient/抵抗FFBは別gate。今回追加分のみローカル未commit/未push。

## 11/18扱い最新：11/17日報作成後、有界fragment/再構成/最新待機を実装

ユーザー「11/17終了・日報、Gitは自分でpush、その後11/18扱いで進める」を依頼。先にDaily_reports/2026-11-17_daily_report.mdと索引・代表図2点（codecサイズ/時間、CSV/script/SHA付き）を作成・リンク/SHA確認。197成功等は同一コードの既存成功結果を再利用。当日扱いの実験UTCが11/16だったことを明記して改変せず、11/18分を日報へ混ぜない。こちらでは今回commit/push/pullを一切していない。開始/現HEADはc05ff48。

その後[11/18有界flow](Experimental_results/2026-11-18/frame_packet_flow_r01/README.md)へ進行。新src/driver_frame_packet_flow.pyはheader88bytes/明示1,024〜16,384bytes上限のfragmentとworker用再構成、sender進行中1＋最新待機1を実装。最初の片からの期限を完成/重複で延長せず、旧seq・scope混入・conflict・破損を拒否、completedは一度だけ渡す。新組で旧途中/未消費complete失効。最新入力で進行中を毎回中断せず待機のみ置換し、source capture age/指定buffer上限でhand-off制御。実send成功ではなく、投入済transport bytesの取消もできない。単一worker owner契約でthread-safeではない。

新27を含む関連224試験成功（3.93秒）、正式results_r01。実VP8packetの逆順分割/再構成/decodeも確認。元11/16 pin画像は不変、運動は合成。20Hz20組の論理queueで32Mbps20完成、8Mbps11完成/9待機置換、1Mbps0完成/14置換/6期限切れ、32Mbps1片欠落で19完成（frame5採用なし）。上限message16,384/logicalqueue32,768/実保持sender203,898・receiver101,969bytes、close後0。これは実通信/CPUを測った性能ではなく、他traffic/codec時間/SCTP内部queueや再送を含まない。全鮮度/物理/FFB/ROS認定false。

次はmax-message-size交渉・callback外worker所有権・実send失敗/終了をfake peerで接続検証し、その後実負荷を確認してライブ採否を決める。既存RTC/ROS/操縦/capture/距離/FFBへ今回接続なし、前日のpacket/source実装と旧距離/表示12SHA不変。現在の追加撮影/走行/GPU反映/時計設定/G923試験不要。新日報と11/17・11/18成果はローカル未commit/未pushのままユーザーに委ねる。

## 11/17扱い最新：11/16日報push完了後、画像・運動一体packetをローカル試作

ユーザー「作業を終え日報/push、その後11/17扱いで進行」を依頼。11/16日報・代表資料3点・clock実記録監査・sender-frame部品・目標/方針変更をcommit c05ff4881c6c1ca3a128bdb7a673e1c444c62d2e、origin/mainへpush成功。push直後HEAD=origin/main、worktreecleanを確認。日報Daily_reports/2026-11-16_daily_report.md、索引更新。pin5186画像は元PNGとSHA同一、3地点差とclockbracket統計図はCSV/manifest付き。raw/重み/外部FFBrepoはpush対象外。

その完了後、[11/17一体packet試作](Experimental_results/2026-11-17/frame_motion_packet_r01/README.md)へ着手。新src/driver_frame_packet.pyは画像VP8 keyframeと元candidateを一つの長さ/全体SHA付きpacketに束ねる。厳密JSON/元候補再検査、native寸法/可視keyframe、別sender/stream/重複/逆順/途中破損/入替え拒否、失敗時旧pairクリア、受信内ageのみを実装。時計同期/換算/RTP先頭PTS推測なし。SHAは認証ではなく、callerが元から誤った画像/metadataを束ねた場合の保証でもない。

新23を含む関連197試験成功（3.39秒）、正式results_r01。初回1失敗はimmutableなPyAV C拡張属性へmockするtestの誤りで、module属性mockへ修正しproduction gateを弱めず再実行成功。元保存pin1枚＋合成運動fixture（実画像の実odomでない）を5回処理し、packet中央値101,927bytes/encode26.415ms/decodecopy14.535ms。PNG比較1,021,907bytes/encode37.323ms。30fps単純量24.46/245.26Mbpsは実通信性能ではない。元画像file/画素不変、圧縮/復号画像再保存なし。

これは既存RTP受信画像へmetadataを貼る方式でなく、新しい認識入力packet候補のoffline試作。ライブ採用未決定、RTC/ROS/実機/FFB未接続、全認定flag false。前日のsender-frame部品とsender/receiver/capture/odom/FFB source不変、旧距離/表示12SHA一致。今回11/17分は未commit/未push（11/16pushとは分離）。

次は有界の分割/再構成、欠落/期限/再接続/バックプレッシャー時の最新優先破棄と、追加encode/帯域が既存操縦映像へ与える負荷をローカル検証。約100KBpacketをそのまま単一DataChannelで送れると仮定しない。圧縮/復号をRTC callbackへ置かず、実取得点とGPU入力接続は方式決定後。PC間時計対応へ戻さない。現時点のGPU反映/撮影/走行/再記録不要、車体TF/車幅/点の意味は別の未確定事項。

## 11/16最新：PC間時計対応の必須化を撤回、送信元フレーム・運動対応部品を実装

ユーザーが以前の時計問題を指摘。9/17の約51〜58ms差によるFFB拒否と、9/24のchallenge方式PC間/G923成功を確認し、PC間時計同期/換算を必須に戻さない方針へ変更した。下記の過去「次はPC間時計対応」は当時の予定で、現在は中止。保存済み時計観測は診断資料として保持し、原本やfalseflagを書き換えない。challengeは指令期限用で、元画像/odom鮮度を自動認定しない。

[部品・試験・次の境界](Experimental_results/2026-11-16/sender_frame_motion_r01/README.md)。新src/driver_frame_motion.pyのSenderFrameMotionは既存の厳密odom snapshotの有界履歴から、同sender monotonicの画像read-return以前の最新観測callbackだけを候補とする。過去callbackの無効/反復/逆転/期限/frame不一致を飛び越えて旧値で救済せず、欠落/drop/競合で履歴失効、異sender/時計逆行/不正identityはinstance退役。0実測・符号・元整数stamp・元snapshot時刻を保存。capacity/時間制限は明示呼出し値、試験4件/100ms/200msを実機基準へ採用しない。全認定/control/FFB/ROSflag false、receiver_media_pts null。露光/元計測時刻への同期や実年齢証明ではない。

新30を含む関連174試験成功、正式results_r01。実aiortc1.14.0 TimestampMapperで先頭欠落後PTS0が別captureへ移ることとwrapを確認、実VP8でframe.opaqueの任意identityが消えることも確認。元測距/表示12ソースSHA一致。既存のsender/receiver/capture/odom/relay/publisherは一切変更せず、新部品はruntime未接続。PC間時計対応のコード/新交換は作っていない。

次はsource bundleと受信実画像の厳密な識別・配送方式を、欠落/再接続込みでローカル検証して決める。送受信連番、到着順、先頭PTS0、近いreceive時刻だけで結合しない。旧clock-binding必須offline joinerの条件を緩めて流用しない。現時点のGPU反映/追加撮影/同じ停止記録/走行は不要。新部品の呼出し点と実画像照合は未実装で、走行測距/G923接続完了と報告しない。日報・commit・push・実機起動は未実施。

## 11/16最新：sender ROS時計bracketの実記録確認完了、次はPC間時計対応

[正式監査](Experimental_results/2026-11-16/sender_ros_clock_live_audit_r01/README.md)。received_sender_clock_20261116_r01.tar.xz（SHA07cdbd52ca87b33a33f5eabba9bf09d21a59c9da57b6caa8a5d4e0b2ac89488e）の通常3原本完備。peer_begin1＋v3telemetry1177＝1178events、50.329734秒/23.3659Hz。receiver4コードSHA現版一致。queued=written1178、2,895,788bytes、queue/lock/drop/受理後破棄0、sequence1〜1178連続、closed/errornull/donetrue。offered1180/rejected2の末尾理由は未記録で断定しない。

全1177clockはsampled、ROS_TIME/use_sim_timefalse/activefalse、同sender13c3ef90fd6a41e7a283b7195abd6604のodomとID/時計ID一致、同messageのodom snapshot→clock read順序整合。clocksequence1〜1177、generation全1、first1/advanced1176、逆行/設定変化/読出し異常なし。odom全受信/元stamp進行、v/ω全0、twistbase_footprint/poseodom。clock読出し幅P95/最大.165567/.287649ms、受信間隔最大58.617648ms、受信→writer最大4.081418ms（disk完了/通信遅延ではない）。一定offset仮定の区間交差は幅46,064nsで非空だが真clock精度やdrift/header時計認定でなくbinding生成なし。

この新項目の実ROS→JSON→受信→保存確認は完了。次は両PC時計の対応区間を採る実装。今回PC間4timestampを新実装したわけではなく、片道ログからoffsetを作らない。同じ停止記録の再提出/走行/撮影は不要、ユーザーの追加操作は次の実装後に提示。同時刻距離結合/現取付車体TF/車幅/点の意味/FFBは未認定のまま。

formalresults_r02、rawsender_ros_clock_live_intake_r02、r01は因果検査追加前の同提出成功履歴。新監査10を含む関連84テスト成功。runtime変更なし、252成功は再利用。開始時worktreecleanで前回分は既にユーザー側commit済み。こちらから実機起動・Git外部操作・日報作成はしていない。

## 11/16最新：sender ROS時計のmonotonic bracketを実装、両PC未反映

[実装/検証/反映後手順](Experimental_results/2026-11-16/sender_ros_clock_bracket_r01/README.md)。ユーザー「すすめてください」で、driver元stamp起源の貼付確認後の第一段階を実装。新src/driver_sender_clock_observation.py（ROS依存なし）、TelemetryNodeのoptional getter/辞書key1、receiver記録v3のみ。node ROS nowをinteger monotonic_nsの前後で挟み、clock type/use_sim_time/ROSactive・試行sequence・generation・ROS前進/反復/逆行/0・設定変化・読出し幅/差区間を記録。元odom metadataと同sender ID、元stampとは別で、header時計/センサ取得時刻の一致を認定しない。

読出し異常/競合/monotonic異常は新clock値を全nullとし旧区間を再利用しない。ROS逆行/設定変化等はgenerationを分けるが、前進jump全件や途中の設定変化を完全検知するわけではない。最悪読出し時間・実通信負荷・drift上限未認定。PC間4timestamp交換はまだ追加していない。

新clock keyありはv3 envelope、旧senderはv1/v2維持。厳密schema・整数ns・方程式・flags検査、未知/不正/odom sender ID不一致はclock null＋理由。既存有界queueを使いcallback disk IOなし。metadataにreceiver4コードSHA。source_clock_id/measurement_valid等はnull、全FFB/clock/header/freshness認定false。旧offline adapter/監査はv3未対応なので自動投入しない。既存原本/過去SHAは書換えない。

実sender getter→JSON→実receiver callback→保存をfake ROS/peerで17/17、v3 15＋v2 1＋v1 1、開始終了込み19events/drop/reject0。新20を含む関連252テスト成功、元距離/表示12ソースbyte不変。TelemetryNode固定ASTは正確なmetadata9追加（旧odom5＋clock4）だけを除き旧baseline一致、操縦/camera/spin/keyboard/ROS/control hash維持。構文確認3ファイル成功。formalresults_r01、rawsender_ros_clock_bracket_synthetic_r01。

未commit/push・実ROS未確認。次は今回分をmatsunucとGPUPC双方へ反映後、GPUPC新保存先received_sender_clock_r01で通常送受信の短時間停止記録（新項目初回確認）。receiverを先に起動→通常sender再接続、コーン/走行/画面録画不要、受信正常終了とsummary確認後received_sender_clock_20261116_r01.tar.xz提出。反映前に旧patch再適用や新記録だけ始めない。runtime起動・実機操作・外部Git操作・時計設定変更は今回未実施、日報/push未依頼。

## 11/16最新：Kobuki stamp生成経路を貼付grepから確認。上部再送不要

[元stampの根拠](Experimental_results/2026-11-16/spacetime_evidence_r01/kobuki_stamp_source_evidence.json)。ユーザーは端末上部が切れた295行のテキストを提出したが、kobuki_ros.cpp593でnodeget_clocknow→Odometry::update引数、odometry.cpp87でrclcppTime now受取→104でodom_quat_time_=now→138でheader.stamp代入→kobuki_ros.cpp598でpublish、が全て含まれていた。元テキストはrecordings/2026-11-16/kobuki_stamp_source_intake_r01/terminal_excerpt.txt、SHA201fcc9ba30c9aa9f597fc78e5e9638491148ad0def15833c6518f179242ab8b。再表示・再提出は不要。

貼付ソースのstampはdriver更新時のROSノード時計で、firmwareのセンサ取得時刻そのものではない。use_sim_time双方falseと併せて起源は狭まったが、全文SHA/現在binary一致/時刻補正・TimeSourceは未確認、時計同期/センサ取得/露光同期を認定しない。過去r03のnullclockやfalseflagを上書きしない。次はROS nowをsender monotonicで挟む観測とsender/receiver時計対応区間保存の実装段階。まだruntimeへ新実装していない。ユーザーの現時点の追加操作不要。本文・JSON保存のみでruntime/時計設定/driver/操縦/ROS/FFB変更なし、83テスト成功は再利用、日報/push未依頼。

## 11/16最新：ROS時計設定のユーザー出力を確認。次は既知Kobukiソースのstamp生成行

[設定結果と読み取りコマンド](Experimental_results/2026-11-16/spacetime_evidence_r01/README.md)。ユーザー貼付でmatsunucのkobuki/送信ノードuse_sim_time双方false、/clock Unknown topic。user_report JSONに由来を明示し保存。設定を変える必要はない。r03期間全体の設定/元stamp生成元/PC間同期の証明にはしない。

8/18既存ODOM診断メモを調べ、当時のdriver実体は/home/matunuc/kobuki_ws/install/kobuki_node/lib/kobuki_node/kobuki_ros_node、ソースはkobuki_ws/src/turtlebot2_ros2/kobuki_ros/kobuki_node/srcと判明。過去のwheelbase/use_imu_heading修正と停止/前進/左右旋回のodom検証は再利用し、今回の停止0を理由に実機走行試験をやり直させない。ただし元stamp生成行/現在binary一致は未記録。次は既知kobuki_ros.cpp/odometry.cppのheader.stamp/now/clock/odom更新publish周辺をrgで読み取る。上流別版/Gazebo/ROS1実装を実機証拠と混同しない。外部検索は当該根拠を与えなかったため採用なし。runtime/時計設定/ROS/操縦変更なし、新テスト不要、83テスト成功はコード不変で再利用。日報・push未依頼。

## 11/16最新：時計と現取付座標の接続根拠を整理。次はROS時計設定の読み取り

[正式監査・方式比較・次の3コマンド](Experimental_results/2026-11-16/spacetime_evidence_r01/README.md)。ユーザー「すすめてください」でr03全2045観測の経過差を集計。元stamp/ sender callback/snapshot/receiver経過は87.164885501/87.164924483/87.158089766/87.160979457秒。元stamp−callbackの相対経過差−15.394〜.403ms、receiver−snapshot経過差−.271〜62.251ms。時計誤差/通信遅延上限ではない。一定相対歩度でもoffset593.462465584秒なら条件付きd0〜62.522ms、offsetを.1秒小さくしてもd100〜162.522msで同じ片道ログを説明できるため、真offset/上限は決めない。

4timestamp区間をoffline合成検証、非対称経路で中点を真値へ固定しない。実交換・clock bindingなし。将来は元ROS時計/有効性の確認→ROS nowのmonotonic bracket→sender/receiver交換または外部根拠＋誤差/ドリフト/適用区間→同sessionの距離運動結合が必要。ROS2公式Clock and Time/REP103/RFC5905を参照。OS同期設定・control channelを変更しない。

既存光学ベクトル原本SHAと19,297条件付き/31,905保留を再利用、車体XY新規0。10/19診断TFはmeasured/base false、10/21紙fitは独立物理変換false、11/9同frame診断はhandedness保留/selectednullで現取付TFへ自動採用しない。R(q-hu)+tと直下点t-hRuの原点差を合成検証、反射/非剛体/床向き不一致を拒否。合成yaw転記ミスは初回auditで拒否し正式結果保存前に修正・全再実行。新10含む関連83テスト成功。

次はmatsunucで通常kobuki/映像送信中に `ros2 param get /kobuki use_sim_time`、`ros2 param get /theta_driver_telemetry_node use_sim_time`、`ros2 topic info /clock` の出力を得る。時計設定変更・走行・新撮影・同じ停止記録再提出は不要。base_footprintに対する現光学原点の前後左右/高さ/向きと測量根拠・session、車幅/点の意味も未確定。左右言葉の定義は前進方向基準で確認済みなので再質問しない。runtime/ROS/FFB変更・起動なし、日報/commit/push未依頼。

## 11/16最新：r03受信事実のoffline運動形式への受け渡しを実装・検証

ユーザー「作業が止まってしまっているので再開してください」で、r03受信監査後の保存形式受け渡しまで進行。[結果と境界](Experimental_results/2026-11-16/received_motion_handoff_r01/README.md)。新adapter/checkは実験directoryだけに配置。r03原本3SHAを正式受信監査へ照合し2,045telemetryを既存offline_measured_motion_record_v1へ変換、MotionLog/read_motion_records往復全一致。元整数ns stamp/base_footprint/v・ω0/sequence/session/受信時計/時刻を保持。構造validをmeasurement_validへ昇格せずnull、source_clock_idもnull。元観測/age/pose frame/複数保留理由/元行SHAをwrapperへ保存。旧UIの初期0は測定値へ補完しない。

実r03全2,045件に測定有効性未認定/元時計不明/時計対応なしの3理由（同一行の重複診断）。以前の距離51,202件は別sessione52bb32f、r03は4852ed17なので結合試行0/実ペア0。合成では未認定の新入力で旧join候補が失効し距離だけ維持することを確認。新adapter10を含む関連145テスト成功（過去suiteと重複）。formalresults_r01、rawrecordings/2026-11-16/received_motion_handoff_r01。runtime/ROS/FFB/測距変更・実機起動なし。

次は元ROS時計とsender/receiver時計の対応根拠・誤差・運動有効性、現取付車体↔光学変換の整理。実機で同時計・同sessionの結合を確認する必要が生じた段階で手順提示。疎通用の同じ停止記録/走行/撮影をすぐ繰り返させない。新adapterは実行UIへ未接続、FFB/物理/時計認定false。日報・commit/push未依頼。

## 11/16最新：r03でodom受信・元stamp進行・保存を確認。疎通段階は完了

[正式結果と次の段階](Experimental_results/2026-11-16/odometry_metadata_received_audit_r01/README.md)。received_telemetry_odom_20261116_r03.tar.xz、SHA50619c1e1fb3b241ae7fe2d25c18746f0ebb17d5fd268703de0d5ab5ed55d5d2、通常3原本完備。peer_begin1＋telemetry2045＝2046events、87.160979秒/23.4509Hz、3,163,824bytes。offered=queued=written2046、queue/lock/drop/reject/破棄0、sequence1〜2046連続、正常closed/errornull/donetrue。

全2045でcallback_received=true/構造validtrue/statusadvanced。保存観測間2044区間すべて元stampとcallback sequenceが進行、callback sequence8→4385、元stamp1794822450209981778→1794822537374867279、twist base_footprint/pose odom、受信したv/ω全0。初期0ではなく受信メッセージの0として区別できた。sender callback ageP95/最大18.225/25.648msは元計測の輸送遅延ではない。受信間隔最大104.180ms、FFB100ms達成とはしない。receiver3コードSHA一致、sender全sourceSHA未提供。単一session4852ed17f96f41cfbd13aa38d0ba6592/sender486c49b1306c4367a76ff576283882ef。

r02未受信からの解消原因は未特定（間のCLIはユーザー貼付でkobuki配信/CLI受信あり）。同じ疎通確認の再撮影/走行/再記録は不要。次は新metadata→offline運動形式への受け渡しと時計対応不明時の保留の検証。今回telemetryだけで距離ログなし、以前の距離とは別session/時計なので結合しない。時計対応/車体変換/実運動精度/距離との対応/FFBは未認定のまま。

正式results_r01、rawodometry_metadata_received_intake_r01。offline監査にprefix引数と観測間進行/age集計を追加、監査新3を含む関連63テスト成功。runtime/ROS/FFB/測距変更なし、実機起動なし、日報・commit/push未依頼。

## 11/16最新：r02実記録は成功。送信側odom未受信が判明、次はROS読み取り診断

[全件監査と次の3コマンド](Experimental_results/2026-11-16/odometry_metadata_live_audit_r01/README.md)。received_telemetry_odom_20261116_r02.tar.xzの3原本完備、SHA4ff43fd8b39d1859efb793935dd682ea10aee0b5871681fe55ac2492c91bc0fd。peer_begin1＋telemetry3222＝3223events、137.235720秒/23.4706Hz、4,676,786bytes。queued=written3223、queue/lock/drop/受理後破棄0、sequence1〜3223連続、closed/errornull/done/shutdowntrue。offered3225/rejected2の末尾理由は不明。受信間隔最大300.761ms、記録投入最大.2665msはFFB性能認定でない。

全3222telemetryに厳密v2観測が保存され、全件callback_received=false/sequence0/statusnot_received、元stamp/frame/入れ子v・ωnull、observer drops0。従来UIの全0は未受信初期値で実測停止ではない。receiver3コードSHA一致、sender新metadata伝達は確認できたがsender全sourceSHAは未提供。単一session080bcb3591ae4c498cea187ad48b857a、sendercef46aab5c824dc8adfe6765743eec13。次は通常映像送信中にmatsunucの同じROS環境でnode list、node info /theta_driver_telemetry_node、topic list -tの出力を得る。topic/配信元/ROS環境/QoS/spinのどれが原因かは未確定。追加走行/撮影/再記録/driver起動をまだ要求しない。

正式results_r03、rawodometry_metadata_live_intake_r03（r02も同じ提出物で保存）。新offline監査9を含む関連60テスト成功。共通envelopeはコピー上だけv1へ投影して既存厳密監査器を再利用、原本/原summaryは維持。runtime・ROS・FFB変更/起動なし、日報・commit/push未依頼。

## 11/16最新：元odometry実提出は空ログ。まずGPUPC元フォルダを確認

[提出確認と次のコマンド](Experimental_results/2026-11-16/odometry_metadata_live_audit_r01/README.md)。received_telemetry_odom_20261116_r01.tar.xz（788bytes、SHA d62a08d9afe84b9659890ba29c18198105dd8188e5bdde7cdc2813c8ef8c1ffa）はmetadata1058bytes＋JSONL0bytesのみ、終了summaryなし。受信側3コードの記録SHAは現版一致だが、sender反映・接続・元odom受信/進行・正常終了は未確認。空ログの原因は断定しない。原archive/展開原本はrecordings/2026-11-16/odometry_metadata_live_intake_r01へ保持。再撮影/走行/再記録を直ちに要求せず、GPUPCでUI通常終了後のls/wc/summary出力を確認する。runtime変更なし、既存200テストを再利用。日報・Git push未依頼。

## 11/16最新：元odometry metadataを送受信する実装完了（両PC未反映）

[実装・検証・反映後手順](Experimental_results/2026-11-16/odometry_metadata_r01/README.md)。ユーザー「進んでください」で、実ログの全0を初期0/受信0に区別する段階を実装。新driver_odometry_observation.py、webrtc_stream.pyの任意sidecarと辞書1項目、driver_telemetry_recording.pyの対応schema保存だけを変更。旧UI値/操縦publish/topic/camera/頻度/距離/FFBは変更なし。

元header stamp整数ns、twistのchild_frame_idとpose header.frame_id、同じcallbackのv/ω、callback受信有無/順序・sender monotonic時刻/経過、stamp最大値の進行/反復/逆行/経過を保持。sample_fields_validは構造検査のみで物理/鮮度認定ではない。observer初期化/観測/読出し異常はmetadataだけ不採用、競合は待たず明示。ROS header時計は不明のままで、sender/receiver時計へ勝手に対応させない。全FFB/鮮度/clock認定false。

新sender metadataがあればreceiverはv2 envelopeへ厳密検査/独立コピーして保存。旧senderはv1維持、未知版/不正metadataは理由付きnull。旧トップレベル数値はそのまま、新coherent観測は入れ子のみ。旧measurement_valid等はnullで、offline joinerへ未接続。旧ログのSHA/内容を更新して新metadata付きとは扱わない。

正式results_r02のfake ROS callback→sender JSON→実receiver callback→保存14/14成功、v2 13＋v1 1、開始終了込み16events/drop0。新観測20＋新AST1を含む関連200テスト成功（先行63/170等と重複）。TelemetryNode固定ASTは正確なmetadata追加5箇所を除くと旧hash一致、sender control/camera/spin/receiver keyboard/ROS/control hash維持。測距/表示計算12ソース全byte不変。r01は初期化例外防御前の成功履歴。合成rawはrecordings/2026-11-16/odometry_metadata_synthetic_r02。

この変更はまだローカル未commit/未push、GPUPCとmatsunuc双方への新反映が必要。前回の「GPU反映済み」はこのmetadata追加前の記録機能の版。双方に反映できた後、停止状態の短時間通常送受信で新保存先received_telemetry_odom_r01へ記録し、同名archive received_telemetry_odom_20261116_r01.tar.xzで提出する手順を準備済み。追加撮影/コーン移動/走行/画面録画は不要。実ROS/カメラ/ネットワーク/GPU/機体/G923起動、外部反映、日報、Git pushは今回実施していない。

## 11/16最新：GPUの実telemetry記録を受領、記録疎通確認は完了

[実ログ全件監査](Experimental_results/2026-11-16/receiver_telemetry_live_audit_r01/README.md)。received_telemetry_20261116_r01.tar.xzの3ファイル完備。session22d50ca3b78c41c0b0517b82e5300c4e、単一receiver時計、peer_begin1＋telemetry2,208＝2,209events、約93.772秒・23.536Hz。stateclosed/errornull/donetrue、queued=written2209、1,480,656bytes一致、queue/lock/drop/受理後破棄0、sequence1〜2209連続。GPU記録metadataのUI/recorder sourceSHAは現ローカルと一致。

offered2210/rejected1で末尾番号2210が未保存。正常stop後のpeer終了callback経路と整合するが理由/event未記録なので断定しない。終了eventの保存はなし。受理済み範囲の欠落や記録機能失敗とせず未確定の末尾拒否として残す。受信→writer時刻P95 .615ms/最大5.636ms（ディスク完了/通信遅延でない）、投入最大.1801ms（callback全体でない）。受信間隔最大369.78msの原因/FFB100ms鮮度は未認定。

全telemetryのv/ω/speed/IMUyawは0、無効値0件。ただし元clock/stamp/frame/measurement_validは全nullなので、実測停止と未受信初期0は区別不能。次はsenderの元odometry時刻/frame/受信済み状態等のmetadataと受信側対応schemaの実装段階（まだ未実装）。同じ撮影/記録の再提出や追加走行は不要。時計対応・現取付車体変換等は後続の結合前に必要。

正式results_r02、元bytes保管recordings/2026-11-16/receiver_telemetry_live_intake_r02。r01は初回成功履歴で原本も保持。新監査9＋記録22＝31テスト成功、runtime170は未変更SHA一致で再利用。runtime/操縦/sender/FFB/profile/原本変更なし、実距離同期/露光同期/推論併走負荷/画面滑らかさ/勾配/FFB未検証。この解析では実機/ROS/GPU/FFBを新たに起動せず、日報・commit/push未依頼。

## 11/16最新：ユーザー申告でGPU反映済み。次は停止状態の短時間telemetry記録

ユーザー「GPUPCに反映しました。次に進めてください」。開始時HEADc9534a2（1116v3）、worktree clean。前段の未commit/未push記載は当時の履歴。実GPUのファイルSHAや実記録は未検証。

[反映後の疎通確認](Experimental_results/2026-11-16/receiver_telemetry_recording_r01/README.md)を先頭に追記。既存受信を通常終了し、同じROS/Qt端末で `THETA_UI_NO_VENV=1 python3 src/webrtc_receive_ui.py --cam-width 1280 --cam-height 720 --telemetry-record-dir recordings/2026-11-16/received_telemetry_r01`。今回は記録だけの独立確認でmotion-distance/推論/参照を起動しないため距離欄は出ない。通常native送信へ接続して10〜20秒、機体停止・操作なし・録画なしでUI正常終了→summary確認→3ファイルをarchiveで提出。旧受信終了で送信接続が切れていれば従来の送信コマンドで再接続。既存directory/archiveは新しいr名を全箇所で統一し、削除/上書きしない。

runtime変更なし、170テスト成功は再利用。起動コマンドの実parser、記録ON/測距OFF、既存CLIの引数転送不要、圧縮の構文をローカル非起動検証する。まだ実記録/実通信負荷/同期/勾配/FFBの確認ではない。追加コード反映不要、日報・commit/push未依頼。

## 11/16最新：受信側の任意telemetry記録を実装（GPU未反映）

ユーザーへ「ファイル記録は動作の必須条件ではなく検証補助」と説明後、受信処理への記録実装を明示依頼された。[実装・使用手順](Experimental_results/2026-11-16/receiver_telemetry_recording_r01/README.md)。新driver_telemetry_recording.pyとUI受信callback/起動終了/CLIのみ変更。既定OFF、`--telemetry-record-dir`でrecordings配下の未使用directoryを指定。callbackは固定5スカラー抽出＋有界queue nonblocking投入、専用threadでJSON/ディスク保存。最大16MiB/10万件/queue128既定、欠落counter・記録だけの失敗停止・最大2秒close/不完全終了警告・排他作成。

現senderは未変更。受信速度/ヨー/送信wall時刻は記録するが、元clock/stamp/frame/measurement_validは不明null、鮮度未認定。旧telemetryを実測/同期/FFBへ自動昇格せず、offline_motion_record/joinerとも別schema。接続sessionを測距と共有し、再接続/旧peer遅着は原sessionのまま保持。process内時計IDは同期証明やOS boot IDではない。

fake peerで実callbackを実行し、25通知/25telemetry＋開始終了4＝29events、2session、drop0、19,418bytes、正常closeを保存。通常合成の最大投入0.166ms未満は実機性能保証ではない。新記録22＋新AST1を含む関連170テスト成功。遅いwriterでqueue満杯でも100/100 UI通知、disk error/broken observerでもcontrol通知維持、無効値/既存非上書き/有限close等を確認。最初のfake video試験は実呼出しが渡すsession引数を省略していたため修正し、productionへ架空ID補完を追加していない。旧callbackは正確な観測2箇所だけを除くと従来固定AST hash一致、操縦/ROS/keyboard/sender hash不変。旧測距/表示計算12ソースも全byte不変。

集計receiver_telemetry_recording_r01/results_r01、合成生ログrecordings/2026-11-16/receiver_telemetry_recording_synthetic_r01。GPU未反映・未commit/未push。反映後、既存受信コマンドへ `--telemetry-record-dir recordings/2026-11-16/received_telemetry_r01` を追加可能（既存名なら新名）。ローカルで実ROS/カメラ/ネットワーク/機体/G923は起動せず、実記録・負荷・露光/運動同期は未確認。記録確認自体のために追加撮影/実測/走行/録画を要求しない。日報・Git pushは今回未依頼。

## 11/16後続：時刻・有効性付き運動レコードと距離の受信時計基準結合を実装

[保存・結合処理と結果](Experimental_results/2026-11-16/motion_time_join_r01/README.md)。新driver_motion_time_join.pyはオフライン専用で実行UI/telemetry/ROS/FFBへ未接続。元整数ns時刻/元時計/受信時計/frame/受信時刻/記録時刻/有効性/符号付きv・ωを保存。未受信nullと実測0を区別、指令値/旧telemetryを実測認定しない。MotionLogは排他的新規作成・件数/容量/行長制限、readerは重複キー/NaN/途中行等を拒否。

時計対応はアンカー・適用区間・誤差上限・根拠IDを明示し、区間全体で過去性/鮮度/ずれを判定。無効更新で旧候補破棄、元stamp/受信/記録/sequenceの重複逆行拒否、時計巻戻り/非有限/巨大整数で値失効。未来nearest/補間/zero fillなし。対応先は映像受信時刻で露光同時刻ではない。clock宣言やSHAは独立した実時計認定ではなく全出力non-controllingを維持。

正式results_r02：合成20/20ケース（正逆走・実測0で3組生成、不足/指令/時計/期限等17保留）、合成19レコード保存往復同一。実保存51,202件で距離19,297/保留31,905を維持、実運動レコード0なので結合0・運動値nullを確認。既知3画面距離も同一。新27＋関連計127テスト成功（先行56/82/90と重複）。r01は初版成功履歴で正式版ではない。raw派生はrecordings/2026-11-16/motion_time_join_r02。

試験ずれ50ms/運動年齢100ms/clock誤差5msは合成呼出し値で実機採用やFFB要件達成ではない。次は元odometry時刻/frame/受信済み状態のmetadata収集と受信側受動記録を実通信へ接続する実装段階（未実装）。callbackへ同期ディスクI/Oを持ち込まない。実機操作・追加撮影・GPU反映は今回不要。元測距12ソース/telemetry/UI/操縦/FFB/profile/原画像/生ログ不変。車体XY・勾配・ROS送信・実FFBは未生成/未起動。日報・commit/pushは今回未依頼。

## 11/16後続：保存許可点のカメラ基準床面ベクトルを復元。次は運動情報の保存・結合形式

[空間入力の監査](Experimental_results/2026-11-16/motion_spatial_inputs_r01/README.md)。ユーザーの「すすめてください」で、目標資料の作業範囲2（空間/運動の結合条件整理）へ進んだ。RESEARCH_GOAL.mdの「今回の依頼は1まで」は直前依頼時点の範囲記録であり、この後続依頼では2のオフライン検討まで実施。ROS送信・実機操作・FFB出力は引き続き含めない。

正式全ログ16ファイルとhandoff r02をSHAで結び、主結果/受け渡し51,202件のsession/frame/受信時刻/profile一致を確認。表示許可19,297件の元支持画素から、仮定床面の直下点→支持点ベクトルを光学座標で復元。長さは全件元距離と1e-12m以内（最大差1.333e-15m未満、物理精度ではない）。保留31,905件の位置はnull。新10＋関連計82テスト成功（先行90や31と重複あり）。生派生JSONLはrecordings/2026-11-16/motion_spatial_inputs_r01、正式集計results_r01。

新driver_motion_spatial.pyはオフライン専用で既存実行系へ未接続。光学座標の水平ベクトルは車体XYではない。床法線は車体yawを決めず、原点も異なる。現在取付の車体↔光学変換・時刻/有効性付き実測v/ω・車幅/障害物点の意味が必要。既存の紙座標変換、UI表示用pitch/offset、bird_eye既定幅を今回値へ無断採用していない。

今回提出構造化ログに運動/元ROS時刻/車体変換の該当フィールドなし。現地に別rosbagがないという意味ではない。現在のtelemetryはodom v/ωを送るが元header時刻/受信済み/元測定鮮度を保持せず、送信wall timestampと測距の受信monotonicは別時計。指令値優先のUI予測も実測入力とは別。次は時刻・有効性付き運動レコードの保存/結合形式をローカルで準備し、合成で欠落/期限/時計不明を検証できる。既存距離確認の再撮影・GPU反映は今回不要。既存12計算ソース/profile/画像/操縦/FFB不変。日報・commit/pushは今回未依頼。

## 11/16最新：最終目標を抵抗型リスク勾配FFBへ更新、保存ログの距離受け渡しを検証

**最終目標の入口は[RESEARCH_GOAL.md](RESEARCH_GOAL.md)。** ユーザー指定のFFB_feedback_control/docs/2026-10-21_risk_gradient_ffb_plan.mdを全文確認。差動2輪遠隔操縦でωに対するリスク感度をG923の危険側抵抗へ写像し、安全側への誘導トルクを出さず手動権を保持する。距離計算は接近情報／リスクの入力という中間段階で、最終目標を単なる距離表示や接近通知だけへ縮めない。外部原本は未変更、読取りSHA331dbab8c3879f443f49202334de5517df204820f113f8fab5cb8cfd175088ab。原本のPhase1〜4実装／synthetic dry-run済み記載は今回の実機認定ではない。

ユーザーがこのPCでpush・GPUでpull済みと申告し、GPU端末で新panel_textの日本語出力を確認済み。下記の過去「UI未push／GPU未反映」は当時の履歴。開始時mainはorigin/mainと一致・clean、HEAD4dc26e3（1116v2）。実際の運転画面の新レイアウトは未確認だが、そのためだけの再走行・撮影は要求しない。

[保存ログの受け渡し結果](Experimental_results/2026-11-16/motion_range_handoff_r01/README.md)。新driver_motion_handoff.pyはオフライン専用で既存実行系へ未接続。元結果／表示レビュー／bridge受理から距離・保留・元受信monotonic時刻・session/frame・参照識別をJSON化し、独立受信側でschema・明示session／参照・順序・期限を検証。無効／例外／時計異常では保持値を消し、zero fill／旧値保持／比較値救済なし。0.5秒は測距用の受信時刻基準で、FFB指令100ms／challenge条件と混同しない。

正式r02：51,202件JSON往復、数値19,297全件元値同一、距離なし31,905全件null。既知3画面の値・frame・元時刻を保持。遅延+100msで数値19,297、+400msで19,296、+501msで0。最後の値の期限切れクリアも確認。新21＋関連計90テスト成功。全sampleはrecordings/2026-11-16/motion_range_handoff_replay_r02、集計はmotion_range_handoff_r01/results_r02。r01は初版の成功記録で現在版の正式結果ではない。

スカラー距離から車体XY・追跡ID・TTC・左右勾配・力覚指令は生成していない。次は車体基準の障害物位置と同時刻の車速／ヨー入力の対応を整理する段階。ユーザーの今回承認は保存ログ検証までで、ROS送信・G923実出力・hardware arm変更は含まない。追加実機・撮影・GPU反映不要。旧計算／表示判定12ソース・profile・画像・操縦・既存FFBを変更せず、日報・commit/push未依頼。

## 11/16最新：対象範囲・保留理由の日本語UI説明を実装。GPU PCは未反映

[表示例・反映手順](Experimental_results/2026-11-16/motion_panel_guidance_r01/README.md)。driver_motion_presentation.pyを新設し、UIラベル初期化／更新だけで呼ぶ。既存bridge.panel_textの元数値・frame・age・body-review世代・英語コード／注意文を維持し、日本語の実ROI・状態理由・非制御注意を追加。no_candidateを範囲外と断定せず、自己遮蔽も可能性として説明。QLabel PlainText固定。ROIは起動引数、未指定を中央へ暗黙固定しない。映像への枠描画は今回なし。

新12＋関連計71テスト成功。fake peer・制御/ROS/keyboard/sender AST不変・古い数値の非表示・入力非変更を確認。合成Qtラベル3点をoffscreen描画し日本語・折返し・高さを確認（実機画面ではない）。先行実機監査の計算/参照/guard/bridge/protocol等12ソースは全バイト不変。runtime変更はUIと新説明moduleのみで、距離計算・profile・しきい値・採否・制御変更なし。

GPUへは未反映・未push。2ファイルのmotion_panel_guidance_update_r01.patchを作成、SHA 86dbd43a0188690adbc48c21ef924daac1762fb75f95f7cf76351adf6c7c4b7c。Downloadsへコピーし、READMEのSHA→reverse check済み判定→正方向check成功時だけ適用する分岐を使う。正逆check・二重適用拒否は隔離fixtureで検証済み。GPUは受信停止のまま、日本語端末出力の確認だけ可能。追加撮影・測定・走行・録画や終了済みr01の受信再開は不要。実GPUフォント・全運転画面配置は未確認。日報・commit/push未依頼。

## 11/16後続：保存3支持点の感度を計算し、診断表示の利用範囲を整理

[感度と利用条件](Experimental_results/2026-11-16/range_sensitivity_r01/README.md)。追加実機を使わず、正式全ログのSHA／保存profile／カメラ／設定へ結んだ3点の距離を再計算。ログと1e-12m以内で一致（最大丸め差4.45e-16mで物理精度ではない）。支持点x/y各±1px・高さ±1cm・対象方向の床法線±1度の一因子計27ケースをCSV/JSON保存。2m地点はy1px約3.90cm／高さ1cm約3.40cm／法線1度最大約13.42cmの影響。これは仮定感度であり今回の差の原因・実際の取付誤差・信頼区間ではない。法線回転は対象ごとの光線平面で、車体pitch/rollの実測ではない。新10＋関連計69テスト成功、先行67等と重複あり。

利用判断を「条件付きの前方中央・赤コーン1本の運転者向け診断表示」と明文化。11/13の走行機能・11/16の3画面確認を未確認へ戻さず、全距離精度・接触距離・傾斜補償・制御認定とは分ける。現行ソフト出力0.2〜4mを実測確認済み範囲と混同しない。次に優先するソフト改善は対象範囲と保留理由の分かりやすい表示で、採否や距離を変えない。今回UI変更はまだなし。runtime・profile・しきい値・画像・ROS/FFB変更なし。追加実機・撮影・受信再開不要、日報・commit/push未依頼。

## 11/16最新：全ログ監査完了。3画面の値・参照・正常終了が一致

[正式監査](Experimental_results/2026-11-16/body_display_range_audit_r01/README.md)。body_guard_full_20261116_r01.tar.xzは16点完備。主／表示レビュー／bridge各51,202件・比較51,200件を照合し、pin5186の完全主元行SHA・PNG/BGR・初回4点・発行参照バイト・12コードSHAとprofile/config・記録重みSHAが一致。主／比較正常終了・child0・エラー／強制killなし。sent-returned差1、比較未処理差2=上書き1＋終了未処理1を確認。

画面frame34957／45469／46432に元主値・表示許可・bridge受理・別比較が対応し、画面1.005／1.480／1.960mと3桁丸め一致。申告実測1／1.5／2mとの差+0.5／-2／-4cm。各画面±0.5秒の31／30／30件に数値途切れなし（1.003940〜1.005149／1.480214同値／1.957462〜1.959566m）。短文脈は実測に対応する静止区間全体の証明ではなく、常時±4cm・独立精度は未認定。

load後27,073件：元数値19,324→表示19,297、追加保留27=自己遮蔽22＋参照範囲外5、元保留救済0。全許可元値同一・bridge受理、全19,324支持列の判定再計算一致。レビュー完了age P95/最大19.00/108.06ms、主完了からレビュー追加経過P95/最大0.51/1.92msで露光〜GUI総遅延ではない。非同期比較と主表示は別経路。

原本・全timingはrecordings/2026-11-16/body_display_full_intake_r02、正式JSONはbody_display_range_audit_r01/results_r01。初回raw r01はパス記録の不整合で集計JSON発行に失敗した途中成果で、削除せず保持。パスresolve修正後r02へ新規取込し成功。既存監査へ参照・pin原本の明示パス引数だけ追加、旧既定と検証は維持。今回の現地3地点確認は完了、追加撮影・再測定・走行不要。runtime・校正・しきい値・制御変更なし、日報・commit/push未依頼。

## 11/16最新：1／1.5／2mの画面3点が揃った。次は通常終了・closed圧縮提出

[3地点記録と圧縮手順](Experimental_results/2026-11-16/body_display_range_check_r01/README.md)。同session・参照pin5186／世代1で、申告実測1.000→画面1.005m（frame34957）、1.500→1.480m（45469）、2.000→1.960m（46432）。差は+0.5／-2／-4cm、今回3点の絶対差最大4cm。申告実測の不確かさ・時系列変動未確認で、常時±4cm・全範囲精度・制御利用を認定しない。画面3点と計算値をobservations.csvへ保存、校正へ合わせ込まない。

現地の追加測定・走行・録画・再pin・再loadは不要。受信を通常終了して端末へ戻り、既存11/14pack_submission.pyのclosedモードに本日主driver_body_guard_live_r01／比較body_guard_live_r01を指定し、Downloads/body_guard_full_20261116_r01.tar.xzとして提出。拒否されたらエラー共有、削除・強制終了・受信やり直しで強行しない。同名archive時は出力名だけ変更。受領後、3画面の正確なframeと主／レビュー／bridge・pin元行SHA・参照バイト・終了状態を監査する。実測に対応する静止区間を未確定のまま周辺全ログを精度評価へ混ぜない。日報・commit/push未依頼。

## 11/16後続：参照active・主画面の数値復帰を確認。実測1mに対し表示1.005m

[観測記録](Experimental_results/2026-11-16/body_display_range_check_r01/README.md)。ユーザー貼付statusで同sessionのstate=active／reference_frame5186／generation1／scope=true／error=nullを確認。frame24780のno_candidateは元主も候補なしであり参照load失敗ではない。会話添付画面では候補なしと数値0.955m（frame28079）をそれぞれ確認した。異なるframeを同時刻として扱わない。

ユーザー申告で、カメラ直下の床点から台座手前辺中央までの床面直線距離1.000m、表示1.005m。添付画面も同session／frame34957／body-review gen1／receive-age16msで1.005mを確認。申告実測との差+5mm（+0.5%）をCSV保存。ただし1点・1時点、実測不確かさ未申告で、5mm精度・全範囲精度は認定しない。主全ログとスクリーンショットのローカル原本は未提出。次は機体・カメラ固定のまま、置ける範囲でコーンだけ1.5m／2mへ移して同一基準の実測・表示・変動を対応させる。走行・再pin・再load・再起動・録画は不要。runtime・校正・閾値変更なし、日報・commit/push未依頼。

## 11/16再開：現在pin5186の参照作成。次はファイルコピー・SHA照合・load

ユーザー申告で全機材使用可・GPU反映済み。開始時mainはorigin/mainと一致しclean、11/14扱いの運用helper等はcommit 811e455に含まれていた。以下の古い「未commit／未反映」記述は当時の履歴であり、現在の状態ではない。11/14はユーザーの実機作業なし。本日、受信・pin・圧縮手順の保存先を11/16へ統一した（pack_submission.py自体の場所は11/14のまま）。

[本日の参照と次の手順](Experimental_results/2026-11-16/body_display_reference_r01/README.md)。body_guard_pin_20261116_r01.tar.xzの4点は完備。session e52bb32f03d6488ebf37d769f46ec37a／pin5186／コピー時latest9191、pinned・reason=comparison_pin_requested・error=null・writer_done=false。PNG/BGR/sidecar/status一致、表示ゲートON、比較9＋表示7（重複除く12）コードとprofile/config・記録重みSHAがローカル一致。元主JSONL未提出のため完全元行SHAは後日照合。

今回の元PNGから天板境界x270〜380・中央y448付近を新規に読取り、新しいreference.jsonを発行。SHAは60ebc44adee96cf21195fefb61dc4d988033e157971c764025e8a783f8d3edde。GPUのrecordings/2026-11-16/body_guard_live_r01/reference.jsonへコピーし、SHA一致時だけ同接続load1回→statusと画面下部を共有する。今回の参照は未push。送受信・停止維持、再pin・再起動・Lキー・走行・録画はまだ不要。

元画像のコーンはROI x270〜350より左寄りで、コピー時元距離もunavailable。参照activeと数値表示を分けて確認し、必要ならload後にコーンだけを画像x310付近へ調整する。ROI拡張・保留解除で救済しない。現在までのwitness保持・load成功・GUI・物理精度は未確認。参照は自己遮蔽棄却専用で距離校正ではない。11/13の走行確認をやり直す必要はない。rawはrecordings/2026-11-16/body_display_pin_intake_r01。runtime・校正・環境・制御変更なし、日報・commit/push未依頼。

## 11/14開始：11/13日報をpush完了後、実機不要の運用手順・提出補助を整備

11/13分はcommit **0ecfad2540c955ace62dd6b368971ecde6f86b08** としてorigin/mainへpush完了し、git ls-remoteでも一致を確認。push直後のworktreeはclean。11/13の日報・代表4点・最終走行監査とローカルhelperの変更を通常commitした。生録画・全ログ・重み・venvは追加していない。

その完了後、ユーザー指定に基づき [11/14分の運用・再開手順](Experimental_results/2026-11-14/guarded_display_operations_r01/README.md) とpack_submission.pyを作成した。現在pinのPNG／JSON／status原本／engine summary4点だけを選ぶpinモード、主／比較とも正常終了確認後だけ圧縮するclosedモードを用意。旧pinの一括混入・更新中ログの提出・同名archiveの上書きを防止する。新しいarchive名を選ぶだけで再圧縮でき、元データ削除・再pin・受信やり直しは要求しない。

GPUローカルの鮮度・sidecar／PNG SHA・native寸法・非制御flags・主出力と比較dirの対応を確認。元PNG復号BGR／主完全行SHAは解析側の役割として維持。fullはregular file・ファイル名集合・件数32・主256MiB／全512MiB・圧縮中の変化・symlinkを制限。一時コピーからatomic非上書き発行し、削除はhelper自身の一時コピーだけ。カメラ／ROS／モデルをimportせず、pin／load／操縦要求を送らない。

新日付の手順は11/14の新保存先を例示し、8つのBash構文と実motion引数parserで保存先一致を確認する。ダミーメタデータだけで検証し、実機・GPU PC・matunucは使っていない。測距・操縦runtime／閾値／校正変更なし。11/13に確認済みの走行診断表示・遮蔽保留・復帰を再撮影必須へ戻さない。

**11/14分はローカル未commit／未push。GPU PCへ新helperは未反映。** 11/14終業依頼はまだなく、日報も作成しない。検証記録はguarded_display_operations_r01/checks_r01を参照。次は実機を使う必要が生じたときに新接続の現在pinから再開するか、別の未解決課題を選ぶ段階。距離を使うROS／FFB・自動停止や無人遠隔走行へ勝手に広げない。

## 11/13終業：日報・代表4点を作成。push完了後の続きはユーザー指定の11/14分

[11/13日報](Daily_reports/2026-11-13_daily_report.md)と日報索引を作成。本日既存commit・未commit差分・3回の主要実機監査を整理し、別系列FFB/replay実装と今回の非制御測距を区別した。[代表4点](Experimental_results/2026-11-13/report_assets/README.md)は数値推移図SVG＋無加工1920×1200の遮蔽前／遮蔽保留／復帰画面PNG。元画面／図へバイト一致、入力と出力SHA・PTSをmanifestへ保存。生録画・全ログはGit対象外。

終業の対象9テストファイルは108件成功、代表4点と日報関連45リンクを確認。根拠はreport_assets/checks_r01/summary.json・tests.log。日報本文の200／60／44等は各段階の過去記録で、重複スイートを独立件数へ合算しない。ユーザー依頼によりこの研究分と日報を通常commit・origin/mainへpushする。結果はGit履歴と終了報告を参照。

**そのpush完了後に11/14作業扱いで続ける**というユーザーの明示指定。時計や既存11/13の実験日時を書き換えず、新成果物をExperimental_results/2026-11-14へ保存する。次は実機不要の運用条件・再開手順整理。走行診断表示・自己遮蔽保留・復帰は今回の条件で確認済みで、同じ実験を繰り返さない。実機操作・新撮影・ROS／FFB接続を勝手に開始しない。

## 11/13最新：走行中の表示ゲート・遮蔽保留・復帰を実画面＋全ログで確認完了

[全監査と図](Experimental_results/2026-11-13/body_display_occlusion_live_audit_r01/README.md)。body_guard_occlusion_r01_full_r02.tar.xzの18ファイルと20:27:27開始の約60.290秒画面録画を受領。予定は車体停止・コーン移動だったが、ユーザー確認で実際は車体の前進・後退。走行試験として記録し、停止車体でのコーン移動実績とはしない。独立オドメトリ・実測誤差は未検証。

録画の直接読取りframe49664〜51472、1,787件／source幅60.275秒。遮蔽前887件は元数値・表示許可887、遮蔽区間50558〜50935の373件は自己遮蔽372＋元ROI端保留1で表示数値0、復帰後527件は元数値・表示許可527。表示数値1,414は全件元値と同じ・bridge受理、元保留からの救済0。元主値約0.682〜0.731mが残る近接区間でも新表示側で棄却できた。今回の走行診断表示・自己遮蔽保留・復帰の確認は完了。同じ実験の追加撮影・やり直しは不要。

25原解像度画面を確認し、数値17点のsession/frame・3桁丸め・body-review gen1がログと一致。保留6点はUIにframe表示がないため完全同frame証明とせず、数値anchorのPTS対応観測幅58.15ms内の候補ログが同じ保留であることを確認。別アプリで隠れる2点はGUI成功件数から除外。未保存画素・全GUI描画・総遅延の証明ではない。

録画対応区間の主age P95/最大19.21/32.89ms、表示レビュー完了age19.76/33.26ms、主完了→レビュー完了P50/P95/最大0.42/0.60/1.54ms。約29.63件/秒、source gap最大86.83ms、範囲内sequence欠け22で常時30fps保証ではない。全体主／レビュー／bridge各52,645・比較52,642行一致、参照有効支持列13,039件の再評価もclear12,667／遮蔽372で一致。pin1677・17327の元PNG/BGR/sidecar/完全主元行SHA、発行参照バイト、記録重複除外12コードとprofile/config・記録重みSHA一致。

主sent52,646/returned52,645は終了未返却1、bridge退役は初回1。比較offered52,645/processed52,642は上書き2＋終了未処理1。主／I/O・比較writer正常終了、エラー・強制killなし、child=-15はSIGTERM、終了待ち56.39ms。rawはrecordings/2026-11-13/body_display_occlusion_full_intake_r01（18原本＋webm＋無加工の画面抽出＋全timing CSV）。Git側はresults_r01/audit.json・screen_audit.json・録画対応screen_window.csv・数値図SVG・再現コード／読取表。新7＋既存関連44テスト成功。

静止監査に明示run引数と比較CSV列を追加して再利用。今回主ログ232MBに対して主256MiB／計512MiBの明示上限を設定し、18ファイル安全取込を検証。runtime・閾値・校正・GPU環境は変更せず実機操作なし。次は確認済み構成の運用条件・再開手順整理。既定OFF・非制御／非ROS／非FFBを維持し、物理精度・床接地・取付再現・傾斜補償・接触距離は未認定。日報・commit/pushは今回未依頼。

## 11/13最新：遮蔽試験の再pin17327を受領、新参照作成。次はコピー→SHA照合→load

[新参照とload手順](Experimental_results/2026-11-13/body_display_reference_occlusion_repin_r01/README.md)。body_guard_occlusion_repin_r01.tar.xzの4点は完備。session24e1146277d043fa8c01d36e2ebe0651／pin17327／コピー時latest30613、pinned・saved2・writer_done=false・error=null、最新reason=comparison_pin_requested。前回のinput_gapは今回statusに出ておらず、コピー時の継続不確実フラグfalse。PNG/BGR/sidecar/status一致、表示ゲートON、記録9＋7コード（重複除外12）とprofile/config・記録重みSHA一致。元主JSONL完全行SHAは終了後に照合する。

現在PNGから境界x270〜380／中央y450付近を新規に読み、x300〜340のテープ部分は隣接境界から補間。旧pin361の境界流用ではない。現在session/frame/PNGに結んだreference.jsonを生成。SHAは2b75af07233ad001628e3be8277a8e0c90818acad2c78a56b24067fee5032f87。GPUのrecordings/2026-11-13/body_guard_occlusion_r01/reference.jsonへファイルコピーし、SHA一致時だけload1回→statusと画面下部を提出。新ファイル未pushなのでPullだけでは届かない。まだコーン移動・録画・走行・新pin・再起動・Lキーは不要。

同接続でactive／reference_frame17327／scope=trueと数値＋body-review genを確認後、既存の車体停止・コーン移動による遮蔽→復帰の録画手順へ進む。load失敗なら連打せず出力共有し、session書換えはしない。コピー後から現在までのwitness保持は保証せず実loadで確認。rawはrecordings/2026-11-13/body_display_occlusion_repin_intake_r01、根拠は上記results_r01/audit.json・reference_validation.json・reviewed_boundary.csv。既存intakeと生成器を再利用、前段階60テスト成功を再利用し、今回実入力と生成物のSHA結合を確認。runtime・閾値・校正・環境変更や実機操作なし、物理精度・床接地未認定、日報・commit/push未依頼。

## 11/13最新：遮蔽試験pin1677の4点は完備。ただしinput_gapで継続不確実、次は再pin

[判断と再pin手順](Experimental_results/2026-11-13/body_display_reference_occlusion_r01/README.md)。body_guard_occlusion_pin_r01.tar.xzを受領。session24e1146277d043fa8c01d36e2ebe0651／pin1677／latest2945、pinned・writer_done=false・error=null・saved1。PNG/BGR/sidecar/status一致、表示ゲートON、記録9＋7コード（重複除外12）・profile/config・記録重みSHA一致。原画像を確認したが境界CSV・reference.jsonは発行していない。初回results_r01はファイル整合性のみ、最終判断assessment_r02/audit.jsonはrequires_repin。

latest.reason=comparison_input_gap。gap後のwitness消去があり、state=pinnedだけではload可能といえない。ただしworker順序admit→pinなので、同じpin frameでgapが先だった場合にはreason=input_gapでもwitnessが残り得る。**この4点だけでpin後の失効と断定しない。** gapの発生frame・原因は主／比較全ログ未提出で不明。先行commentaryの断定は訂正済み。継続を確立できないため保守的に同接続で1回再pinし、最新reason=pin_requestedを確認する方針。

現地は停止・送受信維持、コーン／カメラを動かさず、manage_guarded_comparisonで同body_guard_occlusion_r01へpin→数秒後status。再gap/staleなら連打せずstatus共有して原因確認へ。新pinは1677より後・同session・saved2を想定。元フォルダに旧pinも残るためワイルドカードで全部コピーせず、手順のPythonでstatusが指す最新PNG／JSON＋status原本＋engine summaryだけをbody_guard_occlusion_repin_r01.tar.xzへ新規圧縮して提出。新参照前のload・録画・コーン接近・走行は不要。

rawはrecordings/2026-11-13/body_display_occlusion_pin_intake_r01。ローカル4点intakeにprefix指定、共通intakeにreason／継続不確実フラグ、生成器に発行拒否を追加。GPU runtime・閾値・校正・環境は変更せず、新パッチ不要。合成のgap前後両順序・生成拒否・prefix・再提出手順を含む関連60テスト成功。実機操作・日報・commit/pushなし。

## 11/13最新：表示ゲートの遮蔽・復帰確認手順を準備。新pin4点提出まで

[新手順](Experimental_results/2026-11-13/body_display_occlusion_live_r01/README.md)。静止全体監査完了後、ユーザーが継続を依頼。まず車体停止・コーン移動で「見える位置の数値→台座遮蔽時の保留→復帰」を確認する手順を作成。機体走行は要求しない。新保存先は主driver_body_guard_occlusion_r01、比較body_guard_occlusion_r01。前回GPUで確認済みのbody表示ゲートONを使うだけで、runtime・閾値・校正・GPU環境の変更や旧パッチ再適用なし。

**今の現地作業は、新受信／送信→停止状態でpin1回→PNG／同名JSON／status／engine summary4点をコピー圧縮して提出まで。** コピー先はrecordings/2026-11-13/body_guard_occlusion_pin_submit_r01、提出archiveはDownloads/body_guard_occlusion_pin_r01.tar.xz。稼働中ログ全体の圧縮や転送目的の受信停止は不要。こちらで新画像確認→現在session/pin対応参照作成→SHA付き専用load手順を提示する。終了済みpin361参照を流用しない。

load成功と数値復帰を確認した後だけ録画中表示を確認してA〜C各約5秒を記録予定。コーンは床上、手を離れた区間で確認し、車体接触・持ち上げ・カメラ操作はしない。可能な範囲で台座が隠れなければ無理をしない。no_candidate／ROI端等の保留は自己遮蔽ゲート成功に数えず、同frameの元主・レビュー・bridge・画面で切替を監査する。終了後は主／比較全ログarchive＋画面録画。数値は非制御／非ROS／非FFB、床接地・物理精度未認定を維持。

手順のシェル構文・実motion引数parser・送信引数AST・ダミー4点のコピー圧縮を確認。こちらからUI／実カメラ／CUDA／ROS・実機は起動していない。既存未commit変更を保持し、日報・commit/pushは今回未依頼。

## 11/13最新：表示ゲートONの静止全ログを監査完了。次は遮蔽時の表示保留・復帰

[全実行監査](Experimental_results/2026-11-13/body_display_static_live_audit_r01/README.md)。body_guard_static_r01_full.tar.xzは必要16ファイル完備、追加提出不要。session e011664e9b994ce1b070439efa875b6a／pin361。主・表示レビュー・bridge各28,369行が全件対応し、別比較28,367行も元主へ一致。発行参照バイト・元PNG/BGR/sidecar/status・pin完全元行SHA・profile/config・記録重みSHA・重複除外12コードSHAを照合。参照済み表示3,711件は保存された支持列から天板判定を再計算して全件clearに一致。全未保存画素／YOLOの再計算や独立精度認定ではない。

比較の参照有効化開始frame24754〜28485／約124.405秒は3,732件。元数値3,713→表示許可3,711、全件元値と完全同値＋bridge受理、救済0。開始2件だけ未取得／not_current保留、24756から数値許可し同種保留の再発なし。元測距のambiguous_upper_body_colour19件（28276〜28294）は表示・比較も保留し、その後復帰。possible_self_body_occlusionは0なので新主表示の実遮蔽棄却は未確認。終盤固定30秒900件は数値881／元保留19、表示のみ保留0。全体の長い未load待機を有効化後の失敗率へ混ぜない。

有効化後の主age P95/最大18.29/45.36ms、表示レビュー完了age18.73/45.98ms、主完了→レビュー完了の経過P50/P95/最大0.40/0.55/1.22ms。終盤30秒のレビュー完了age P95/最大18.61/26.11ms、処理間隔約30件/秒。これは関数専有CPU時間・露光〜GUI総遅延・全描画回数ではない。数値範囲1.4375〜1.4442mも独立実測誤差ではない。

主／I/O・比較writerは正常終了、エラー／強制killなし、child=-15はSIGTERM。主sent=returned28,369、初回古い入力のbridge退役1。比較offered28,369／processed28,367は上書き1＋終了未処理1と整合。rawはrecordings/2026-11-13/body_display_static_full_intake_r01。根拠は上記results_r01/audit.json／display_timing.csv。新7＋既存関連37テスト成功。

今回の静止確認は完了。次は新ゲートONで「遮蔽のない数値→台座遮蔽でWITHHELD→見える位置で復帰」の実画面とログの確認。最初は車体停止・コーン移動の方法を検討し、まだ走行を要求していない。受信終了済みなので再開時は新保存先・新pin・現在画像に結んだ新参照を使い、終了済みpin361参照を流用しない。物理精度・床接地・取付再現・動的床姿勢は未認定、診断値の非制御／非ROS／非FFBを維持。runtime・GPU環境変更や実機操作なし。既存未commit変更を保持、日報・commit/pushは今回未依頼。

## 11/13後続：body静止4点完備・表示ゲートONを確認。現在pin361参照を生成、次はSHA照合load

[最新参照と手順](Experimental_results/2026-11-13/body_display_reference_static_r01/README.md)。1113body.tar.xzのPNG／同名JSON／status／engine summary4点を受領。session e011664e9b994ce1b070439efa875b6a／pin361、コピー時latest8944・pinned・error=null・writer_done=false。PNG/BGR/sidecar/status一致、比較9コード＋表示7コードの記録SHAがローカル一致（重複除き12ファイル）。summaryでbody_display_guard.enabled=trueを確認し、GPU側新モードの反映と有効化が記録上確認できた。実GUI・連続レビュー・新負荷はまだ未確認。

現在PNGから天板境界x270〜380／中央y455付近を再読し、同session/frame/PNG SHAの新reference.jsonを生成。GPUのrecordings/2026-11-13/body_guard_static_r01/reference.jsonへコピー、SHA f93f4bd8e0c40fb4b6ee9e1fa3695520adc241d26c093ffca6e51334727a20d4を照合してから同接続load→statusと画面下部表示を提出。停止・送受信継続、今は走行・新pin・再起動不要。原本4点はrecordings/2026-11-13/body_display_pin_intake_r01。元行SHAは主ログ未提出で未照合。参照は未push。今回runtime変更・実機操作・日報・commit/pushなし。

4点intakeは既存3点checkを維持し、summaryを別検証。生成器は全4点SHA確認後、明示pin3点へ既存checkを適用するよう拡張。25関連テスト成功。物理精度・床接地・取付再現は認定していない。pin画像コーンはROI右寄りなので現在sceneの保留を無理に解除しない。

## 11/13後続：GPU側停止確認のpin361取得。元画像と新モードsummaryの提出待ち

[statusメモ](Experimental_results/2026-11-13/body_display_guard_r01/static_pin_status_note.md)。ユーザーからbody_guard_static_r01のstatus貼付けを受領。session e011664e9b994ce1b070439efa875b6a／pin361／latest1297、pinned・error=null・writer_done=false、参照generation0の未load。原主値約1.438868mは記録されているが表示可否の認定ではない。変更対象3コード（worker/stream/process）の記録SHAは現在ローカルに一致し、それらのGPU反映と整合する。表示ゲートONとbridge/新ヘルパー反映はstatusだけでは不明。

次は現在PNG・同名JSON・statusの原本3点に加え、主出力driver_body_guard_static_r01/motion_engine_summary.jsonもコピー提出してもらう。現在画像とコード・enabled確認後に同接続用参照を作成する。送受信・停止維持、旧参照load・再pin・再起動・走行は不要。現時点では新UI・実GPU負荷・物理精度未確認。今回開始時worktreeはcleanで先行変更は既にGitへ保存されているが、こちらから新たなcommit/pushはしていない。

## 11/13後続：自己遮蔽時の表示専用ゲートを実装。ローカル200テスト・既存1,186件評価済み、GPU未反映

[最新実装・結果](Experimental_results/2026-11-13/body_display_guard_r01/README.md)、[反映後の停止確認手順](Experimental_results/2026-11-13/body_display_guard_r01/live_check.md)。ユーザーの継続依頼で、主測距・元ログは保ち、表示のみ現在支持列の自己遮蔽棄却を適用する明示opt-inを追加した。`--motion-body-display-guard`（子は`--body-display-guard`）は既定OFF、比較dir必須。旧コマンドでは表示は変わらない。今回の変更はまだcommit/pushせずGPU PC未反映なので、Pullだけでは届かない。

driver_body_display_guard.pyを新規追加、既存stream/workerからpin/PNG検証済み参照コピーだけをnonblockingで取得し、現在の主support_observationへ既存compare_self_bodyを適用。非同期比較数値・half-pixel救済は使わず、数値変更・平滑化なし。GPU子で別motion_display_reviews.jsonlと任意IPCレビューを生成、bridgeは同session/frame/source時刻・元数値と権限falseを確認して元値かWITHHELDを表示。参照未load/失効/競合/古い入力/別session等では元数値へ戻さず保留。新機能がない旧worker応答もON時は拒否。操縦・ROS・FFB・送信のコードは変更していない。

元r02録画区間44063〜45275の1,186件を既存supportログからオフライン評価。元数値1,178→表示数値911（元値と全同値）、自己遮蔽267件保留、元ROI端保留8件維持、近接停止177/177件保留。最終根拠results_r02/evaluation.json/CSV。ゲート単体ローカルCPU P50/P95/最大0.47/0.85/5.21ms、実GPU追加負荷ではない。元ログSHA不変。過去参照が有効だった区間の後解析で、新表示が実機で動いた証拠や精度認定ではない。

新19＋関連200テスト成功：合成画像・memory pipe・実ローカル子processで保留→遮蔽保留→正常数値復帰、元主ログ/IPC数値不変、失効・不正IPC・ロック競合・gap/世代棄却、既定OFF・操縦AST不変等。2件の旧モジュール名文字列検査を実ImportのAST検査へ精密化し、直接import禁止は維持。実カメラ／ROS／実YOLO/CUDAは起動していない。

次は新規1＋変更4のsrcと関連テストをGPUへ反映後、カメラなし単体確認→新保存先driver_body_guard_static_r01/body_guard_static_r01で停止確認。新モード未loadのWITHHELDは正常。現在pin3点を同接続維持で提出し、新参照SHA照合→load→表示復帰を確認する。今は追加走行・追加録画不要。実UI/pin/load・GPU負荷・物理精度・取付/床姿勢は未確認。過去実験のコードSHAを新コードに書換えない。日報・commit/pushは今回未依頼。

## 11/13後続：走行r02の録画・全ログを監査。走行時更新を確認、近接主表示が残課題

[最新監査](Experimental_results/2026-11-13/guarded_motion_live_audit_r02/README.md)。guarded_motion_r02_full.tar.xzの39ファイル＋約40.426秒の画面録画を受領。原本はrecordings/2026-11-13/guarded_motion_full_intake_r02。ユーザー申告の録画前試走は保持して評価から除外し、録画session24aad0a8d31d46eeb33ef252b0d18475／frame44063〜45275だけを固定。25点の原解像度画面を目視し、表示frameと主距離3桁丸めが全点でbridge受理済み主ログに一致した。実動作は短い初期停止→接近→近接停止→離脱→約10秒停止。境界は目視概略で独立オドメトリではない。

録画対応40.416秒は主／比較1,186件、全件参照有効・bridge受理、約29.32件/秒。主数値1,178／ROI端保留8、比較数値911／自己遮蔽保留267／ROI端保留8。両方数値911件は完全同値。主age P95/最大20.90/43.67ms、比較service P95=5.02ms、比較age P95/最大24.84/69.05ms。主33.33ms超過1件、source gap最大174.86ms、sequence ID27個には主／比較共通で結果がない。常時30fps・露光〜表示遅延・全GUI描画や独立精度とは別。

**近接時は主が約0.65mを出し続ける一方、別比較はpossible_self_body_occlusionで保留。** 録画14〜20秒は主数値177件／比較保留177件。画面でも台座が天板に隠れ、主支持点y455付近が天板境界へ達する。主数値の小さい揺れを精度良好と認定しない。比較はログ専用なので主表示にはまだ棄却が反映されていない。次は追加撮影ではなく既存証拠で主出力の自己遮蔽保留方針・回帰検証を検討。主への反映は別実装判断、今回runtime・閾値・平滑化・ROS・FFBを変更していない。

全体主45,530／bridge45,530／比較45,527行が整合。pin1062・18497の原PNG/BGR/sidecar/主元行SHA、発行参照バイト一致、記録9コードSHA・profile/config・記録重みSHA照合。参照generation2はframe30258から有効。主sent45,531/returned45,530で終了未返却1、比較offered45,530/processed45,527は上書き2＋終了未処理1と整合。主child0・強制killなし・errorなし、主／I/O・比較・evidence正常終了。evidence10組すべて元行まで一致、録画内は44302・44793のみ。比較救済1件43801など録画前の結果を今回成功に混ぜない。

根拠はresults_r01/audit.json（全体）、screen_audit.json（録画内）、screen_window.csv、screen_anchors.csv・図。カメラ／画面画像は加工せず、図はログ数値だけ。新7＋既存関連を含む50テスト成功。追加提出不要。物理精度・動的床姿勢・取付再現・制御採用は未検証。日報・commit/pushは今回未依頼。

## 11/13後続：r02 load失敗後の再pin18497を確認。新参照をSHA照合してload

[最新参照・手順](Experimental_results/2026-11-13/guarded_motion_reference_r02_repin/README.md)。r02で旧r01参照からframe516 PNGを探してload失敗し、内部witnessもinvalidateされた。その後正しいframe1062参照を入れてもwitness不在で拒否。明示再pinを依頼し、1113motionr02_1.tar.xzを受領した。session24aad0a8d31d46eeb33ef252b0d18475は維持、最新pin18497／copies時latest20232／pinned・snapshots_saved=2・error=null。PNG/BGR/sidecar/status一致、記録9コードSHA一致。主元行SHAは主ログ未提出で未照合。

現在のframe18497画像を独立に読取り、x270〜380／中央y455付近の天板境界から新referenceを生成。旧frame1062参照ではない。同名ファイル混同を避けるためGPU PCのrecordings/2026-11-13/guarded_motion_r02/reference.jsonへコピー後、生成物SHAを照合してからload→status提出する。停止・同接続継続、今は走行・再起動・再pinしない。失敗したらload連打せず出力共有。active確認後に画面録画中表示を確認して短距離低速直進へ。

原本はrecordings/2026-11-13/guarded_motion_repin_intake_r02。ローカルintakeのsaved数を整数1〜8へ拡張し、最新pin/requestの厳密一致は維持。関連19テスト成功。runtime・主表示・ROS・FFB・GPU環境変更なし。現在までのwitness残存・remote load/走行・床接地/物理精度は未確認。日報・commit/push未依頼。

## 11/13後続：録画忘れの再試行r02。新pin確認、次はr02のload→status提出

ユーザーはr01で走行したが画面録画を忘れたと申告。r01ログは保持し、3保存先をr02へ揃えて再試行する。[r02参照・再試行手順](Experimental_results/2026-11-13/guarded_motion_reference_r02/README.md)。1113motionr02.tar.xzはpin原本3点完備。session24aad0a8d31d46eeb33ef252b0d18475／pin1062、コピー時pinned・latest2926・writer_done=false・error=null。PNG/BGR/sidecar/statusのpin一致、記録9コードSHA一致。主元行SHAは主ログ未提出で未照合。原本はrecordings/2026-11-13/guarded_motion_pin_intake_r02。

現在画像から天板境界x270〜380／中央y455付近を新規に読み、同session/frame/PNG SHAのreference.jsonを生成。黄色テープ部分は補間、目安2px。r01より約4px下に見えるが床姿勢や取付変化量を断定しない。距離校正ではない。既存検証器を再利用しruntime変更なし。

GPU PCのrecordings/2026-11-13/guarded_motion_r02/reference.jsonへファイルコピーし、同接続・停止状態でload→statusを提出。active照合後に**画面録画開始・録画中表示を確認**して停止→短距離最低速直進→停止を行う。旧r01参照転用・再pin・Lキーは不要。新参照は未pushなのでPullのみでは届かない。現在までの接続/witness残存・load成功・走行結果は未確認。こちらから実機操作・日報・commit/pushなし。

## 11/13後続：走行確認用pinを受領、新参照生成。次は停止のままload→status提出

[現在参照・load手順](Experimental_results/2026-11-13/guarded_motion_reference_r01/README.md)。1113motionr01.tar.xzは必要3点完備、session f50fc9ecb85144518676084c4d001ec8／pin516。コピー時pinned・latest2708・writer_done=false・error=null。元PNG／復号BGR／sidecar／status一致、記録9コードSHA一致。主JSONL未提出なのでpin元行SHAの実照合は終了後。原本はrecordings/2026-11-13/guarded_motion_pin_intake_r01へ無加工保存。

現在PNGから局所天板境界x270〜380・中央y451付近を新規に読み、同session/frame/PNG SHAに結んだreference.jsonを生成。黄色テープ部分は隣接点間補間、目安2px。床姿勢・高さ・距離精度や取付再現の校正ではない。既存intakeの明示prefix指定と生成器audit/CSV指定を追加しただけでruntime・主表示・ROS・FFB変更なし。

GPU PCのrecordings/2026-11-13/guarded_motion_r01/reference.jsonへ**ファイルコピー**し、同接続・停止状態でload→status出力を提出する。未pushなのでPullだけでは届かない。現在接続/witness残存は未保証、load失敗時は出力共有。新pin・再起動・旧参照書換え・Lキーは不要。active照合後に走行手順5〜6へ進む。こちらから実機操作・日報・commit/pushは行っていない。

## 11/13後続：比較併用の低速直進手順を準備。まず新接続のpin提出まで

ユーザーが次段階の継続を依頼。[新しい走行確認手順](Experimental_results/2026-11-13/guarded_motion_live_r01/README.md) を用意した。前回静止r02は終了済みなので、主 `Experimental_results/2026-11-13/driver_guarded_motion_r01`、比較 `recordings/2026-11-13/guarded_motion_r01`、既存evidence `recordings/2026-11-13/guarded_motion_evidence_r01` の新3保存先を使う。static監査の未commit変更を保持。runtime・操縦経路・閾値・profile・環境変更なし。

**最初は停止状態で受信→送信→pin→PNG／同名JSON／status3点をコピー提出まで。新参照を用意しload成功を確認する前に走行しない。** 古いreferenceのsession書換え転用・旧パッチ再適用はしない。今回はload後の走行終了まで1接続を維持する。対象は赤1本、他コーンは最初から外し、取付後のカメラを終了まで動かさない。

load成功後だけ、現地監視下・従来最低速・短距離の直進と停止を、短い画面録画（映像＋主距離欄session/frame）と合わせて実施する予定。初回に旋回・後退・段差・接触・意図的遮蔽は要求しない。数値を制御・停止判断に使わない。録画は前回の一時値に対応する場面証拠のためで、native画素や独立実測の代替とはしない。

既存bounded evidenceを40組／128MiB／1秒で明示ONにするが、保存対象はcolour_contour_reaches_roi_edge保留だけ。数値の一時変動を自動保存する機能ではないことを明記した。終了後に主／比較／evidence3フォルダ＋画面録画を提出してもらう。7 shell例のbash構文と実motion CLI parserを確認しただけで、こちらから実UI／ROS／モデル／機体は起動していない。日報・commit/pushも未依頼。

## 11/13後続：静止r02の全提出物は完備、終盤30秒901件一致。過渡値8件は別課題

[最新の全実行監査](Experimental_results/2026-11-13/guarded_static_live_audit_r02/README.md)。提出guarded_static_r02_full.tar.xzは主／比較2フォルダの必要15ファイルが揃い、追加提出不要。開始HEAD `41f9a8b`、clean。session 9e961a39b4f54b0395eb140f52625755、主／bridge各29,101行が全対応一致、比較29,100行も元主行へ対応一致。pin330の元PNG／復号画素／sidecar／status／主JSONL完全行SHA、発行referenceとのバイト一致、profile／config・記録重みSHA・記録9コードSHAを照合。実測や全未保存画素を独立再計算したものではない。

参照有効は15858から13,293行、主／比較とも数値4,174で全同値（救済・棄却0）。多数の複数候補待ちを含む全体保留率85.41%を対象1本の失敗率と解釈しない。終端から固定30秒はframe28266〜29166の901行で、主／比較数値901／901・全同値・保留0、約30.005件/秒。主age P50/P95/最大13.57／17.81／27.60ms、比較service P95=4.99ms、受信〜比較完了P95=21.79ms・最大32.46ms。終盤主33.33ms超過0/901。露光〜表示・操縦込み総遅延や独立精度の認定ではない。

主／I/O・比較writerは正常終了。child_exitcode=-15はSIGTERM、強制killなし・worker_error/shutdown_error=null、終了待ち約63.34ms。比較offered29,101／processed29,100、終了待ちslot1件破棄と整合、比較slot上書き／tap失敗0。主入力tap_lock_drops=7は別。初回約1016msは主保留＋bridge退役1件であり、全区間の最大を終盤の最大と混同しない。

**未解決の過渡値：参照後に2m超の数値8件（最大3.5897m）。** 24971〜24976、26817、26829で主／比較双方に出ている。selected_colourはいずれもred、支持点y349〜369／355などへ上がり、終盤のy381と異なる。各瞬間の元画像・独立実測がなく、遮蔽・対象移動等の原因や誤りを断定しない。抽出CSV／診断は上記transients_r01。終盤の安定だけで全場面完成とせず、今回閾値や平滑化を追加していない。

静止の現カメラ→受信→実YOLO→主／別比較→参照load→終了は今回の条件で成立。同じログの再送・再静止試験・旧パッチ適用は不要。残るのは毎回取り外すカメラの取付／床profile整合と実測誤差、過渡支持点品質、比較ONの走行時更新・負荷。次の走行は現地監視・低速・診断値非制御の別試験として準備し、まだこちらから走行指示・実機駆動・主表示／ROS／FFB接続をしていない。

rawはrecordings/2026-11-13/guarded_static_full_intake_r02。根拠は上記results_r01/audit.json／paired_timing.csv／transients_r01。新監査＋既存parser関連18テスト成功、runtime／環境変更・実CUDA／カメラ／ROS起動・日報／commit/pushなし。

## 11/13後続：新r02の稼働中pin3点を確認、現在画像の参照を生成。次は同接続でload

[現在のload手順・根拠](Experimental_results/2026-11-13/guarded_static_reference_r02/README.md)。提出1113r02.tar.xzは内部名も1113r02だが、PNG／同名JSON／statusの必要3点が揃っており問題なし。開始HEAD `22d6f39`、clean。session 9e961a39b4f54b0395eb140f52625755、pin330、コピー時latest2794／state=pinned／writer_done=false／error=null。PNG・復号BGR SHA・pin全情報一致、記録9コードSHAも一致。コピー時から現在までの接続継続やwitness残存までは保証しない。

**この画像を新規に確認して境界x270〜380、中央y450付近を読み直し、同session／frame330／PNG SHA対応のreference.jsonを生成した。** 旧sessionの書換え流用ではない。黄色テープが境界の明暗を隠す部分は隣接点間補間。原画像は無加工。床姿勢・高さ・距離精度・取付再現を校正したものではなく、カメラを毎回取り外す未検証条件は維持。

次はこのPCの `Experimental_results/2026-11-13/guarded_static_reference_r02/reference.json` をGPU PCの `recordings/2026-11-13/guarded_static_r02/reference.json` へコピーし、同接続のままmanage_guarded_comparison.py load→status。新pin・再起動・Lキー・旧パッチ適用は今は不要。まずstatus出力を提出してもらう。active確認後は静止20〜30秒の主更新／比較／保留／鮮度を確認し、終了後に主出力と比較の両フォルダを提出。load_rejected／失効時は出力を共有し、session書換えや無条件の再pinをしない。

raw3点はrecordings/2026-11-13/guarded_static_intake_r02、根拠は上記results_r01/audit.json／reference_validation.json／reviewed_boundary.csv。新3点intake7テスト成功。実workerでのload・現地負荷・物理精度はまだ未確認。runtime／環境変更・実機操作・日報／commit/pushなし。生成した参照は未pushなので、GPUにはファイルコピーで渡す。

## 11/13後続：r01 pin画像は有効。ただし転送のため受信終了、次は新r02と3ファイルコピー

[提出監査](Experimental_results/2026-11-13/guarded_static_pin_review_r01/README.md)、[再開手順](Experimental_results/2026-11-13/guarded_static_pin_review_r01/restart_r02.md)。開始HEAD `0fb7377`、clean。提出guarded_static_r01.tar.xzの元PNG／復号画素／pin JSON／statusが一致。session ab3878cba91c4394a84fb907835ae3b2、pin1484。記録9コードSHA一致、比較6,857行は全て参照未load、主数値206行は比較ログ側の記録だけで主ログは未提出。state=closed／writer_done・shutdown_complete=true／error=null。ユーザーはファイル更新が続くため転送前に受信を停止したと説明した。古いpinを再開後の接続でloadしない。

**重要な取付条件：ユーザーはカメラの電源操作のため毎回取り外しており、基本の場所は同じだが100%一致とは言えない。** 今回の天板境界は中央y447で旧参照y458より約10〜11px上に見える。原因や姿勢変化量は断定しないが、録画間の床姿勢／高さの再現を検証済み扱いしない。現在画像の天板境界は自己遮蔽棄却用で、床法線・高さ・測距精度を補正するものではない。新校正一式や床マーカー撮影は今は要求しない。既存profileの距離は取付仮定を含む未検証の診断値として扱い、走行／制御採用とは分ける。

元画像の局所境界x270〜380をreviewed_boundary.csvへ記録したが、終了済みsessionのload用reference.jsonは作らない。次は主出力と比較保存先の両方を新r02にし、停止状態で通常受信→送信→pin。新PNG／同名JSON／statusの3点をいったん別フォルダへ**コピー**し、そのコピーを圧縮して提出。更新中ログ／元フォルダ全体は途中提出に含めない。受信・送信を維持し、新画像確認後に現sessionの参照を作る。接続断／失効時は報告。主表示・ROS・FFB・機体の操作変更なし。

生提出5ファイルはrecordings/2026-11-13/guarded_static_intake_r01へ無変更保存。結果は上記results_r01/audit.json。新intake9テスト成功、元画像の加工・実CUDA／カメラ起動・runtime変更・日報／commit/pushなし。

## 11/13再開：カメラ／実機使用可能。まず静止映像と現在sessionのpin

ユーザーから本日はカメラ等を使用可能との連絡。[本日用の静止手順](Experimental_results/2026-11-13/guarded_static_live_r01/README.md)を準備した。開始HEAD `793428d`、clean。runtime・環境変更や成功済み再生の繰返しはせず、主保存先を `Experimental_results/2026-11-13/driver_guarded_static_r01`、比較を `recordings/2026-11-13/guarded_static_r01` とする。フォルダが既存なら新しいsuffixを全端末で揃える。

GPU PCの通常運転UI環境で受信→matunucでmotion-native送信→停止状態で映像・主更新を確認→別端末からpin→元PNG／同名JSON／statusの3点提出が最初。まだ走行・画面録画・床マーカー・距離再測定・loadは求めない。受信／送信は同接続を継続し、こちらで現在画像から天板境界参照を用意してからloadする。過去参照のsession書換え転用はしない。カメラ取付位置・角度が前回から変わった場合は先に確認する。

GPU r04の反映・保存画像負荷確認は完了済み。旧パッチ再適用・Pullのやり直しは不要。IP／deviceは前回値なので本日の実際の値を優先する。本日こちらから実カメラ／ROS／機体を起動したわけではなく、日報・commit/pushもまだ行っていない。

## 11/11終業：日報・Git保存、次回はカメラが使える日の静止確認

ユーザーの終了依頼により研究を終了し、[本日日報](Daily_reports/2026-11-11_daily_report.md)・[代表3点／集計CSV／来歴](Experimental_results/2026-11-11/report_assets/README.md)・日報索引・この最新状態資料をcommit/push対象として整理した。開始HEAD `d313ac5`（1111v6）、worktreeはclean。runtimeとGPU r04監査は既存commitに保存済みで、今回は測距コードやGPU環境を追加変更しない。最終commit ID・push成否は終了報告とGit履歴を参照。

保存画像の負荷対策は一区切り。比較ONの主P95 23.91ms・28.96件/秒、r03との主640／比較322行一致、33.33ms超過1/320件。ただし常時30fps・通信／表示遅延・物理精度の完成ではない。次は [静止手順1から](Experimental_results/2026-11-11/guarded_async_comparison_r01/live_procedure.md) 進める。GPU r04実行PCでパッチ再適用・同じ再生・Pullのやり直しは不要。

matunuc／カメラが使える日に、停止状態で通常映像→現在native画像をpin→PNG／同名JSON／statusを提出→現在の天板境界参照をこちらで準備→同接続でloadし静止確認。初回確認に走行・画面録画・床マーカー・距離再測定は不要。カメラなしの今、必須の再試験や新撮影は求めない。旧参照のsession書換え転用・無人遠隔走行はしない。主表示・ROS・FFBへの比較値接続はない。

代表PNGは11/10の元14922のバイト一致コピーで本日の新撮影ではない。グラフ2点は監査済みr01〜r04のJSONから生成し、入力／出力SHAを保存。raw・重み・venv・別作業は追加しない。以前の各段階の「未commit／未push」は当時の履歴として読む。

## 11/11後続：GPU r04の主P95は23.91ms。保存画像の負荷対策を終え、次は静止実映像

[最新監査](Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r04/README.md)。ユーザーが `guarded_cuda_gpu_r04.tar.xz` を提出。開始HEAD `2cca269`（1111v5）、clean。元入力25・コード25のSHA、主640／setup4／warmup8／比較322行、両pin／参照／元画素・鮮度・終了を照合した。r03との差は予定したruntime5＋測定SHA追加1だけ。GPU PCはGit経由の今回runtime反映済み、Pullのやり直し・パッチ適用・同じCUDA再生は不要。

OFF/ON320組の検出枠・主判定一致、r03との検出枠・主判定640/640・比較の値／理由／flags322/322一致。主数値は保留画像反復で0、比較40数値は元14922反復の1.142471541888944mのみで独立精度検証ではない。両比較worker正常終了、slot上書き／tap失敗0。

比較ONの主P50は27.68→19.81ms、P95 45.22→23.91ms、ログ／tap込みP95 24.46ms、件数/秒26.54→28.96、33.33ms超過119/320→1/320（0.31%）。比較service P95 26.15→16.43ms、age P95 71.35→41.18ms。OFFは主P95 21.31ms・29.69件/秒。ON両blockの主P95が33.33ms以内になったが、開始間隔P95 36.73ms・最大117.32msが残るため、全フレーム30fps維持・実映像遅延の認定ではない。

**保存画像での負荷対策は一区切り。次はカメラ／matunucが使える日に静止実映像を確認する。** 現状このPC＋GPU PCのみなので今すぐ新撮影は求めない。[静止手順1から](Experimental_results/2026-11-11/guarded_async_comparison_r01/live_procedure.md)通常受信→送信→現在native画像をpin→PNG／同名JSON／status提出→こちらで現在境界参照を用意→同接続でloadし静止20〜30秒を確認。過去参照のsession書換え転用や、無人遠隔走行はしない。最初の確認に走行・画面録画・床マーカー・距離再測定は不要。主画面は現行のまま、比較値は別ログのみ、ROS／FFB／制御未接続。

監査helperは旧既定24を保ち、r04のみ明示25かつcolour依存SHA必須へ拡張。関連26テスト成功。未変更の測距404＋重複する測定メタデータ22テストはSHA照合で再利用し、今回の再実行数に加えない。正式記録は上記results_r01／checks_r01／checks_reuse_r01。rawは `recordings/2026-11-11/guarded_cuda_gpu_intake_r04/`。今回runtime／GPU環境変更・実CUDA／実機起動・日報／commit／pushなし。

## 11/11後続：間引きは見送り、捨てていた光線の逆算を削減。GPU r04待ち

[最新の変更・GPU手順](Experimental_results/2026-11-11/guarded_domain_only_r01/README.md)。matunucは使用不可、このPCとGPU PCのみ。単純な比較頻度制限は、r03の保存開始時刻で10Hz選択すると40数値機会のうち1回しか残らなかったため今回は実装しない。この数字は8画像反復の位相依存で、実カメラの検出率・精度ではない。根拠は [選択試算](Experimental_results/2026-11-11/guarded_cadence_r01/README.md)。

代わりにbbox中心／角／contextの有効域boolだけを使う呼出しから、捨てているrayの64回反復逆算を外した。`angular_fisheye_geometry` の同じ入力・ROI・最大半径チェックを共通化し、core／colour／lateral／upperの4モジュールで `pixels_in_domain` を使用。runtime計5ファイル変更。実際の支持点のray・距離式・閾値・丸め・校正・鮮度・参照失効・自己領域棄却は維持。主測距にも同じ意味の軽量化が効くが主判定は変えず、比較の頻度・thread数・権限／ROS／FFB接続は変更しない。

関連404テスト成功、元の式とray／validのbit単位一致。元8画像のbaseline／proposal全値一致、CPU比較P50 49.14→33.15ms（32.5%短縮）、P95 63.98→48.62ms。8ケースのunproject 61→1回、距離算出の1回は維持。GPU r03の比較320/320行（数値40）を新runtime＋模擬時計で再現。実子／pipe／threadの元8画像も主8/8一致・比較1.142471541888944m・別session拒否・元画素不変・正常終了。CPU時間をGPU性能や実映像遅延へ換算しない。

GPU測定の依存SHAリストにcolourモジュール1件を追加しただけの後続変更は、影響するCUDA試験22件を再実行して成功。404と重複するため426件の独立テストとは数えない。正式記録は上記フォルダchecks_r01／checks_metadata_r01／bench_r01／gpu_rows_replay_r01／pipe_replay_r01。旧hash固定監査は履歴であり、新ソースでそのまま一致すると案内しない。

次は今回の10ファイル限定 `recordings/2026-11-11/guarded_domain_update_r01.patch`＋manifestをGPU PCへ反映して、保存画像CUDA試験を新規 `recordings/2026-11-11/guarded_cuda_gpu_r04` に実行・全フォルダ提出。既にGitで反映済みならreverse **--check** が成功するので重ねてapplyしない。旧r01〜r03は保持。カメラ・送信・ROS・走行・画面録画は不要。GPU効果・30件/秒維持は未確認。今回は実CUDA／実機の起動、commit/push、日報作成なし。前回r03監査の未commit差分・別作業は保持。

## 11/11後続：compactのGPU効果を照合、比較ONは26.54件/秒

[最新GPU r03監査](Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r03/README.md)。ユーザーが `guarded_cuda_gpu_r03.tar.xz` を提出。開始HEAD `0576314`（1111v4）、clean。入力25・依存24のSHAを照合し、r02との差は予定したcompact関連runtime4ファイルのみ。更新済みで、パッチ再適用や反映方法の再確認は不要。

主640／setup4／warmup8／比較322行と両pin・元画素・参照・終了を照合。今回のOFF/ON320組は検出枠・主判定一致。r02との比較も検出枠・主判定640/640、比較値・理由・flags322/322一致。主数値は保留標本で0、比較40数値は元14922反復の1.142471541888944mだけ。独立精度検証ではない。両writer正常終了、slot上書き／tap失敗0。

GPU比較ONはr02の23.86→26.54件/秒へ改善。主処理P50 33.51→27.68ms、P95 55.59→45.22ms、33.33ms超過166/320→119/320（37.19%残る）。比較service P95 34.96→26.15ms、入力から比較完了までP95 93.67→71.35ms。OFFは主P50 22.78ms・29.62件/秒。中央値が33.33ms以下になっただけで30fps維持・通信込み実遅延を認定しない。

次は保存データで残るCPU処理内訳・比較だけの実行頻度を主測距優先の観点で検討できる。**追加撮影、同じ未変更GPU試験、パッチ再適用は今は不要。** 今回監査ではruntime・頻度・主表示・ROS・FFB・環境の変更なし。実CUDA／カメラ／機体をこのPCで起動せず、commit/push・日報作成なし。rawは `recordings/2026-11-11/guarded_cuda_gpu_intake_r03/`、根拠は上記results_r01。監査helperをrun／期待差分指定へ一般化し、新規6テスト成功。

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
