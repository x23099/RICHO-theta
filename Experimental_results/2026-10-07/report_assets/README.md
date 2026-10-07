# 2026-10-07 作成資料

9/29試験のchallenge間隔を、既存の両PC bagとrelay診断から再集計した。新しいカメラ録画・実機試験は行っていないため、生画像を新規収録したとは扱わない。

| グラフ | 用途 |
|---|---|
| [challenge間隔・安定待ち](../challenge_jitter_review/challenge_interval_and_stability.png) | 発行元側と受信側のbag記録間隔、relayの1秒待ち直しを説明 |
| [v11実記録とv12オフライン許可](../challenge_jitter_review/relay_gate_recorded_vs_offline.png) | 鮮度とstream継続性の分離の効果。実記録対オフライン比較という制約を含む |

図は根拠CSV・スクリプトのある[診断フォルダ](../challenge_jitter_review/README.md)へ保存し、ここから参照する。同一PNGを重複保存しない。受信揺らぎのネットワーク／DDS／OS負荷の内訳は未確定。元カメラ画像には加工していない。
