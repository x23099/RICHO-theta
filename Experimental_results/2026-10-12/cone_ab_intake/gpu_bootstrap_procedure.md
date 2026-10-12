# GPU PCでの初回コーン学習手順（2026-10-12）

## 今回実行するもの

カメラ側リポジトリのオフラインYOLO学習だけ。Kobuki、ROS、ハンコン、FFB adapterは起動しない。赤・黄色の可視コーンをclass 0 `traffic_cone`で学習する。白線逸脱・距離・FFBへの接続はまだ行わない。

初回用は`ab_bootstrap_v01`：train A=35枚、val B=38枚、計73枚・109枠。400枚版の残327枚を無確認で背景にしたものではない。枠はassistantの視覚レビューで作成しており、人による独立品質確認が残る。独立testと、コーンが全くないnegative画像は未取得。

## 1. コードとデータをGPU PCへ置く

コードは通常のGit反映で取得する。ここで使う新規CSV／コードがGPU PCに存在することを確認する。**datasetはGit対象外なので、pullだけでは画像・labelsは届かない。** 同じPCで作業する場合、既存datasetを再展開する必要はない。

解析PCで作成した受渡し用アーカイブ：

`recordings/2026-10-12_cone_ingest_ab/cone_ab_bootstrap_v01.tar.xz`

このファイルをGoogle Drive／USB等でGPU PCの`~/Downloads/`へコピーする。ファイルhashは同じ解析結果フォルダの`bootstrap_bundle_manifest.json`に保存している。GPU PCの**カメラ側リポジトリroot**で以下を実行する。GPU PCでの配置が`~/theta_ws/RICHO-theta`なら最初のcdを使う。別の場所ならcdだけ変更する。

```bash
cd ~/theta_ws/RICHO-theta

# 別PCで、datasetがまだ無いときだけ展開。既存データには上書きしない。
if test -e datasets/cone/ab_bootstrap_v01; then
  echo "既存datasetあり：再展開しません"
else
  mkdir -p datasets/cone
  tar -xJf ~/Downloads/cone_ab_bootstrap_v01.tar.xz -C datasets/cone
fi
```

今回は自分たちで作成したdatasetアーカイブの手順。未検証の任意アーカイブを同じコマンドで展開する用途ではない。

## 2. YOLO環境を確認する

既にsetup済みならsetupは省略できる。ROS用のtheta-envではなく、独立した`yolo-env`を使う。

```bash
./setup_cone_yolo.sh
./start_cone_yolo.sh env --output-dir runs/cone/environment_ab_bootstrap_v01_r01
./yolo-env/bin/python3 src/cone_dataset.py relocate --dataset datasets/cone/ab_bootstrap_v01
./yolo-env/bin/python3 src/cone_dataset.py check --dataset datasets/cone/ab_bootstrap_v01
```

出力先が既にある場合は`r02`など未使用名にする。envのPASSはCUDA演算・モデルload・合成画像forwardの確認で、実コーンの精度ではない。CUDA環境でエラーが出たらログを共有し、CPUへ切り替えて進めない。解析PCではGPU実行を確認していない。

## 3. 初回の枠を確認する（画面表示可能なPC）

```bash
./yolo-env/bin/python3 src/annotate_cone_dataset.py \
  --dataset datasets/cone/ab_bootstrap_v01 \
  --review-existing
```

通常起動ではレビュー済みをスキップするため、今回は`--review-existing`を付ける。各画像で`P`→既存枠を画面表示→`Y`で確認。前後両レンズ、台座、遠方黄色、レンズ端を確認する。`S`は保留、`Q`は終了であり、確認済みとは扱わない。保存生画像へ枠は描き込まない。

直したい枠はその場で承認せず保留する。既存GUIは非上書き型なので、YOLO対応ラベル編集ツール等で対応txtを修正してから、このコマンドで修正枠を再表示・確認する。画像は切り抜き・補正・描画しない。txtだけ変更して再確認していない場合、hash不一致でcheckが拒否する。

```bash
./yolo-env/bin/python3 src/cone_dataset.py check --dataset datasets/cone/ab_bootstrap_v01
```

全枠の人の確認を終えていない試走は、その旨を残す。checkのPASSだけを「人の確認完了」とは扱わない。

## 4. 初回学習→val

```bash
./start_cone_yolo.sh train \
  --dataset datasets/cone/ab_bootstrap_v01 \
  --output-dir runs/cone/train_ab_bootstrap_v01_r01 \
  --epochs 50 --batch 8 --imgsz 960 --device 0

./start_cone_yolo.sh val \
  --dataset datasets/cone/ab_bootstrap_v01 \
  --weights runs/cone/train_ab_bootstrap_v01_r01/model/weights/best.pt \
  --output-dir runs/cone/val_ab_bootstrap_v01_r01 \
  --device 0
```

学習中にCUDAメモリ不足が出た場合は、エラーログを残して別run名でbatchを4等へ調整する。所要時間は未測定なので予告しない。dataのsplit、ラベルを結果が良くなるように事後変更しない。

共有してほしい結果：両runの`metrics.json`・`provenance.json`、train側`model/results.csv`と`model/weights/best.pt`。実行環境は`environment_freeze.txt`で追跡できる。これらの取得後に検出漏れ・誤検知・推論時間のオフライン確認へ進む。

## 限界と次段階

- 全73枚に少なくとも1つコーンが写っており、background-only negativeは0枚。両splitともcheckに警告が出る。
- 後方の固定黄色を含む集計値だけでは、赤コーンの検出性能や誤通知率を判断できない。
- valは開発用。testコマンドは独立testなしとして拒否される。valをtestへ流用しない。
- 元400枚は残り327枚をレビューした後に拡張学習へ使える。検出枠だけで床接地点・距離・TTC・FFBが完成したとは扱わない。

詳細・再現根拠は[受入れ報告](README.md)。追加録画なしでここまでの初回試作へ進める。
