# Phase 5 v11 reliability実装記録

## 実装内容

1. UNKNOWN通知後は、青箱の`measurement_valid=true`が0.5秒連続するまで再armしない。途中で無効測定が1回でも入ると連続時間をリセットする。
2. relayはchallengeを既定1.0秒連続受信するまでintentをfail-closedで見送る。session変更またはchallenge受信間隔が上限を超えた場合も安定時間をリセットする。
3. relayは全intentについて`/collision/ffb_relay_diagnostics`へJSONをpublishする。転送結果、見送り理由、intent/challenge age、安定継続時間、session/tokenを含む。
4. `publish_mock_odom_scenario.py`を追加した。実機`/odom`を拒否し、`/phase5/`配下に停止→前進→停止を自動送信する。各publishの予定時刻と実時刻をCSVへ逐次flushする。
5. 実験済みv10設定は保存し、新機能を明示した`bird_eye_config_ttc_v11_ffb_reliability_20260925.json`を追加した。
6. Phase 5 bag解析スクリプトにrelay診断JSONの復号と理由集計を追加した。

## 安全性

- 新ODOMコマンドは`/odom`へpublishできず、既定topicは`/phase5/mock_odom`である。
- relayのchallenge安定前・受信断後はcommandを転送しない。
- 診断publish失敗はcommand再送やtoken再利用を行わない。
- 今回の検証は単体・dry-runに限定し、ハンコンへの物理出力は行っていない。

## 検証

- UNKNOWN再arm境界、無効測定による連続時間リセットを自動テスト化した。
- relay起動安定前の遮断、連続受信後の許可、challenge gap後の再遮断、診断JSONを自動テスト化した。
- 一人用ODOMのphase順序、速度、件数、危険なtopic/値の拒否を自動テスト化した。
- v11 configのpreflightとrelay起動引数を自動テスト化した。
- v10実録画の`detections.csv`をv11 cadenceへ再入力した。v10ではUNKNOWN activeが9フレーム・4区間に分かれていたが、v11では最初の1フレーム・1区間だけとなった。短い測定復帰による再発火を過去録画上で抑止できた。
- ROS/FFB workspaceをsourceした状態で全206件の単体・回帰テストがPASSした。
- v11のワンコマンド起動を`--dry-run`で確認し、relay引数に診断topicと1.0秒安定化条件が含まれることを確認した。
- 一人用ODOMシナリオを短縮条件でsmoke testし、停止→0.25 m/s→停止の3行と各実送信時刻がCSVへ保存されることを確認した。実機カメラ、Kobuki、ハンコンへの物理出力は実施していない。
