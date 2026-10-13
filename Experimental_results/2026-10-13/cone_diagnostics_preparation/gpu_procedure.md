# GPU PC：既存best.ptの画像別診断

対象は**hsr-Alienware-m16-R2（GPU搭載・ハンコン接続PC）**。
`~/yopi_ws`のFFBリポジトリではなく、`~/yopi_ws/RICHO-theta`で実行する。
Kobuki PCやカメラ・ハンコンの起動、録画、再学習は不要。

## 1. コード反映後に実行

今回の変更をGPU PCへ反映してから実行する。変更はまだコミット/PUSHしていないため、古いPULLだけではdiagnoseは使えない。
動作済みyolo-env・dataset・best.ptを保持し、setupやpip upgradeは実行しない。

```bash
cd ~/yopi_ws/RICHO-theta

./start_cone_yolo.sh diagnose \
  --dataset datasets/cone/ab_bootstrap_v01 \
  --weights runs/cone/train_ab_bootstrap_v01_r01/yolov8n/weights/best.pt \
  --output-dir runs/cone/diagnose_ab_bootstrap_v01_20261013_r01 \
  --diagnostic-split val \
  --device 0 \
  --imgsz 960 \
  --confidence-thresholds 0.05 0.10 0.25 0.50 0.75
```

既存runを上書きしない。既に同名outputがあればr02等の未使用名へ変える。
GPU不可・dataset未確認・hash不一致・別クラスモデルなどは拒否する。CPUへ切り替えない。
`--batch`は従来train/val用で、今回の診断は1画像ずつ（batch=1）に固定する。
単一GPUの合成forwardや学習の成功を、今回の診断コマンドの成功の代わりにしない。

## 2. 完了確認

`[INFO] Diagnose 38/38`、`[INFO] Diagnostics completed: .../analysis_report.md`が表示されること。
provenance.jsonのstatusが`COMPLETED_NOT_HARDWARE_OR_SAFETY_APPROVAL`となること。
中断/エラー時は途中runを正常完了と扱わず、エラーログを共有する。勝手にdatasetやdriverを修正しない。

```bash
./yolo-env/bin/python3 -c 'import json; from pathlib import Path; p=Path("runs/cone/diagnose_ab_bootstrap_v01_20261013_r01"); print("provenance:",json.loads((p/"provenance.json").read_text())["status"]); s=json.loads((p/"diagnostic_summary.json").read_text()); print("images:",s["image_count"],"GT:",s["gt_count"]); print(*s["threshold_summary"],sep="\n")'
```

38画像・56枠を想定。成功判定は診断処理の完了であり、検出精度の合格ではない。
Ultralyticsの設定フォルダが/tmpへ退避する警告が出たかも記録する。

## 3. 結果を共有

完了したrunフォルダ全体を圧縮する。画像3枚・CSV・条件が入るが、dataset一式やbest.ptは含めない。

```bash
test ! -e ~/Downloads/diagnose_ab_bootstrap_v01_20261013_r01.tar.xz && \
tar -cJf ~/Downloads/diagnose_ab_bootstrap_v01_20261013_r01.tar.xz \
  -C runs/cone diagnose_ab_bootstrap_v01_20261013_r01
```

同名archiveがある場合は上書きせず別名を選ぶ。r02等で実行した場合は確認・圧縮コマンドのrun名も揃える。
共有後にconfidence別TP/FP/FN、見逃したimage/gt_indexと原画像を照合し、必要な追加データや次の閾値候補を判断する。
今回はdiagnoseだけでよく、valやtrainを再実行する必要はない。
