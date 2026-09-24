# Phase 5 challenge受信診断 r01（2026-09-24）

## 判定

**challengeのPC間配信はPASS、カメラアプリ内での利用はFAIL、衝突警告試験は未成立。** ハンコン接続PCが発行したchallengeは、カメラ録画と重なる区間でKobuki PCのbagにも50 Hzで連続到着していた。同区間のsession/token 1,542件は両PCで全件一致し、PC間欠落は0件だった。一方、`bird_eye.py`は912フレーム中489フレームで`no_recent_receiver_challenge`として指令を見送った。したがって、主な切り分け対象はネットワークではなく、アプリ固有のchallenge subscription、ゼロ待ち`spin_once`、callback実行タイミングである。

青箱は生映像に写っていたが検出は0/912だった。今回の映像は画面全体が強く青へ偏り、現行HSVマスクが代表フレームの51.8%を青として抽出した。左右fisheyeが約24万pixelの巨大輪郭となり、箱が背景マスクへ結合したため、青箱の独立候補が生成されなかった。9月8日の代表フレームへ同じマスクを適用した割合は4.69%であり、今回だけ大きく異なる。よって0.25 m/sの模擬ODOMを送ってもWARNING・active FFB指令は0件で、FFB警告経路の合否には使えない。その後、同じPCで`bird_eye.py`を単体起動すると青箱検知を確認できたため、恒常的なしきい値不良ではなく、当該録画時の一時的なカメラ状態または起動状態として扱う。HSVしきい値は変更しない。

## 入力

| 入力 | SHA-256 |
|---|---|
| `phase5_challenge_reception_diag_r01_20260924_161045_968.tar.xz` | `63b85bc360172814bf64269f8174012eb3dc5c0551e1d9ba76f8641734117bc5` |
| `phase5_challenge_kobuki_r01.tar.xz` | `4ee0febd37c3a6a1f602e0f034abbdfed5399ee8e0e5531e3eaf6440ee47aa48` |
| `phase5_challenge_hsr_r01.tar.xz` | `407b00bcf583c2e0530c32898f33d4ce892ae2de5b49da547807daee1573f477` |

## カメラ録画

| 指標 | 結果 |
|---|---:|
| フレーム・動画時間 | 912・30.4秒（CSV経過時間30.854秒） |
| raw/BEV/detection/CSV | 各912、完全性PASS |
| 実効FPS / 有効処理p95 | 29.547 / 29.08 ms |
| 青箱検出・追跡 | 0/912・0/912 |
| ODOM available | 521/912（57.13%） |
| カメラCSVで0.25 m/sを観測 | 28フレーム、15.413～16.314秒 |
| FFB publish成功 / 見送り | 423 / 489 |
| WARNING / active指令 | 0 / 0 |

録画品質の自動判定は、実効FPSが30 fps±1%の下限29.7を下回ったためFAIL。フレーム完全性はPASSであり、検出0とは別の判定である。

FFB publishはフレーム1～175で全件見送り、176～453で成功、454～465で見送り、466～610で成功、611～912で全件見送りだった。challengeがKobuki bagへ常時到着しているのに、アプリ利用可否が長い区間単位で切り替わっている。

## 両PCのbag照合

| 項目 | Kobuki PC bag | ハンコン接続PC bag |
|---|---:|---:|
| 全challenge | 28,051 | 50,308 |
| 全command / status | 425 / 421 | 425 / 421 |
| 模擬ODOM 0.25 m/s | 90件、約2.97秒 | 85件、約2.80秒 |
| status mode | 全件`dry_run` | 全件`dry_run` |
| active command/status | 0 / 0 | 0 / 0 |
| fault | 2 | 2 |
| 最終status | `shutdown`, inactive, faultなし | 同左 |

bag全体の長さは異なるため、全challenge件数は直接比較しない。カメラ録画区間をFFB sequenceから位置合わせすると、Kobuki側は各5秒区間で250件ずつchallengeを記録した。カメラ録画に対応するtoken `51859`～`53400`の1,542件はハンコン側にも全件存在し、両PC間のtoken欠落は0件だった。

カメラCSVでpublish成功となった423件は、両bagのcommandにも同じsequenceで423件存在し、すべてCLEAR/`no_alert`だった。Kobuki側bagでのchallenge記録からcommand記録までの時間は中央値10.67 ms、最大105.51 ms。2件の非active指令だけが`expired_receiver_token`と`unknown_receiver_token`で拒否され、出力は常にinactiveだった。受信側100 ms期限ぎりぎりのtokenを送信側が使用する境界問題は前回同様に残る。

模擬ODOMはKobuki bagで90件記録されたのに、カメラCSVで0.25 m/sとして残ったのは28フレームだけだった。challengeだけでなくODOMでも、PCへのtopic到着とアプリ内の観測に差がある。アプリのROS callback処理経路を優先して調べる根拠となる。

## 青箱未検出の診断

代表生フレームには正面の青箱が明瞭に写っている。しかしBGR平均は今回`[85.9, 58.2, 45.2]`で青成分が強く、9月8日の代表フレーム`[70.2, 73.0, 66.5]`とは異なる。現行HSV条件`H=90..140, S>=70, V>=30`によるmaskは今回477,379/921,600 pixel（51.8%）、9月8日は43,205/921,600 pixel（4.69%）。今回の最大輪郭は左右約246,984・240,974 pixelで、箱ではなくfisheye画面の広域が一体化したものだった。

単にHSV範囲を広げたり面積しきい値を下げたりする問題ではない。録画終了後の`bird_eye.py`単体起動では青箱検知へ復帰している。次回は録画前pilotで箱の輪郭表示を確認し、その状態のまま本試験へ移る。再び検出0または画面全体の青偏りが出た場合に限り、カメラ再接続・電源再投入と生映像確認を行う。

## 実装対応

1. challengeとODOMのcallbackを、GUIのフレーム処理から独立した専用ROS executorで処理するよう変更した。
2. challenge受信累計、最終受信age、session/token、およびODOM受信累計を録画CSVへ追加した。
3. sender側のchallenge利用期限を60 msとし、受信側100 msより40 msの余裕を設けた。受信側期限は変更していない。
4. executor異常時とchallenge期限切れ時は指令を送らないfail-closedを維持した。
5. 単体・回帰試験174件、および実ROS 2ローカル結合試験をPASSした。詳細は[callback安定化実装記録](challenge_callback_stabilization_implementation.md)を参照。

## 次の作業

1. 単体起動で青箱検知へ復帰したためHSVしきい値は維持する。録画前の10秒pilotで青箱検出を確認し、検出0なら本試験を開始しない。
2. 修正後も`dry_run`、単一adapter、専用`/phase5/mock_odom`で再試験する。hardwareと実走行には進まない。
3. 新しいCSV列でchallenge/ODOM受信累計とageを確認し、長時間のcallback停止が解消したことを判定する。

根拠ファイルは同日フォルダの標準解析、両bagのsummary/events、および[成果報告用資料](report_assets/README.md)に保存した。
