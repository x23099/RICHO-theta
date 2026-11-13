# 11/13 走行r02：録画中のリアルタイム更新を確認、近接時の主表示が残課題

## 結論

提出は必要な主・比較・evidenceの39ファイルと画面録画1本が揃っている。追加提出・撮り直しは現時点で不要。
**今回の条件では、機体の接近・離脱に伴って、実カメラ→GPU YOLO→主距離表示が更新されることを確認した。**
参照を読み込んだ別比較も同時に稼働したまま、主／I/O・比較・evidenceはいずれも正常終了した。

ただし、**台座が天板に隠れる近接区間では、主表示に約0.65mが残る一方、別比較は自己遮蔽の可能性で保留している。**
約0.65mを真の距離・精度良好と認定しない。現状の主表示にはこの棄却が反映されていない。
走行時の処理成立と、近接時の出力品質・接地・物理精度・制御採用を分ける。

ユーザー申告どおり録画前にも試走が含まれる。原ログは削除・間引きせず保持し、下記の評価区間に混ぜていない。

## 録画から選んだ区間

録画 `Screencast from 2026年11月13日 18時46分18秒.webm` は1920×1200、VP8、約40.426秒。
カメラnative画像ではなく、運転UI全体の録画。既存の青い矢印等も元録画の一部であり、解析で追加していない。
原解像度の25フレームを無加工で抽出・目視し、表示session prefix24aad0a8とframe番号・小数3桁の距離を読んだ。
25点すべてで、同一session/frameのbridge受理済み主ログの丸め値と一致した。
処理完了から実GUI描画までの全フレーム同期や、露光から表示までの遅延を測定したものではない。

評価対象は**frame44063〜45275**、主入力時刻7340.772257229〜7381.188698512（40.416秒）。
録画先頭から約0〜40.4秒に対応する。録画PTSと主source時刻のオフセット変動は25点で約54msあり、
走行開始／停止境界をミリ秒精度と扱わない。独立したオドメトリ・操作ログは未提出。

| 録画のおおよその時刻 | 場面 | 主数値／処理件数 | 別比較数値／処理件数 |
|---|---|---:|---:|
| 0〜2秒 | 初期停止（短い区間のみ） | 58/58 | 58/58 |
| 2〜14秒 | 接近、開始・停止境界を含む | 346/352 | 270/352 |
| 14〜20秒 | 近接停止、台座が天板に隠れる | 177/177 | 0/177 |
| 20〜30秒 | 離脱、開始・停止境界を含む | 291/293 | 277/293 |
| 30〜40.4秒 | 最終停止 | 306/306 | 306/306 |

最初に予定した「停止10〜15秒→直進→停止15〜20秒」そのままではなく、
短い初期停止→接近→近接停止→離脱→約10秒停止の実記録として評価した。
上記は既に行われた動作の読取りで、追加の後退・接近を依頼するものではない。

主表示の代表値は先頭1.440m、5秒1.209m、10秒0.814m、15秒0.652m、20秒0.654m、25秒1.033m、
30秒1.438m、終端1.439m。**距離変化の追従であり独立精度の誤差ではない。**
図は[ログ数値の比較](results_r01/screen_range_comparison.png)、根拠は[評価区間CSV](results_r01/screen_window.csv)。

## 録画対応区間の定量結果

| 項目 | 結果 |
|---|---:|
| 主／比較の対応件数 | 1,186件、全件bridge受理・参照有効 |
| 処理結果間隔からの更新頻度 | 約29.32件/秒 |
| 主数値 | 1,178件、輪郭がROI端に達した保留8件 |
| 比較数値 | 911件、両方数値の911件は完全同値 |
| 比較の自己遮蔽保留 | 267件（主は数値のまま） |
| 主入力から主処理完了age P50／P95／最大 | 14.41／20.90／43.67ms |
| 別比較service P95／最大 | 5.02／24.79ms |
| 主入力から別比較完了age P95／最大 | 24.84／69.05ms |
| 主age 33.33ms超過 | 1/1,186件 |
| 主source入力時刻の隣接gap最大 | 174.86ms |

常時30fps、露光から表示まで20.90ms、全1,186件が実際にGUI描画された、などとは主張しない。
source sequenceの1,213個のIDに対し対応ログは1,186件で、27個のIDには処理結果がない。
主・比較で対応が食い違ったという意味ではなく、通信・入力tap等のどこで欠けたかはこの集計だけでは特定しない。
画面全域の監視ではなく、明示ROI x270〜350等の現行検出条件での結果。

## 近接時の残課題

frame44406〜44677の範囲内に、別比較のpossible_self_body_occlusionが267件ある。
主支持点は天板境界y455付近に達している。別比較は支持列全体を現在の天板境界と照合し、
クリアランス不足として保留した。主数値範囲は約0.6512〜0.6816m。
特に録画14〜20秒は177件すべてこの保留であり、表示上の約0.65mの小さい揺れを測距精度の良さと解釈しない。
元数値フレームのnative画像は保存対象外のため、各支持画素の独立再抽出まではしていない。
ただし画面録画でも台座下端が天板に隠れる場面が確認でき、現在はこの別比較を主出力へ反映していないことが問題として具体化した。

次は追加撮影ではなく、既存の数値・支持点・現在境界・録画を使い、
**主表示でも自己遮蔽を保留する出力方針**を検討・回帰検証する。
比較値を無条件に採用したり、距離0.7m等の固定閾値で切ったり、平滑化で隠したりしない。
主表示への適用は別の実装判断であり、今回runtime・判定・操縦経路は変更していない。
カメラの取付再現・床姿勢／高さ・動的傾き補償・独立距離精度は別途未検証。

## 全実行の整合性と証拠

全実行は主45,530行／bridge45,530行、比較45,527行。各比較のsession/frame/source時刻・元数値が主行と一致。
全主行のinference_sourceはlive_cuda_yolo。pin1062・18497のPNG/BGR・sidecarと、主元JSONL完全行SHAを検証。
採用参照は発行済みframe18497のJSONとバイト一致、参照generation2はframe30258から有効。
記録9コードSHA、profile/configと記録checkpoint SHAが一致。重み本体は未提出なので実ファイル再hashはしていない。
physical_metric_verified／floor_contact_verified／controlling_distance／usable_for_ffb／published_to_ros等はfalseを維持。

主child_exitcode=0、worker_error/shutdown_error=null、強制killなし、主／I/O・比較・evidenceの終了完了を確認。
主sent45,531・returned45,530で終了時に未返却1件。比較offered45,530・processed45,527はslot上書き2件＋終了未処理1件と整合。
比較tap_busy_drops=0、主tap_lock_drops=3は別項目。
主の開始直後の約976ms ageと保留1件は全体の記録で、今回録画区間には含まない。

evidenceは10組すべてPNG/BGR/sidecar/index/主元行SHAが一致し、writerも正常終了。
録画内はframe44302・44793の2組。他は録画前の試走等なので今回走行品質へ混ぜない。
全evidence保存量約8.60MB、queue/quota拒否0、1秒間隔による間引き14件。
保存対象はcolour_contour_reaches_roi_edgeだけで、自己遮蔽267件や数値の一時変化を自動保存したものではない。

全参照有効区間には主2m超や比較救済1件（frame43801、録画開始前）もあるが、
それらを録画中の精度や救済成功の証拠にはしない。旧試走は原ログに残し、別途分析できる。

## 保存先・再現

原本は `recordings/2026-11-13/guarded_motion_full_intake_r02/`：
`logs/primary`、`logs/comparison`、`logs/evidence`、`video/screen`。
画面原解像度PNGは同配下のscreen_samples_r01とr02へ保存。各frames.csv/provenance.jsonに元動画PTS・frame index・SHAを記録。
カメラ画像・画面画像の注釈・crop・resize・色補正・合成は一切行っていない。

集計はresults_r01/audit.json（全体整合）とscreen_audit.json（録画対応区間）を分け、
paired_timing.csvは全実行、screen_window.csvは録画内だけ。screen_readings.csvは25点の目視転記で、
screen_anchors.csvに元PNG SHA・PTS・主数値・比較理由を対応させた。
state=passはファイルとログ整合性の成功で、物理精度や制御への採用判定ではない。

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/guarded_motion_live_audit_r02/review.py extract \
  --archive /home/robo25/Downloads/guarded_motion_r02_full.tar.xz \
  --video-archive '/home/robo25/Downloads/Screencast from 2026年11月13日 18時46分18秒.tar.xz' \
  --intake-dir recordings/2026-11-13/guarded_motion_full_intake_r02 \
  --output-dir Experimental_results/2026-11-13/guarded_motion_live_audit_r02/results_r01
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/guarded_motion_live_audit_r02/review.py audit \
  --intake-dir recordings/2026-11-13/guarded_motion_full_intake_r02 \
  --output-dir Experimental_results/2026-11-13/guarded_motion_live_audit_r02/results_r01
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/guarded_motion_live_audit_r02/screen_audit.py \
  --intake-dir recordings/2026-11-13/guarded_motion_full_intake_r02 \
  --results-dir Experimental_results/2026-11-13/guarded_motion_live_audit_r02/results_r01
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/guarded_motion_live_audit_r02/plot_results.py
```

再生成は原本を上書きせず新規出力へ。画面抽出はscreen_frames.pyと各provenance.jsonのtimes/commandを参照。
通常pytestの既存環境プラグイン不整合を避け、自動プラグイン読込みのみ無効化した条件で関連テストを実行。
新しいarchive/区間切出しの7テスト、既存pin/evidence関連を含めて次の50件が成功した。

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q \
  tests/test_guarded_motion_r02_audit.py tests/test_guarded_current_pin_intake.py tests/test_driver_withheld_evidence.py
```

実提出の全行整合監査・25点照合・図生成も成功。画面照合スクリプトの初回は来歴の相対パス処理で失敗したが、
入力ディレクトリの絶対パス化後に再実行して成功した（初回は成果物を書き込む前の失敗）。
図生成で既存matplotlibの3D機能警告が出るが、使用する2D図の生成は成功。ライブラリや環境は変更していない。
実GPU／カメラ／ROS／機体をこちらから起動したわけではない。日報・commit/pushは今回未依頼。
