# 新session df33e833：固定床比較モデルと表示再確認

入力は `decoded_df33e833acdf4e7d8b00d1ec37b7bcae_f002292.png`、
native1280×720。SHA256は
`375be11d55ad8db1aaa97c2bde07c095db45c63cd84b174d89f43978c963c11a`。
元バイトを `recordings/2026-11-04/floor_reference_df33e833_r01/` へ保存（Git外）。
画像の注釈・切抜き・リサイズ・再保存はしていない。

## 観測とモデル

- 格子全体は既存の9×6内角検出で不成立。検出成功と扱わず、紙外周を別途明示した。
- 紙外周の主観測はnative XY `[[296,399],[338,398],[341,410],[293,411]]`。
  床板ROI XYWH `[280,390,80,40]` 内のgray threshold170、輪郭面積562px²、
  approxPolyDP係数0.02の実頂点を用いた。旧sessionの角は流用していない。
- 閾値150による1px差、閾値190/係数0.025による2px差、
  閾値170/係数0.03による3px差を、別の感度対照として導出した。
  高さ・コーン距離に近い角や解を選んだわけではない。
- 紙実寸296×210mm、板厚概算15mm、レンズ床上高さ590mmは、同じ板・取付けという従来の申告条件を明示入力した。今回の再実測ではない。
- 主モデルは1画像×2辺対応×2平面解×2高さ条件の8候補を保持。
  対照3ケースも各8候補。配布するのは主モデル8候補だけで、対照との合成やランキングはしない。
- 主モデルas_listed解0の紙面推定高さは約513.7mm、画像法線＋紙面高さ＋板厚では約528.7mm。
  外部590mmとの違いは残る。1px対照では紙面推定約535.1mm、2px対照約469.5mm、
  3px対照約447.1mm。この差は四隅読取りの感度であり、統計的な信頼区間ではない。
- 背景の向きが以前のsessionと異なる。旧155～158cmを今回の距離正解へ転用しない。
  現sessionで測定した実距離は未受領。

## 配布ファイル

[prepared_floor_df33e833_f002292.json](prepared_floor_df33e833_f002292.json)

SHA256：`08d8409f9674c433d5151f99228c43d8f8f6fb10d7245954223f6598e3af3176`。
`derived_primary_r01/prepared_floor.json` とバイト同一。
session `df33e833acdf4e7d8b00d1ec37b7bcae` 専用。
今の受信・送信を維持する。新しい接続や旧sessionへ名前を書き換えて使わない。

上記ファイルを **GPU PC** の `~/Downloads/` へ保存後、GPU PCの別ターミナルで実行する。
受信は先の手順どおり `floor_display_fix_live_r01` を使っている前提。
違う出力先で起動した場合はLの読込み先と照合し、下記だけを適当に変更しない。

```bash
cd ~/yopi_ws/RICHO-theta
python3 -c 'from pathlib import Path; import hashlib; data=(Path.home()/"Downloads/prepared_floor_df33e833_f002292.json").read_bytes(); assert hashlib.sha256(data).hexdigest()=="08d8409f9674c433d5151f99228c43d8f8f6fb10d7245954223f6598e3af3176", "model hash mismatch"; out=Path("Experimental_results/2026-11-04/floor_display_fix_live_r01/prepared_floor.json"); f=out.open("xb"); f.write(data); f.close(); print("Saved:",out)'
```

ファイル新規作成のみ。既に存在する場合は削除・強制上書きせず、その内容を確認する。
成功後に映像ウィンドウで英字Lを1回押す。
`load_requested` → `active reason=accepted_comparison_only` と、
画面下の `MODEL SPAN ... m`、各候補の数値または保留理由を確認する。
上部の元経路のWITHHELDは、比較パネルの成功・失敗と分けて扱う。
20秒ほど静止して、画面のスクリーンショットと保存JSONL末尾を提出する。

GPU PCの別ターミナルから、元ログを変えずに末尾120行の提出ファイルを作れる。

```bash
cd ~/yopi_ws/RICHO-theta
python3 -c 'from pathlib import Path; import subprocess; p=Path("Experimental_results/2026-11-04/floor_display_fix_live_r01/distance_frames.jsonl"); data=subprocess.run(["tail","-n","120",str(p)],check=True,capture_output=True).stdout; out=Path.home()/"Downloads/floor_comparison_df33e833_recent.jsonl"; out.write_bytes(data); print(out)'
```

配布前の検査時点では実GPUでのL受入れ・表示結果は未確認だった。
その後のユーザー提出画面による確認結果は、末尾の実機続報に記載する。
上記準備のローカル検査と実機で成功したという報告は区別する。

## ユーザーが報告した台座付近の丸について

現行 `src/cone_distance_core.py::render_distance` は、
rowの `base_pixel` があるときに半径4pxの黄色い円を描く。
これは元の色輪郭支持点候補であり、距離のavailable・床接触・モデル採用の印ではない。
候補点がないrowでは描かず、workerの有効な組合せ結果がない間は
`src/run_cone_distance_live.py` が生画像へ保留表示するため円も出ない。
点滅の原因は、支持点がなくなったのか、表示結果待機・鮮度切れなのかを
その時刻のJSONL/画面で区別する必要がある。丸だけから故障・正常・推定成功を断定しない。
色・形が違う場合や元映像にも印がある場合は、スクリーンショットとの照合が必要。
今回のモデル読込みで丸を強制表示・固定化する処理は追加していない。

## 検証・再現

`verification_r01/verification.json`：導出・同session読込み・GUIの関連68件成功。
本画像の輪郭4条件、無加工/hash一致、8未選択モデル、根拠frame2292、
旧session拒否・未来frame拒否・config不一致拒否・配布バイト一致を確認。
既存の397件成功のGUI修正検証は別成果物として保持した。
カメラ・GPU・ROS・FFBはこの解析で起動していない。commit/pushも行っていない。

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 src/derive_fixed_floor_live_bundle.py --references Experimental_results/2026-11-04/floor_reference_df33e833_r01/references.json --image-dir recordings/2026-11-04/floor_reference_df33e833_r01 --board-thickness-mm 15 --external-height-mm 590 --board-on-floor --rigid-board --static-camera --output-dir Experimental_results/2026-11-04/floor_reference_df33e833_r01/derived_primary_r01
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-04/floor_reference_df33e833_r01/verify.py --output-dir Experimental_results/2026-11-04/floor_reference_df33e833_r01/verification_r01
```

出力先は既に存在するため、再実行時は未使用名を指定する。
角観測・格子不成立・幾何仮説・高さ差・画像品質受理は、
床面の物理検証・コーン接触点・絶対精度・base_link変換・FFB承認を意味しない。

## 実機続報：frame19541で比較GUIの数値表示を確認

ユーザー提出 `image (3).png` で `loader=active gen=1`、
`MODEL SPAN 1.562 - 1.744 m | available 3/8`、
`unverified_comparison_only` を視認した。少なくともこの時点のGPU上の比較GUI数値表示は確認済み。
verification.jsonの `live_load_on_gpu_verified=false` は配布前のローカル検査時点の記録として保持する。
時系列の更新は本段落と `live_gui_screenshot_evidence.json` に記録した。
20秒以上の連続安定性や今回配置の測距精度は、静止スクリーンショットだけでは承認しない。

個別に読めるモデルは `f002292_as_listed_s0_image_plane_plus_thickness` が1.562m、
`f002292_as_listed_s0_external_height_image_normal` が1.744m。
表示順位3・4は `support_behind_heading_reference` により保留。
全8候補は表示されていないので、残りの個別値は画像から推測しない。
上部の `latest_scene_image_rejected` は元の動的scene推定経路の理由であり、固定床比較経路の失敗ではない。
`image (4).png` の流れるログも元経路の `colour_contour_reaches_roi_edge` /
`support_confirmation_pending` 等である。L要求・受入れの行そのものは
このターミナル画像には残っていないが、GUIのactive状態は確認できる。
全遷移の時刻と失効有無は保存events/JSONLで別途確認する。

スクリーンショットは `../report_assets/` に元のバイト列のまま保存した。
遠隔デスクトップや既存GUI注釈を含む**ユーザー提出の画面記録**であり、
S保存した無加工nativeカメラ画像や幾何推定入力と混同しない。

### ターミナルのコピー不要：600行をファイルで提出

GPU PCの別ターミナルで、現在の元ログを変えずに末尾600行の提出用コピーを作れる。
先行の120行より長く、30件/秒なら約20秒だが、実際の秒数はログの時刻から評価する。
処理ログなので、GUI描画回数や入力フレーム全体の完全な記録とは限らない。

```bash
cd ~/yopi_ws/RICHO-theta
tail -n 600 Experimental_results/2026-11-04/floor_display_fix_live_r01/distance_frames.jsonl > ~/Downloads/floor_comparison_df33e833_recent.jsonl
```

Downloadsの同名提出用コピーは更新する。稼働中の書込み途中の最終行が含まれる場合は、
その末尾だけ解析時に区別する。ターミナルのスクロールバックやコピーのために受信を止める必要はない。

後続の提出600行の結果は [20秒間の比較値と丸点滅の解析](../floor_comparison_df33e833_live_r01/README.md) を参照。
全600行で比較値あり、loader activeを維持。元の丸用の点は312行で存在・288行で欠けたが、
欠けた行も比較値は継続した。これは今回の約20秒の処理結果であり、物理精度や全GUI描画の保証ではない。

さらにユーザーから今回配置の水平直線距離1.50mを受領した。
as_listed紙面寸法由来候補の中央値1.562406mとの差は+6.24cm。
原点・支持点と台座手前辺中央の対応および測定不確かさは未確認であり、
この1点に合わせた補正・モデル自動採用はしない。詳細は上記の20秒解析資料の末尾を参照。
