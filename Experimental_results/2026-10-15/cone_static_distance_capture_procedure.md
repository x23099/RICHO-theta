# 次の段階：床置き赤コーンの静止・距離確認

## 目的と範囲

コーン検出枠の下端と実際の接地点が対応するかを確認するための少量の参照録画。
検出モデルの学習用画像をむやみに増やす試験ではなく、**静止状態の距離・左右位置の検証**。
連続録画比較の結果は[動画比較](cone_video_comparison_r01/README.md)へ記録する。
ハンコン、FFB adapter、challenge relay、模擬速度、走行操作は不要。
TTCや接近時の警告の実験は、今回の座標確認の後で行う。

## 設置

- カメラはこれまでのTHETA・車体への固定方法・解像度1280×720を維持。高さ・傾きは変えない。
- Kobukiもコーンも各録画中は静止。赤コーンは床に立て、台座全体が見える位置に置く。手で持ち上げない。
- 反射の少ない床を選ぶ。人はレンズとコーンの間から退く。
- 後方や周辺にほかのコーンがある場合は、可能なら画角外へ移動する。移動できなければ個数と位置をメモ。
- 各配置は録画を始める**前**に整え、録画中の置き替え区間を混ぜない。

### 距離の基準

原点はこれまでと同じ**カメラ直下（Kobuki中心）**。車体前端ではない。
床面で、コーンの台座の「車体に近い辺の中央」までの位置を測る。
同じ辺が車体側になる向きを維持し、対象点に床テープで印をつけてから台座を置く。
コーンの頂点・軸中心までの距離と混ぜない。台座の幅/奥行も一度だけ測ってメモする。

`x`は車体右が正、`z`は前方が正。左右配置の`z=1.30m`は前後方向の値であり、斜めの直線距離を1.30mにする意味ではない。
テープ等の設置を数mm単位で完璧にする必要はない。実際に測った値と、分かる範囲の測定誤差を残す。

## 録画6本

| 順 | label | 配置 | 長さの目安 |
|---|---|---|---:|
| 1 | `cone_static_no_cone_r01` | 両レンズにコーンなし | 10秒 |
| 2 | `cone_static_center_z0p80_r01` | x=0、z=0.80m | 20秒 |
| 3 | `cone_static_center_z1p30_r01` | x=0、z=1.30m | 20秒 |
| 4 | `cone_static_center_z2p00_r01` | x=0、z=2.00m | 20秒 |
| 5 | `cone_static_left_z1p30_r01` | x=-0.40m、z=1.30m | 20秒 |
| 6 | `cone_static_right_z1p30_r01` | x=+0.40m、z=1.30m | 20秒 |

合計約110秒＋設置時間。最初は各1本でよく、同じ条件の3回反復や接近走行はまだ不要。
2.00mを確保できなければ無理をせず、測れる距離をメモして知らせる。

## 起動コマンド：KobukiPC（matunuc-NUC13ANHi5）

既存のカメラ/ROS環境を準備し、Kobukiを停止状態にする。
FFB adapter/relayは起動しない。Gitがcleanであることと`/odom`を確認してから実行する。
これは録画準備の既存preflightを維持するための`/odom`で、今回の距離評価に模擬の接近速度は使わない。

```bash
cd ~/theta_ws
export ROS_DOMAIN_ID=88
export ROS_LOCALHOST_ONLY=0

git status --short
ros2 topic echo /odom --once

python3 src/run_field_experiment.py \
  --config Experimental_results/2026-10-12/cone_yolo_preparation/cone_capture_config.json \
  --record-dir src/recordings/2026-10-15_cone_static_distance \
  --experiment-label cone_static_no_cone_r01 \
  --camera-device 0 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /odom \
  --odom-timeout-sec 10
```

実際の撮影日が違えば、`--record-dir`の日付だけ撮影日へ変更する。
既存の専用configでFFB publish=0、relay=0、AI=0を維持する。
**この時点でコーンにYOLO枠が表示されなくても問題ない。raw映像を後で同じモデルに入力する。**
preflightがFAILならその理由を確認し、clean GitやODOMの検査を無条件に迂回しない。
`--camera-frames 60`は事前検査の枚数であり、録画枚数/録画時間ではない。

## GUIでの操作

1. コーンなしの状態で`Start Recording` → 約10秒 → `Stop Recording`。
2. 次の配置を作り、GUIの実験label欄を表の次のlabelへ変更する。
3. `Start Recording` → 約20秒 → `Stop Recording`。
4. 2～3を残りの配置で繰り返す。アプリを6回起動し直す必要はない。
5. 全て保存されたことを確認してアプリを正常終了する。

GUIのlabelは録画開始時に読み取られ、毎回別のsessionフォルダに保存される。
録画中はlabel変更や設定スライダー操作をしない。

## 渡すもの

- 保存された6つのsession（`raw.avi`、`metadata.json`、`detections.csv`を含めてまとめる）。
- 実測x/zの値、測定誤差の目安、台座の幅/奥行。
- カメラ位置/高さ/傾きを変えていないこと、後方の別コーンや遮蔽等があればその情報。

この録画で距離・左右位置の妥当性を確認してから、対象ごとの追跡・TTC・仮想FFBへ進む。
録画や重いmodelをGitには追加しない。
