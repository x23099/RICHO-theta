# Phase 5 v11 reliability dry-run 診断

## 結論

総合判定は **FAIL（実機hardware試験へはまだ進まない）** とする。

ただし、録画そのものと一人試験用の疑似ODOMシナリオは正常に取得できている。ユーザー申告の「録画前半に何もない時間が長い」点は欠損ではなく、録画開始から疑似ODOMシナリオ開始までの待機区間である。

今回確認できた主な結果は次のとおり。

| 評価項目 | 判定 | 根拠 |
|---|---|---|
| カメラ録画の完全性 | PASS | 2,412 frameについてraw/BEV/detectionがすべて揃い、時刻・処理時間列も正常 |
| 疑似ODOMシナリオ送信 | PASS | 750件、送信失敗0件、停止150→0.25 m/s 450→停止150 |
| カメラ側のUNKNOWN再arm | PASS | 有効測定が2.067秒連続した後だけ2回目のUNKNOWNを許可。短い青色復帰では再通知なし |
| intent生成 | PASS | active intent 27件、送信失敗0件 |
| relayによるactive command転送 | FAIL | active intent 27件のうちcommandは12件。15件をrelayが見送り |
| adapterのactive status | FAIL | active command 12件に対しactive status 11件。sequence 3251を確認できず |
| UNKNOWNのPC間到達 | FAIL | 2回のUNKNOWN計7件はいずれもrelayで見送られ、adapterまで未到達 |
| dry-runの安全な終端 | PASS | 最終statusはinactive、fault=false |
| rosbag内の疑似ODOM記録 | FAIL | 両bagとも旧い速度0 publisherの終了後に新シナリオpublisherを捕捉できず、0.25 m/s区間なし |

## 入力

| ファイル | SHA-256 |
|---|---|
| `rokuga_phase5_v11_reliability_dryrun_r01_20260929_153520_912.tar.xz` | `240ac6566fb4fdd1172ce7ab8c2f020129cc2d50c869b1f48b04e970004ec668` |
| `phase5_v11_mock_odom_r01.csv` | `52c9c7e691ca68f9895b6d944d01a0a02100cdfedca0f5b403ddd8f8c791a71d` |
| `H_rosbug_phase5_v11_reliability_hsr_r01.tar.xz` | `c61d5ab47f2b3fe59b523bd8ebae372476139a8455850a0cec8b313bf3df6cbc` |
| `K_rosbug_phase5_v11_reliability_kobuki_r01.tar.xz` | `b8cdc958ec694d78bacd5a72bd1a1ef6eaeee40550411ba07c3794c6ff695eb9` |

設定は `src/bird_eye_config_ttc_v11_ffb_reliability_20260925.json`。relay、受信challenge、UNKNOWN再arm、relay診断が有効なv11構成である。

## 録画前半と疑似ODOMの照合

録画区間は **15:35:20.912～15:36:41.934 JST（約81.0秒）**。カメラCSV上で0.25 m/sの移動が観測されたのは、録画開始から **32.654～47.622秒** である。

外部のシナリオCSVは次の送信を記録している。

| phase | 件数 | 時刻（JST） | 指令速度 |
|---|---:|---|---:|
| initial_stop | 150 | 15:35:48.527～15:35:53.493 | 0.00 m/s |
| forward_0p25 | 450 | 15:35:53.527～15:36:08.494 | 0.25 m/s |
| final_stop | 150 | 15:36:08.527～15:36:13.493 | 0.00 m/s |

カメラ側の移動開始15:35:53.566、終了15:36:08.534は外部CSVと約40 ms以内で一致する。したがって、前半約27.6秒はシナリオ開始前の待機、続く約5秒はinitial_stopであり、映像やODOMが欠けたための空白ではない。

シナリオ送信間隔は中央値33.334 ms、p95 33.438 ms、最大33.529 ms。予定時刻からの送信誤差は中央値0.097 ms、p95 0.202 ms、最大0.347 msで、30 Hz送信として安定している。

## カメラ・認識結果

| 指標 | 結果 |
|---|---:|
| frame数 | 2,412 |
| 実効FPS | 29.765 fps |
| 青箱検出率 | 92.50% |
| 測定採用率 | 98.39% |
| 追跡率 | 92.16% |
| ODOM利用率 | 62.94% |
| 有効処理時間 p95 | 30.37 ms |
| 最小有限TTC | 4.413 s |
| WARNING/CRITICAL frame | 336 / 0 |

通常の一括解析レポートは `raw_ground_distance observation gate failed` によりFAILとなったが、これは今回の録画に遮蔽ラベルを与えておらず、遮蔽失効・再捕捉が0/0になるためである。録画完全性や今回のFFB信頼性試験の失敗理由とは別である。

## UNKNOWN再armの確認

active intentは計27件で、次の8群に分かれる。

| 種別 | sequence | 録画経過時間 | 結果 |
|---|---|---:|---|
| UNKNOWN 1 | 3053～3056 | 32.654～32.754 s | intent生成、relayで全件見送り |
| WARNING | 3075～3078 | 33.388～33.487 s | relayで全件見送り |
| WARNING | 3080～3083 | 約33.55～33.65 s | relayで全件見送り |
| WARNING | 3086～3088 | 約33.75～33.82 s | command/status到達 |
| UNKNOWN 2 | 3159～3161 | 36.188～36.255 s | intent生成、relayで全件見送り |
| WARNING | 3251～3253 | 約39.26～39.32 s | command到達、3251のstatus欠落 |
| WARNING | 3256～3258 | 約39.42～39.49 s | command/status到達 |
| WARNING | 3261～3263 | 約39.59～39.66 s | command/status到達 |

1回目のUNKNOWN後、`collision_measurement_valid=true` が33.321～35.388秒の約2.067秒間連続しており、0.5秒の再arm条件を満たした。その後に2回目のUNKNOWNが生成された。2回目の後には青色検出が短時間復帰しているが、有効測定は連続しなかったため再armせず、UNKNOWNの単発通知も繰り返されていない。

以上から、v11で追加した「有効測定の連続時間でUNKNOWNを再armする」カメラ側ロジックは期待どおりに動作した。

## relay・adapter診断

録画時間内のKobuki側bagでは次を確認した。

| 項目 | 件数 |
|---|---:|
| intent | 2,411 |
| relay diagnostics | 2,411 |
| command | 1,798 |
| status | 1,764 |
| challenge | 4,051 |
| active intent | 27 |
| active command | 12 |
| active status | 11 |

relay診断の結果は、転送1,798件、見送り613件。見送り理由は以下のとおり。

| relay理由 | 件数 |
|---|---:|
| `receiver_challenge_stream_not_stable` | 567 |
| `receiver_challenge_already_used` | 33 |
| `stale_receiver_challenge` | 13 |

特にactive intent 27件中15件がcommandになっていない。内訳はUNKNOWN 7件と初期WARNING 8件である。challengeの受信間隔には60 ms超が25回あり、最大129.436 msだった。現在の実装では `challenge_max_age_sec=0.06` を超える単発の間隔でもchallenge流の安定時間を0へ戻し、その後1秒間を不安定としてintentを見送る。このため、短い通信・スケジューリング揺らぎが長い転送停止へ増幅されている。

adapterへ到達したactive status 11件はすべて `output_mode=dry_run`、`action=apply`、`applied_magnitude=0.05`、`fault=false` だった。sequence 3251はcommandまでは両bagで確認できるが、対応するstatusがない。

録画時間内には `invalid_request:unknown_receiver_token` が1件（sequence 3753）発生した。inactive/no_alertのcommandなので物理出力は起こらずfail-safeに停止しているが、fault 0件という信頼性条件は満たさない。HSR側でchallengeからcommand受信まで約109.6 msかかっており、adapter側のtoken有効期間を超えたことが原因である。

## rosbagの疑似ODOM欠落

両bagの `/phase5/mock_odom` は速度0だけを記録し、次の時刻で終了している。

| bag | `/phase5/mock_odom` の最終時刻 | 0.25 m/s件数 |
|---|---|---:|
| Kobuki PC | 15:35:46.180 JST | 0 |
| ハンコンPC | 15:35:46.209 JST | 0 |

外部CSVのシナリオ開始は15:35:48.527、0.25 m/s開始は15:35:53.527であり、bagの購読はその前に終了している。カメラCSVには速度変化が入り、外部CSVにも送信成功が残るため、シナリオ自体は実行できている。問題は旧い速度0 publisherを停止後、新しいシナリオpublisherをrosbagが記録できなかった点である。

## 次の作業

追加録画の前に次を実施する。

1. relayの「個々のchallenge鮮度」と「challenge流の起動安定」を別の条件に分離する。
2. 単発の60～130 ms程度の受信間隔では1秒の再安定化を要求せず、連続欠落または十分長い停止のときだけ安定状態を解除する。
3. HSR側でtokenが100 msを超えて古くなる経路と、sequence 3251のstatus欠落を既存bagで再診断する。
4. 一人試験用ODOM送信器を、速度0でpublisherを維持したまま手動開始を待てる方式へ変更する。publisherを作り直さず、rosbagが同じpublisherを追跡し続けられるようにする。
5. 今回のbagを使ったオフライン回帰試験を追加し、active intent 27件が意図した条件で転送されること、UNKNOWNがadapterまで到達すること、faultが0件であることを確認する。
6. 上記をdry-runで再試験してからhardwareへ進む。

## その後の対応

上記1、2、4、5に対するv12実装とオフライン回帰を実施した。command単位のchallenge鮮度60 msは維持したまま、stream再安定化を要求する受信断を200 msへ分離した。9月29日bagの再生ではactive許可が12/27件から26/27件へ改善し、`receiver_challenge_stream_not_stable`は567件から0件になった。

一人試験用ODOM送信器には、同じpublisherで速度0を送りながらEnterを待つ機能を追加した。次回は[v12 dry-run手順](phase5_v12_reliability_dryrun_procedure.md)に従い、2PCで再試験する。

## 成果物

- 標準解析: `phase5_v11_reliability_dryrun_r01_analysis/`
- Kobuki bag要約: `phase5_v11_reliability_kobuki_r01_bag_summary.json`
- Kobukiイベント: `phase5_v11_reliability_kobuki_r01_events.csv`
- HSR bag要約: `phase5_v11_reliability_hsr_r01_bag_summary.json`
- HSRイベント: `phase5_v11_reliability_hsr_r01_events.csv`
- 疑似ODOM原本: `phase5_v11_mock_odom_r01.csv`
- 無加工確認画像: `report_assets/`
