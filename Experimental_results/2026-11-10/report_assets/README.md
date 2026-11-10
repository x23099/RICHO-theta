# 2026-11-10 日報の代表資料

カメラPNGは提出されたnative復号画像1280×720のバイト一致コピー。注釈、合成、切抜き、リサイズ、色・明るさ補正は一切していない。元はsession `4c34c8c3d6d44949afb2e921e819e563` の17:12実行で、自動保存archive `motion_withheld_20261110_171250.tar.xz` に含まれる。

|資料|用途・限界|
|---|---|
|[frame14203](decoded_4c34c8c3d6d44949afb2e921e819e563_f014203.png)|台座手前側が車体天板に隠れる例。色領域の下端を床接点だとみなして通さない理由|
|[frame14604](decoded_4c34c8c3d6d44949afb2e921e819e563_f014604.png)|天板境界参照の読取り元。参照を作った画像で、独立した検証画像ではない|
|[frame14922](decoded_4c34c8c3d6d44949afb2e921e819e563_f014922.png)|台座が見える下端半画素候補。再計算1.1424715mで、実測精度の保証ではない。数値は画像へ描き込んでいない|
|[distance_timeline.svg](distance_timeline.svg)|元の測距ログから作った時系列図。境界近傍189数値＋55保留が連続244行にまとまることを示す。カメラ画像へのoverlayではない|

元画像・CSV・生成コード・SHAは [provenance.json](provenance.json)。raw全体はGit対象外の `recordings/2026-11-10/driver_motion_171250_intake_r01/` に保持し、この代表3枚だけを日報資料として保存した。

コピーの再現：

```bash
python3 Experimental_results/2026-11-10/report_assets/prepare_assets.py
```

同じ内容がある場合は照合だけを行い、異なる既存ファイルを上書きしない。
