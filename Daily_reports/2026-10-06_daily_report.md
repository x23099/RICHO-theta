# 2026年10月6日 日報

## 本日の到達点

実Kobukiの低速直進で、実カメラ・実ODOMからTTC判定、intent、独立relay、challenge認証、command、G923までの経路を検証した。dry-run 1回、hardware 3回とも、録画評価窓内のactive配送欠落0、adapter fault 0、終了時の出力停止を確認した。hardware r01・r02ではWARNINGの3連振動を体感した。

ただしr03は同じWARNINGの3連成功ではない。箱が見えているのに認識・距離推定が乱れ、UNKNOWN単発とCRITICAL起点の途中で中断された通知が発生した。**通信・出力経路の成立と、距離・TTC精度の成立は分けて判断する。WARNING 3連の再現性を3/3成功とはしない。**

後半は追加録画なしで原因診断、オフライン候補実装、過去録画との固定条件比較、距離校正の分離診断、遮蔽ラベルの全区間レビューを進めた。候補で保存動画上の検出・距離安定性は改善したが、絶対距離の偏りと長い完全遮蔽の評価が残るため、本番採用は保留した。

## 1. 使用環境・評価範囲

| 項目 | 内容 |
|---|---|
| Kobuki PC | `matunuc-NUC13ANHi5`、`~/theta_ws`、カメラ・実ODOM・カメラアプリ・relay |
| ハンコン接続PC | `hsr-Alienware-m16-R2`、`~/yopi_ws`、G923・challenge・adapter |
| 解析PC | `robo25`、`~/theta_ws/RICHO-theta` |
| ROS domain | 両実験PCとも88、`ROS_LOCALHOST_ONLY=0` |
| 本番設定 | `src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json` |
| 実走行 | 正面直進、実`/odom`、実速度上限0.25 m/s、物理停止線を優先 |
| hardware | challenge安全ゲート有効、適用上限0.05、watchdog 0.10秒 |
| 原本 | `Downloads/`または`Downloads/recoding/`のカメラ・両PC bagアーカイブ。動画・bag・圧縮原本はGit対象外 |
| 解析結果 | `Experimental_results/2026-10-06/`、各CSV・JSON・manifestに入力とhashを保存 |

r03の評価は15:37:55.541～15:38:11.454643 JSTのカメラ録画窓だけを対象とした。利用者から指定された15:37以前のテストを試行件数へ混ぜていない。録画終了後のshutdownは安全停止確認として別に参照した。

## 2. 実Kobuki走行と物理FFB

| 指標 | dry-run r01 | hardware r01 | hardware r02 | hardware r03 |
|---|---:|---:|---:|---:|
| raw/BEV/CSVの一致frame数 | 572 | 650 | 479 | 478 |
| 実効FPS | 29.891 | 29.920 | 29.631 | 29.999 |
| ライブ青箱検出 | 572/572 | 650/650 | 479/479 | 301/478 |
| 有効測定 | 306 | 308 | 270 | 85 |
| 最大実速度 m/s | 0.1834 | 0.2132 | 0.2132 | 0.1450 |
| ODOM正味移動 m | 0.5342 | 0.4123 | 0.6382 | 0.4570 |
| active intent→command→status | 8→8→8 | 8→8→8 | 11→11→11 | 7→7→7 |
| 録画評価窓fault | 0 | 0 | 0 | 0 |
| 最小有限TTC 秒 | 4.217 | 4.375 | 3.518 | 1.799 |
| 通知内容 | WARNING 3窓 | WARNING 3窓 | WARNING 3窓 | UNKNOWN 1窓＋CRITICAL起点2窓 |
| 体感 | 物理出力なし | 明確な3回、後の不要振動なし | 3回を体感 | 振動あり、3連完了とは扱わない |

active件数は送信sample数であり、独立した振動回数ではない。すべて適用値0.05以下で、hardware最後のactiveから停止statusまでr01 30.5 ms、r02 36.5 ms、r03 32.6 msだった。これらはbag上の記録時刻差で、カメラからモーターの物理遅延測定ではない。

r01の`/cmd_vel`最大値は0.2592 m/sだったが実速度は0.2132 m/s。実速度と指令値を混同せず、次の実走行では指令側も可能な範囲で上限内へ抑える。r02は実施者が物理停止線超過なしを確認した。一方、カメラ推定値とODOM移動量と実測停止位置の整合は未確定。r03の実測初期・停止距離、停止線確認結果は未提供でありPASSとはしない。

標準解析器のFAILは実走行判定と分けて記録した。r01等では実際の接近速度が静止用安定性条件に掛かった。r02はFPSも30±1%の下限29.7を少し下回った。r03はライブ距離・視覚速度にも実運動と不整合があり、単に静止用条件の問題として除外していない。bag全体の起動前安全拒否と、録画窓内fault 0も区別した。

根拠: [dry-run診断](../Experimental_results/2026-10-06/phase5_v12_live_kobuki_dryrun_r01_diagnosis.md)、[hardware r01](../Experimental_results/2026-10-06/phase5_v12_live_kobuki_hardware_r01_diagnosis.md)、[r02](../Experimental_results/2026-10-06/phase5_v12_live_kobuki_hardware_r02_diagnosis.md)、[r03](../Experimental_results/2026-10-06/phase5_v12_live_kobuki_hardware_r03_diagnosis.md)。

## 3. r03の原因切り分け

床を反射しない場所へ変更したという利用者申告を記録したが、反射が唯一の原因とは断定しなかった。

- ライブframe 269→270で、約43 msにraw zが約12 cm変化した。実速度から想定する移動は約6 mmだった。
- 再初期化後に追跡接近速度が約0.70 m/sとなり、conservative TTCが大きい視覚接近速度を選ぶためCRITICALへつながった。実速度は約0.145 m/sだった。
- 保存動画では暗い青面がV下限30付近にあり、r03の233/478未検出は縦横比1.5による輪郭除外だった。ただしAVI再検出とライブ検出は178/478で異なるため、動画の除外理由をライブの正確な原因へ読み替えない。
- 動画での接地点zの広がり中央値はr01約4.7 mm、r03約55.4 mm。停止後の隣接距離変化とODOMとの不整合最大値はr03約48.6 cmだった。
- 接地点の広がりが4.47 mmと小さいframeでも、次frameへ距離が48.6 cm飛ぶ例があった。「広がりが小さい＝正しい接地点」とは判断できない。

局所的に初期速度分散を小さくすると過大速度は減ったが、本当の高速接近を遅らせる懸念があり採用しなかった。ODOMのみへ切り替える比較ではr03のCRITICALとともにr01のWARNINGも消え、動く物体の相対速度を扱う最終目標への一般解にはならない。

根拠: [距離・TTC診断](../Experimental_results/2026-10-06/phase5_distance_instability_diagnosis/README.md)、[輪郭・接地点の品質診断](../Experimental_results/2026-10-06/ground_contact_quality_diagnosis/README.md)。

## 4. 実装・オフライン候補評価

### 視覚速度の根拠確認

距離傾向と視覚速度の整合を確認する再生専用部品・CLIを実装した。不確かな高リスクをCLEARで隠さずUNKNOWNとする。r01・r02のWARNINGは維持し、r03のCRITICAL 1、WARNING 7、HOLD 3 frameを0にした。

| 検証 | 結果・制約 |
|---|---|
| 過去28 session・18,039 frame | 候補なし→ありの状態・仮想active差0。旧ライブそのものとの一致を意味しない |
| 人工1 m/s接近 | 短時間確認でCRITICAL追加遅れ約0.067秒。実物・カメラ全経路の安全保証ではない |
| 保存動画の全経路再計算、7 session・5,030 frame | ライブ測定からの後段再構築は状態差0。動画はr03のCRITICALが候補なしでも0で、候補効果は実証できない |

保存MJPG画素とライブ入力は同一とは限らない。r02も動画WARNINGが約0.933秒早まり、検出率100%だけではTTC再現性を示せなかった。

根拠: [速度候補](../Experimental_results/2026-10-06/velocity_confidence_candidate/README.md)、[動画処理再計算](../Experimental_results/2026-10-06/raw_velocity_confidence_candidate/README.md)。

### 箱本体の領域分離と接地点

`offline_box_contact_candidates.py`、`compare_offline_box_contacts.py`を追加し、6方式、7 session・5,030 frame、30,180比較行を保存した。V下限だけを下げる方式、seed＋opening、S下限130を用いる方式、既存近接点／底部中央値を比較した。

| r03動画指標 | baseline | S130 nearest | S130 bottom |
|---|---:|---:|---:|
| 検出 | 245/478 | 478/478 | 478/478 |
| 停止後検出・採用 | 検出93/179 | 179/179 | 179/179 |
| 停止後の最大隣接不整合 | 48.6 cm | 2.6 cm | 3.6 cm |
| 箱なし対照の検出 | 0/853 | 0/853 | 0/853 |

これは固定箱・直進を前提とする距離変化の整合であり絶対距離誤差ではない。r03停止後推定約0.91 mも、実測停止距離がないため正しいとは認定していない。探索に使ったr03を独立holdoutとは扱わない。

その後コード・閾値を固定し、別の左右・距離・接近録画12 session・8,203 frameを3方式で比較した。固定v6動的TTC条件ではbaseline 5/6、S130候補各6/6 PASSだったが、本番hardwareや安全性の合格ではない。左右4配置のX誤差は底部方式で減る一方、左0.9 mのZ誤差は増えた。

根拠: [候補比較](../Experimental_results/2026-10-06/box_contact_candidates/README.md)、[固定回帰](../Experimental_results/2026-10-06/box_contact_validation/README.md)。

## 5. 接地点と距離校正の分離

`diagnose_box_contact_calibration.py`を追加した。39 session/variant・21,297検出で保存座標と現行変換が一致し、範囲ゲート不一致0だった。ground-contact経路に旧BEV用Z倍率を二重適用した問題は確認されなかった。

利用者からr02の1.30 mは**初期距離で、カメラ直下・Kobuki中心を起点**と確認した。停止距離として使用していない。箱側の厳密な基準点とx/z成分は未確認。

| 初期90 frame、ゲート前の比較 | baseline | S130 nearest | S130 bottom |
|---|---:|---:|---:|
| 距離中央値 | 1.497 m | 1.542 m | 1.552 m |
| 実測1.30 mとのMAE | 19.6 cm | 24.3 cm | 25.2 cm |
| 検出／採用 | 90／0 | 90／0 | 90／0 |

候補は安定性を改善しても初期距離の偏りを増やした。接地点を変えると同じX校正でも左右間隔が変わるため、縮みを係数だけの問題と決めつけない。固定pixelではy 5 pxが約12～15 cm、pitch 1度が約8 cmのZ差となる感度を確認したが、実際の姿勢誤りや採用すべき補正量を示すものではない。

一つの距離点への倍率・オフセット合わせ込みはしなかった。根拠: [校正分離診断](../Experimental_results/2026-10-06/box_contact_calibration_diagnosis/README.md)。

## 6. 完全遮蔽のラベル再点検

検出結果と独立に元解像度画像を目視し、ラベルを固定してから3方式の結果へ結合した。旧ラベル・過去集計は上書きしていない。

| 対象 | 目視範囲 | 確定した完全遮蔽 | 結果・制約 |
|---|---:|---:|---|
| 08/26旧完全遮蔽3区間 | 全182 frame | 0 | 182/182は部分遮蔽。候補の採用0でも完全遮蔽PASSとはしない |
| 09/29 v11選定2区間 | 全107 frame | 4、時刻差0.099875秒 | 全3方式で検出0・採用0。trackは4/4予測で、新規検出ではない |
| 09/29 v12 dry＋hardware | 72点、うち連続42 frame | dry 2、時刻差0.035808秒 | ODOMは既に0。全3方式で検出0・採用0・trackなし |

v11全動画2,412 frame×3＝7,236行、v12全動画2,346 frame×3＝7,038行を再計算したが、目視範囲は上表のみ。v12の疎な点の間は未確認で、ラベルを補間していない。録画全体に長い完全遮蔽がないと証明したわけでもない。

v12の完全可視復帰frame 773では全方式が採用済みだった。部分遮蔽での最初の採用はbaseline 771、候補770。この1 frame差は記述的な結果で、完全遮蔽の物理応答遅延0や候補の一般的優位を示さない。

**前進が続く間の2～3秒の完全遮蔽、追跡失効、UNKNOWN、可視復帰の画像正解付き評価は未完了。** 過去のhardware UNKNOWN合格は状態→物理出力の経路確認として維持し、完全遮蔽精度の証明へ読み替えない。

根拠: [旧ラベル全レビュー](../Experimental_results/2026-10-06/occlusion_label_review/README.md)、[v11レビュー](../Experimental_results/2026-10-06/unknown_occlusion_validation/README.md)、[v12探索・復帰](../Experimental_results/2026-10-06/v12_occlusion_screening/README.md)。

## 7. 検証と保存資料

- 本日後半のソースを含む全単体テストは**316件PASS**。その後ソースを変更していない目視・資料作成では同じ成功結果を再利用した。
- 旧遮蔽182枚、v11 107枚、v12 72枚のレビューPNGは、それぞれ元動画の順次decodeと全画素一致を確認した。
- 入出力hash、固定候補条件、frame連番・時刻・方式集合、レビュー範囲、対象なしをNOT_EVALUATEDとする集計を検査した。
- グラフは根拠CSVと再生成スクリプトを保存。カメラPNGは全画角1280×720のまま、注釈・合成・切り抜き・リサイズ・色／明るさ補正なし。
- PyTorch／YOLOは解析環境に未導入。本日は青箱処理の検証で、最終目標のYOLO→FFB統合が完了したとは扱わない。
- 日報・翌日手順の追加時はshell構文・既存CLIの非実行dry-run・相対リンク・Git差分を確認する。新しい実機試験は実行しない。

成果報告の入口は[画像・グラフ一覧](../Experimental_results/2026-10-06/report_assets/README.md)。本日の代表として次の4点を選ぶ。他の無加工画像・図も出典付きで保存済み。

1. [実走行WARNING時の生画像](../Experimental_results/2026-10-06/report_assets/phase5_v12_live_hardware_warning_raw_frame_0372.png)
2. [箱が見えるのに認識不確かなr03生画像](../Experimental_results/2026-10-06/report_assets/phase5_v12_live_hardware_r03_raw_frame_0206.png)
3. [r03の接地点候補比較グラフ](../Experimental_results/2026-10-06/box_contact_candidates/r03_contact_candidate_timeline.png)
4. [完全遮蔽・復帰の目視と固定候補グラフ](../Experimental_results/2026-10-06/v12_occlusion_screening/continuous_window_recovery.png)

## 8. 次回作業と採用判断

明日の日付は**2026-10-07**。具体的なPC別ターミナルコマンド、録画秒数、板を動かすタイミング、保存・解析は[明日の手順書](../Experimental_results/2026-10-07/phase5_full_occlusion_and_distance_reference_procedure.md)へまとめた。

1. 両PCを最新へ揃え、domain 88、adapter 1台・dry_run、本番v12設定を確認する。
2. Kobukiを停止したまま、同一publisherの専用mock ODOMで「可視→2～3秒の完全遮蔽→有効測定の連続復帰」を録画する。まずr01を確認し、同じ条件でr02・r03を収集する。
3. 余力があれば、箱なし10秒、中央0.90／1.10／1.30 m各20秒の静止参照を収集する。起点はカメラ直下、箱側は手前面の床との境界へ統一して記録する。
4. 検出結果を見る前に画像の遮蔽ラベルを確定し、固定した3方式で比較する。ライブCSV・bag経路と動画候補比較を別々に採点する。
5. 本番候補採用、係数変更、hardware強度変更、新たな走行は今回の手順に含めない。

学校へ行けない場合は追加収録をせず、既存未レビュー区間の確認・解析を続けられる。ただし不足条件を合格扱いにはしない。

## Gitの整理対象

本日の既存コミットは`3819aa0`（実走行解析・再現手順）、`2669def`（後続の実験・診断・オフライン実装）。本日後半の箱接地点候補・固定回帰・校正診断・遮蔽レビュー、対応テスト・集計・無加工PNG・グラフ、本日報、翌日手順は`e3b834b`（作業終了）へ反映済み。日付変更後の9/29 challenge図示と関連資料への追補は別の追加コミットとして整理する。

対象リポジトリは`RICHO-theta`の`main`、送信先は`origin/main`。圧縮原本、動画、bag、仮想環境、一時展開フォルダは追加しない。本番JSON、カメラのライブ経路、FFB側リポジトリはこの整理で変更しない。コミット・PUSHの結果は完了時に別途報告する。
