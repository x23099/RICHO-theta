# 実験ランチャー

## 目的

`src/run_field_experiment.py`は、preflightと`bird_eye.py`へ同じ実験条件を渡し、
preflightがPASSした場合だけアプリを起動する。以前発生した`--odom-topic /odom`の指定忘れや、
確認時と録画時でconfig、保存先、カメラ条件が異なる事故を防ぐ。

## 基本操作

リポジトリ直下で、保存先と最初の実験ラベルを指定する。

```bash
python3 src/run_field_experiment.py \
  --record-dir recordings/2026-08-27 \
  --experiment-label pilot_odom
```

既定値は次のとおり。

| 項目 | 既定値 |
|---|---|
| config | `src/bird_eye_config_raw_ground_distance.json` |
| カメラ | device 0、1280x720、30 fps |
| preflight読込フレーム | 60 |
| ODOM | `/odom`、timeout 3秒 |
| 空き容量 | 20 GiB以上 |
| Git | clean必須 |
| 単体テスト | 実行する |

preflightが1項目でもFAILした場合、`bird_eye.py`は起動しない。PASSした場合だけ、同じconfig、
保存先、カメラ条件、ODOM topicを使ってGUIを起動する。

## 機材なしの確認

次のコマンドはカメラ、ROS、保存先へアクセスせず、実行予定の2コマンドだけを表示する。

```bash
python3 src/run_field_experiment.py \
  --record-dir recordings/2026-08-27 \
  --experiment-label pilot_odom \
  --dry-run
```

## 条件を変更する場合

本番configを明示する例:

```bash
python3 src/run_field_experiment.py \
  --config src/bird_eye_config.json \
  --record-dir recordings/2026-08-27 \
  --experiment-label pilot_odom
```

`--allow-dirty-git`と`--skip-tests`は、通常のholdoutでは使用しない。調査中に意図して解除する場合だけ
明示する。利用可能な全引数は`python3 src/run_field_experiment.py --help`で確認できる。

## 確認済み動作

- config、保存先、device、解像度、FPS、ODOM topicの引数共有。
- preflight失敗時にアプリを起動しない。
- preflight成功後だけアプリを起動する。
- `--dry-run`では外部コマンドを実行しない。
- clean Gitを既定で要求し、明示指定時だけ解除する。
