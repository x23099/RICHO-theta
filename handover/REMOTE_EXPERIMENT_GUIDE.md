# 自宅リモート環境での録画解析手順

## できる作業と制約

録画済みデータの距離再計算、校正、ホールドアウト判定、CSV出力は、学校のカメラやGUIを起動せず自宅から実行できる。新しい物理配置の撮影、カメラの取付け変更、実測距離の確認は現地作業が必要である。

## 学校を離れる前の確認

1. NUCと自宅から接続するPCの両方へ、今回のソース変更を同期する。
2. 録画フォルダ内に各地点の `raw.avi` と `metadata.json` があることを確認する。
3. 録画フォルダ名を `cal_xm0.20_z1.00` または `holdout_xp0.20_z1.00` の形式にする。`m` は左、`p` は右を表す。
4. リモート接続ソフトが再起動後も接続可能か、学校内にいる間に一度再接続して確認する。
5. NUCの自動スリープを無効化し、AC電源とネットワーク接続を確認する。

## ヘッドレス評価

リポジトリ直下で次を実行する。`--calibration` と `--holdout` は複数回指定できる。

```bash
cd ~/yopi_ws/RICHO-theta
python3 src/evaluate_ground_contact.py \
  --calibration ~/Downloads/recoding_20260807_4 \
  --calibration ~/Downloads/recoding_20260807_5 \
  --holdout ~/Downloads/recoding_20260807_6 \
  --frame-step 5 \
  --output Experimental_results/ground_contact_evaluation.csv \
  --model-output Experimental_results/ground_contact_model.json
```

最後に `Decision: PASS` が表示されれば、基準「平均誤差5 cm以下、最大誤差8 cm以下」を満たす。`CONDITIONAL_PASS` または `FAIL` の場合は、そのデータで直ちに設定を書き換えず、まず録画名の正解距離、カメラ取付け、箱の基準点、検出率を確認する。

このCLIに不要なもの:

- カメラ接続
- デスクトップ画面・Qt
- PyTorch
- Ultralytics/YOLO

必要なPythonパッケージは `numpy` と `opencv-python` である。

## 自動テスト

```bash
cd ~/yopi_ws/RICHO-theta
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

4件すべてが `ok` になれば、投影・床交点・座標名解析・横方向校正の基本動作は正常である。

## GUIをリモート表示する場合

RustDesk等で学校PCのデスクトップへ接続できる場合は従来どおり起動できる。

```bash
cd ~/theta_ws/src
# ここで普段使っている方法で theta-env を有効化する
python3 bird_eye.py
```

録画済み動画を入力する場合は、カメラ番号の代わりに動画を指定する。

```bash
python3 bird_eye.py --device /absolute/path/to/raw.avi
```

GUIが不要な再解析では `evaluate_ground_contact.py` を優先する。接続が切れても撮影済みデータは失われず、結果の再現もしやすい。

## カメラ設定を変更した場合

高さ、pitch、roll、yaw、レンズ中心、radius scale、カメラ取付け位置を変更すると幾何モデルの条件が変わる。変更後は、校正用と未使用のホールドアウト用を分けて再撮影し、同じCLIで再判定する。ホールドアウト結果を見ながら校正値を調整してはいけない。
