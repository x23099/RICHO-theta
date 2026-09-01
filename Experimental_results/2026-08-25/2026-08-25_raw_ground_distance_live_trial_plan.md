# 2026年8月25日 raw_ground_distance実機確認手順

## 1. 目的

左右位置による観測ゲートの非対称を改善する候補`raw_ground_distance`を、MJPG 30 fps・
単調時計に統一した実機録画で確認する。本試験は実装確認であり、候補を選定した既存録画から
独立した最終holdoutではない。

## 2. 使用する開発設定

`src/bird_eye_config_raw_ground_distance.json`を使用する。本番設定
`src/bird_eye_config.json`は変更しない。

| 項目 | 開発設定 |
|---|---:|
| 面積正規化距離 | `raw_ground_distance` |
| 正規化面積しきい値 | 2000 |
| NISしきい値 | 9.21 |
| 観測確認フレーム数 | 2 |
| HSV V下限 | 30 |
| 照明補正 | `none` |

## 3. 録画前確認

KobukiとODOMを起動した後、リポジトリ直下で次を実行する。

```bash
python3 src/preflight_field_experiment.py \
  --config src/bird_eye_config_raw_ground_distance.json \
  --record-dir recordings/2026-08-25_raw_ground_distance \
  --camera-device 0 \
  --camera-fps 30 \
  --camera-frames 60 \
  --odom-topic /odom \
  --require-clean-git
```

`Experiment config`に次の値が表示され、総合判定が`PASS`であることを確認する。

```text
area_mode=raw_ground_distance, normalized_area_min=2000,
nis_max=9.21, confirm_frames=2, hsv_v_min=30, illumination=none
```

## 4. アプリ起動

```bash
python3 src/bird_eye.py \
  --device 0 \
  --camera-fps 30 \
  --config src/bird_eye_config_raw_ground_distance.json \
  --record-dir recordings/2026-08-25_raw_ground_distance \
  --experiment-label raw_gate_check \
  --odom-topic /odom
```

## 5. 最小録画セット

Kobukiとカメラの位置を途中で変えず、各録画前に画面の実験ラベルを変更する。

| 順番 | 条件 | 実験ラベル | 時間・操作 |
|---:|---|---|---|
| 1 | 青箱なし | `hakonasi_raw` | 10秒 |
| 2 | 中央 `x=0, z=1.0 m` | `x0.0mz1.0m_raw` | 10秒 |
| 3 | 左 `x=-0.40, z=1.0 m` | `x-0.4mz1.0m_raw` | 10秒 |
| 4 | 右 `x=+0.40, z=1.0 m` | `x0.4mz1.0m_raw` | 10秒 |
| 5 | 中央 `x=0, z=1.0 m`遮蔽 | `x0.0mz1.0m_syahei_raw` | 約15秒、遮蔽2回 |

遮蔽では、観測安定、完全遮蔽、再出現後の安定を各2秒程度確保する。今回は暗所問題を混在
させないため、`z=0.8 m`は録画しない。

## 6. 録画後

録画フォルダ全体をtar.xzへまとめ、ファイル名と保存場所を共有する。解析では次を確認する。

- 左右の観測採用率と追跡率
- 正規化面積の左右差
- 箱なし時の誤追跡
- 遮蔽2イベントの追跡解除と再捕捉
- 動画とCSVのフレーム数、実効FPS、ODOM有効率

合格後に候補値を固定し、今回とは異なる位置・距離で独立holdoutを録画する。
