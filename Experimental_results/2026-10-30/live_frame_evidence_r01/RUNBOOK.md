# 実機ログ取得手順（GPU PCでユーザーが実行）

対象: HANDOFF 7.3 step 1。静止状態で60秒だけ記録する。ROS・走行・FFB・Git pushは行わない。

## 0. 前提とPCの役割

| PC | 役割 | 確認事項 |
| --- | --- | --- |
| カメラPC（`robo25-NUC11PAHi5`、`150.89.169.76`） | USBカメラ／キャプチャからRTC送信 | `/dev/video0`が見える。`bird_eye`など同じカメラの同時利用がない |
| GPU PC（`hsr`、`150.89.169.78`） | RTC受信、YOLO推論、証拠ログ | checkpoint `3a6e124a...`、`yolo-env`、このpatch適用 |

カメラがGPU PCへ直接つながっている構成ではないため、送信はカメラPCで行う。

## 1. 変更の反映（GPU PC）

この解析PCのr02差分は未commit。Git pushはせず、patchを運ぶ。

- patch: `Experimental_results/2026-10-30/live_frame_evidence_r01/transfer/frame_evidence.patch`
- SHA-256: `b884b2234a2fb2ae91c0bfe7f9f3070edc66269ede3aa24a2a4c19cf2f6b1bea`
- 基準: `5791a80`。初回実機ログ後の鮮度再同期修正と、接触辺を記録するr02拡張を含む。

GPU PCのrepoが`5791a80`相当であることを確認する。**初回patchを既に適用している場合は、下の5ファイルだけ元に戻してからr02 patchを当てる。** 他の変更が見えたら中止する。

```bash
cd ~/yopi_ws/RICHO-theta
git status --short
git checkout -- src/cone_distance_core.py src/cone_distance_worker.py \
  src/run_cone_distance_live.py src/summarize_cone_distance_live.py
rm -f tests/test_frame_evidence_logging.py
git status --short          # 対象5ファイルの変更が消えたこと
git apply --check /path/to/frame_evidence.patch
git apply /path/to/frame_evidence.patch
git status --short          # src 4ファイルと新規testのみ
```

patchは次を変更する。

- `src/cone_distance_core.py`
- `src/cone_distance_worker.py`
- `src/run_cone_distance_live.py`
- `src/summarize_cone_distance_live.py`
- `tests/test_frame_evidence_logging.py`（新規）

テスト:

```bash
"$PWD/yolo-env/bin/python3" -m unittest discover -s tests -p 'test_frame_evidence_logging.py' -v
"$PWD/yolo-env/bin/python3" -m unittest discover -s tests -p 'test_cone_distance_diagnostic.py'
"$PWD/yolo-env/bin/python3" -m unittest discover -s tests -p 'test_summarize_cone_distance_live.py'
```

16件＋30件＋25件がPASSすることを確認する。

## 2. checkpointの確認（GPU PC）

```bash
sha256sum "$HOME/Downloads/cone_distance_v03.pt"
# 3a6e124adb15c16efd7d22c853406066371f48873c82f1d3cfc445b22ae5997b
```

不一致なら起動前に`YoloConePredictor`が拒否する。**別checkpointへ差し替えて設定hashを書き換えない。** その場合は中止して、checkpointの所在を確認する。

## 3. 受信待機（GPU PC）

先に受信側を起動する。

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"
HANDOFF_RUN_ID="$(date +%Y%m%d_%H%M%S)"
echo "$HANDOFF_RUN_ID"
./start_cone_distance.sh receive \
  --weights "$HOME/Downloads/cone_distance_v03.pt" \
  --target-roi 270 0 350 720 \
  --colour-support-shadow --support-completion-shadow --frame-evidence \
  --duration-sec 60 \
  --output-dir "Experimental_results/2026-10-30/live_frame_evidence_r02_${HANDOFF_RUN_ID}"
```

表示環境がないSSH実行なら`--headless`を追加する（Sキー画像は保存されない）。今回の目的は接触辺の特定なので、可能なら表示ありで実行し、開始後に対象コーンが写ったところで**必ずSキーを一度押して無加工PNGを残す**。

## 4. 送信（カメラPC）

受信待機のあと、カメラPCで:

```bash
cd ~/theta_ws
export THETA_RTC_PYTHON="$PWD/theta-env/bin/python3"
bash src/start_theta_stream_rtc.sh --diagnostic --receiver-ip 150.89.169.78 --device /dev/video0 --fps 30
```

60秒で受信側が自動停止する。送信側はQ/Ctrl+Cで止める。カメラ・固定位置・向きは10/30と同じ条件を維持し、動かさない。

## 5. 取得直後の確認（GPU PC）

```bash
cd ~/yopi_ws/RICHO-theta
IN="Experimental_results/2026-10-30/live_frame_evidence_r02_${HANDOFF_RUN_ID}"
wc -l "$IN/distance_frames.jsonl"
python3 - "$IN/distance_frames.jsonl" <<'PY'
import json, sys
from collections import Counter
rows = [json.loads(line) for line in open(sys.argv[1])]
ev = [r["frame_evidence"] for r in rows if "frame_evidence" in r]
print("rows", len(rows), "evidence", len(ev))
print("one_box", sum(len(e["selected_detector_boxes"]) == 1 for e in ev))
print("support", sum(e["support_observation"]["point"] is not None for e in ev))
print("pose", sum(e["pose"]["pose_available"] for e in ev))
print("fresh", sum(e["freshness"]["within_limit"] for e in ev))
print("reasons", dict(Counter(r["reason"] for r in rows)))
print("distance_available", sum(r["distance_available"] for r in rows))
print("inference", sorted({r["inference_source"] for r in rows}))
print("flags", {(r["physical_metric_verified"], r["floor_contact_verified"], r["usable_for_ffb"]) for r in rows})
PY
```

期待:

- `evidence == rows`（全行にブロック）
- `inference == ["live_cuda_yolo"]`
- `flags == {(False, False, False)}`
- 10/30と同じ背景なら`pose`は0のまま（`scene_reason`に平面不足）。これをログ拡張で隠さない。
- `distance_available`は0でもよい。0でない場合も条件付き診断であり、物理精度の合格ではない。

集計:

```bash
./start_cone_distance.sh report \
  --input-dir "$IN" \
  --output-dir "Experimental_results/2026-10-30/live_frame_evidence_r02_report_${HANDOFF_RUN_ID}"
```

`summary.json`の`frame_evidence`と`processed_frames.csv`を確認する。

## 6. 返送（解析PCへ）

```bash
cd ~/yopi_ws/RICHO-theta
tar -cJf "/tmp/live_frame_evidence_r02_${HANDOFF_RUN_ID}.tar.xz" \
  -C Experimental_results/2026-10-30 "live_frame_evidence_r02_${HANDOFF_RUN_ID}" \
  "live_frame_evidence_r02_report_${HANDOFF_RUN_ID}"
sha256sum "/tmp/live_frame_evidence_r02_${HANDOFF_RUN_ID}.tar.xz"
```

解析PCへは、許可された経路（USBまたは既存のscp設定）で`~/theta_ws/`へ置く。返送後、解析PC側で集計・検証・HANDOFF更新を行う。解析PCでは`flatten_evidence.py`で1フレーム1行へ展開する（`README.md`参照）。

## 中止条件

- checkpoint hash不一致
- `/dev/video0`が見えない、または他のプロセスがカメラを占有
- 受信側がCUDA初期化前に失敗
- 対象コーンが写らない、カメラを動かす必要がある

中止時は数値を捏造せず、`live_summary.json`とエラー文だけを返す。
