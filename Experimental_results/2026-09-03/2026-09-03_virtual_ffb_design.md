# 仮想FFB要求生成の設計と録画再生

## 結論

衝突リスク状態からデバイス非依存の正規化FFB要求を生成する`src/virtual_ffb.py`を追加した。
現段階ではCSV再生評価だけを行い、G923、`/dev/input/event*`、ROS topicへは出力しない。
`--profile`を指定した場合は、録画済みの警告列ではなく、指定profileの速度源、TTC、
警告ヒステリシスをフレーム単位で再計算してからFFB要求へ変換する。

## 既存仕様の確認

- Linux KernelのForce Feedback仕様では、対応effectを問い合わせ、effectをuploadした後、
  `EV_FF` eventで再生・停止する。初期化時に機器が強く振動する可能性も公式文書で警告されている。
  <https://kernel.org/doc/html/latest/input/ff.html>
- ROS 2の`std_msgs/Float32`は意味を持つ独自messageの代用として非推奨である。
  実機接続時は強度だけのtopicではなく、状態、強度、pattern、生成時刻を持つmessageを定義する。
  <https://docs.ros.org/en/ros2_packages/humble/api/std_msgs/msg/Float32.html>
- ROS 2のsensor-data QoSは古い値の再送より最新値を優先する。将来のFFB要求も、
  滞留した警告を再生しない小さなqueueとwatchdogを前提にする。
  <https://docs.ros.org/en/humble/Concepts/Intermediate/About-Quality-of-Service-Settings.html>

## 仮想ポリシー

値は物理トルクではなく、比較用の無次元候補である。

| 衝突状態 | active | 正規化強度 | pattern |
|---|---:|---:|---|
| `CLEAR` / `PATH` | 0 | 0.00 | off |
| `WARNING` | 1 | 0.25 | steady |
| `WARNING_HOLD` | 1 | 0.25 | steady_hold |
| `CRITICAL` | 1 | 0.40 | steady |
| `UNKNOWN` / 不正値 | 1 | 0.15 | pulse |

不明状態を無出力にすると認識喪失を安全と誤認するため、弱い注意要求へ写像する。
強度は`0 <= unknown <= warning <= critical <= 1`を満たさない設定を拒否する。

## 2026-09-03録画再生

| 条件 | 仮想FFB active frame | 最大強度 | 起動event |
|---|---:|---:|---:|
| 約0.08 m/s接近 r01/r02/r03 | 0/0/0 | 0.00 | 0/0/0 |
| 静止 | 0 | 0.00 | 0 |
| 0.10 m/s後退 | 0 | 0.00 | 0 |
| 0.20 m/s接近 r01/r02/r03 | 26/22/26 | 0.25 | 1/1/1 |

正しい0.20 m/s接近だけで1回ずつ要求が立ち上がり、静止・後退・TTC 4.6秒より長い接近では
誤要求がなかった。詳細値は`2026-09-03_virtual_ffb_replay.csv`に保存した。

### `202609031410.tar.xz`へのv5再計算

録画時の画像速度による警告列を使わず、v5の`conservative`方式で再計算した。

| 条件 | active frame | 最大強度 | 起動event |
|---|---:|---:|---:|
| 0.10 m/s接近 r01/r02/r03 | 0/0/0 | 0.00 | 0/0/0 |
| 0.20 m/s接近 r01/r02/r03 | 12/10/12 | 0.25 | 1/1/1 |
| 0.10 m/s後退 r01/r02/r03 | 0/0/0 | 0.00 | 0/0/0 |
| 静止 r01/r02/r03 | 0/0/0 | 0.00 | 0/0/0 |

出力は`202609031410_analysis/virtual_ffb_replay.csv`に保存した。各行へ
`risk_source=profile_replay`、`velocity_source=conservative`、v5 profileのパスを記録している。
この結果は現在候補によるオフライン再生であり、録画時の実行設定を改変するものではない。

## 実機接続前の残作業

1. G923 event deviceのFF capabilityと保持可能effect数をread-onlyで確認する。
2. 意味付きROS messageと100 ms程度のwatchdogを設計する。
3. 明示的enable、最大gain、終了時zero、通信断時zeroを実装する。
4. 車体を停止した状態で最低強度から単体試験する。
5. 人が保持した状態で過大な急変がないことを確認してから走行試験へ進む。

現在の実装には物理デバイスadapterがないため、意図せずハンドルが動く経路は存在しない。
