# L読込み後の比較GUI保留：明示ROIの型差修正

## 観測と判定

ユーザー報告の接続sessionは `9b7d9a17f292490c96e697af31438fd1`。
L後のログは `accepted=True reason=load_requested` → `loading` →
`active reason=accepted_comparison_only`。画面下は `invalid_comparison_result`、
`loader=active gen=1`、frame 106052、上部ROIは `(270, 0, 350, 720)`。
モデルの読込み成功と、比較結果の画面表示成功は別である。
実環境のJSONLはこの修正時点では未受領であり、実際の数値出力は未確認。

## 再現した原因

`ConeDistanceEngine` は有効なROIをtupleとして保持する。
JSONLに保存すると同じROIはlistになる。一方、比較GUIはメモリ内のrowを
保存ログ用の `validate_row` に直接渡し、その検査はlistのみを受け付ける。
このため指定ROIでのライブGUIだけが `native front-lens target ROI required`
例外を捕捉し、汎用理由 `invalid_comparison_result` として保留していた。
同一のrowをJSON化して読み戻すと比較値を表示できることを修正前に再現した。
既存GUIテストはROIなしのfixtureであり、この差を検出できていなかった。

## 修正範囲

- `src/cone_fixed_floor_display.py`：GUIの検査に使う浅いコピーでのみ、ROIのtupleをlistへ正規化する。
- `tests/test_cone_fixed_floor_display.py`：実Engineの明示ROI、保存形式との表示・描画一致、入力不変、不正ROI、安全フラグ・NaN・支持点不正・鮮度・generation拒否の回帰テスト4件を追加。
- 保存ログの厳格なvalidator、元row、距離計算、支持点判定、モデル選択、鮮度、ROS/FFB経路は変更しない。
- `colour_contour_reaches_roi_edge` 等の元距離経路の保留理由は別件であり、今回の修正はそれらを解除しない。

## 検証

修正前、新規4件を含むGUI21テストは1件失敗（実Engine ROIでWITHHELD）。
修正後は21件成功。さらに下記の既存検証スクリプトを**新しい出力先**で実行し、
397件、失敗0、エラー0、skip0となった。
合成の比較数値88行を維持し、実録画の誤session 1689行では数値0行を維持。
旧検証結果は書き換えていない。詳細・使用ソースSHAは
`verification_r01/verification.json`、個別結果は `tests.csv` / `tests.log`。
画像は合成fixtureのみで、実カメラ画像の編集・保存は行っていない。

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-02/fixed_floor_display_r01/verify.py --output-dir Experimental_results/2026-11-04/fixed_floor_display_roi_fix_r01/verification_r01
```

上記出力先は既に存在するため、再実行時は未使用の出力先を指定する。
ローカル修正前のGit HEADは `3ff362d45b0d91f379e8c5e7df062e226a8027e0`。
今回の作業ではcommit/push、GPUプロセスの変更、実機駆動は行っていない。

## 今の接続を維持したまま確認すること

GPU PCの別ターミナルで、床画像が保存されている受信フォルダを特定し、
現在のJSONL末尾120行だけを提出用に複写する。元ログは変更しない。
下のPythonコマンドは1行で貼る。PNGが一意に見つからなければ停止する。
正常に動作中のJSONLなので、最後の行が書込み途中の場合がある。
解析時は末尾の不完全行だけを区別し、正しい完全行を評価する。

```bash
cd ~/yopi_ws/RICHO-theta
python3 -c 'from pathlib import Path; import subprocess; p=list(Path("Experimental_results").glob("*/*/decoded_9b7d9a17f292490c96e697af31438fd1_f061717.png")); assert len(p)==1,p; data=subprocess.run(["tail","-n","120",str(p[0].parent/"distance_frames.jsonl")],check=True,capture_output=True).stdout; out=Path.home()/"Downloads/floor_comparison_recent.jsonl"; out.write_bytes(data); print(out)'
```

このログで `fixed_floor_load`、`fixed_floor_shadow` と各modelのavailable/reasonを確認する。
GUI不具合が再現しただけで、実データに距離が出ていると推定してはいけない。

修正コードをGPU PCへ反映するだけでは、既に起動しているPythonプロセスは更新されない。
再起動後は接続sessionが変わるため、旧prepared_floor.jsonを改名・流用しない。
再起動が必要になった時点で、新sessionの床PNGからモデルを準備する。
比較値は引き続き未検証の水平camera-foot rangeであり、前方距離、接触距離、
base_link基準、精度保証、FFBへの利用承認を意味しない。
