# Phase 3 衝突リスク―FFB dry-run接続検証

実施日: 2026-09-09

## 目的

`bird_eye.py`が確定した衝突リスク状態を、デバイス非依存の
`CollisionFfbCommand`としてROS 2へ送信し、Phase 2のdry-run adapterで
安全に受信・制限・停止できることを確認する。

この検証ではG923を含む入力デバイスを開かず、物理FFB出力を行っていない。

## 実装した接続

- `VirtualFfbPolicy`をライブpublisherでも再利用し、オフライン解析と同じ変換規則を使用した。
- `bird_eye.py`のヒステリシス適用後の最終リスク状態を、処理フレームごとに
  `/collision/ffb_command`へpublishするようにした。
- 既定設定ではpublisherを無効とし、
  `bird_eye_config_ttc_v6_ffb_dry_run_20260909.json`だけで明示的に有効化した。
- recording metadataへpublisher設定、`detections.csv`へsequence、要求強度、pattern、
  active、送信成否、送信エラーを追加した。
- preflightでpublisher設定値と`oit_interfaces.msg`を検査するようにした。
- 終了時は最後に`CLEAR`をpublishしてからROS nodeを破棄する。

## 単体・回帰試験

- publisher重点テスト: enum変換、sequence、時刻、終了時CLEAR、送信失敗、
  `bird_eye.py`との接続を確認した。
- リポジトリ全体: 159 tests PASS。
- FFB用ROS環境をsourceしたpreflight: PASS。
- v6派生設定は、FFB設定を除いて
  `bird_eye_config_ttc_v6_candidate_20260908.json`と同一である。
- TTC profile v6との9 runtime parameters一致: PASS。

## 2026-09-08録画の再生比較

入力: `202609081640.tar.xz`

比較対象:
`Experimental_results/2026-09-08/ttc_v6_holdout_1640/virtual_ffb_replay.csv`

| session | frames | active frames | activation events | peak demand | 結果 |
|---|---:|---:|---:|---:|---|
| approach r01 | 625 | 29 | 2 | 0.25 | MATCH |
| approach r02 | 629 | 69 | 3 | 0.25 | MATCH |
| approach r03 | 626 | 22 | 4 | 0.25 | MATCH |
| omake | 622 | 15 | 1 | 0.25 | MATCH |

全2,502フレームについて、activeフレーム数、リスク別フレーム数、activation event数、
peak normalized magnitudeが既存結果と一致した。

## ROS 2 dry-run接続結果

Phase 3 publisherからPhase 2 adapterへ実際のROS 2 topic通信で合成状態を送信した。

| risk | publisher要求 | adapter適用値 | adapter状態 |
|---|---:|---:|---|
| CLEAR | 0.00 | 0.00 | inactive |
| PATH | 0.00 | 0.00 | inactive |
| WARNING | 0.25 | 0.05 | active |
| WARNING_HOLD | 0.25 | 0.05 | active |
| CRITICAL | 0.40 | 0.05 | active |

- 30 commandを1.000秒で送信し、30.0 Hz、30件すべてのapply statusを確認した。
- 最後のactive command停止から約100 ms後、adapterが
  `reason=watchdog_timeout`、`output_active=false`、`applied=0.00`を出した。
- publisher close時の`CLEAR`とadapter終了時の`reason=shutdown`もinactiveだった。

## 判定

Phase 3の完了条件をすべて満たした。次のPhase 4は物理出力を含むため、
別途承認と現地安全準備が完了するまで開始しない。
