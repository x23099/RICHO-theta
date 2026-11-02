# 床画像→固定床の候補モデル→Lキー読込みの接続

2026-11-02。撮影なし、保存画像のみ。**手順1のソフトウェア接続を実装した。実機の距離精度やライブ動作の合格ではない。**

## できるようになったこと

新しい`src/derive_fixed_floor_live_bundle.py`で、同じ受信接続から保存した無加工PNGを入力し、既存のKB4単位光線→OpenCV IPPEによる床平面候補を計算して、[Lキー読込み機能](../fixed_floor_live_load_r01/README.md)へ渡せるファイルを生成する。

入力は明示的にどちらかを選ぶ。

| 入力経路 | 計算の根拠 | 失敗時 |
| --- | --- | --- |
| `--checkerboard-image` | 指定した床板ROI内の9×6内角、実測マス寸法 | 不検出・小さすぎる格子は保留。紙外周へ自動切替しない |
| `--references` | 元画像上で別途観測した紙外周4隅、PNG hash、実寸のJSON | 不正座標・画像不一致・部分/交差四角形は拒否 |

紙外周経路では、紙の長辺/短辺の対応2通りとIPPEの平面解を残す。格子経路でもIPPEの複数解を残す。**画像だけから物理的な床や正しい紙を認定する機能ではない。** 窓などにある別の格子を使わないよう、格子経路では床板を含むnative ROIを必須にした。

高さは暗黙に59 cmへ固定しない。以下を別のモデルとして保存する。

- `--board-thickness-mm`：画像から得た紙面までの高さ＋明示した板厚。
- `--external-height-mm`：画像から得た法線＋外部入力のレンズ床上高さ。画像による高さ推定ではなく、別の比較条件。

どちらか一つ以上を明示する。両方指定すれば両方残す。距離正解を渡す引数や、59 cmに近い解を選ぶ処理はない。解ごとの再投影残差も記録するが、低残差だけで物理精度を認定せず、高残差の解も比較候補として明記する。複数候補の最小/最大は統計的な信頼区間ではない。

## 今回の保存画像での結果

正式出力は`results_r02/`、正式検証は[verification_r03/verification.json](verification_r03/verification.json)。

- 入力：10/30の同session PNG、frame1259・1655。元画像は再保存・切抜き・注釈・縮小していない。
- 紙外周296×210 mm、板厚概算15 mm、外部レンズ高さ590 mmは以前のユーザー回答を明示入力として使用。
- 観測4隅は[references.json](references.json)に、以前の固定閾値170による整数座標と画像hashを記録。別画像へその座標を転用しない。
- 2 frame × 2辺対応 × 2平面解 × 2高さ条件＝**16モデル**。いずれも未選択・比較専用。
- 8個の平面解は、以前の`white_paper_quad_measured_r01.json`との最大数値差が1e-9未満。
- 生成ファイルを同sessionとしてローカル読込みでき、別sessionは拒否。再接続時の失効も仮想frameメタデータで確認した。**仮想frame1700/1701は実撮影画像ではない。**
- 新規21件を含む**関連360テストPASS、failure/error/skipとも0**。

これは**以前の四隅による計算を再利用可能なコマンドへ接続した結果**である。後続の辺精密化・共同fitによる3モデルを16モデルで置き換えたわけではなく、精度改善とも判定しない。紙角・板厚・内部校正の不確かさ、レンズ高さの差は残る。

`results_r01`は初回実行。`results_r02`は生成に使ったソース・camera/floor/configのhash記録を加えた正式版。`verification_r01`は拡張前356テスト成功、`verification_r02`は仮想GUI試験のasyncio executor終了待ちで100秒timeout、`verification_r03`はテストだけを修正して360テストと全照合が成功した版。仮想GUIの即時終了stubを別threadへ渡さず実行するようにし、実workerのthread/終了試験は維持した。変更前のテストを`source_snapshot/`で旧hashへ照合し、過去manifestは書き換えていない。アプリの終了処理は変更していない。

## 再現：解析PCで既存画像を使うだけ

未使用の出力名に変更する。カメラ・GPU・ROSは不要。

```bash
cd /home/robo25/theta_ws/RICHO-theta
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 \
  src/derive_fixed_floor_live_bundle.py \
  --references Experimental_results/2026-11-02/fixed_floor_derivation_r01/references.json \
  --image-dir Experimental_results/2026-10-30/floor_board_pair_r01/originals \
  --board-thickness-mm 15 --external-height-mm 590 \
  --board-on-floor --rigid-board --static-camera \
  --output-dir Experimental_results/2026-11-02/fixed_floor_derivation_r01/recheck_new
```

出力：

- `explicit_floor_models.json`：元の同session候補モデル。
- `derivation_report.json`：観測点・既知寸法・全平面解・残差・使用した入力とソースhash。
- `prepared_floor.json`：保存PNG/config/cameraとの来歴を付けたLキー読込み用ファイル。

新規フォルダのみ使用し、既存ファイルを上書きしない。途中失敗時に不完全な診断フォルダが残ることはあるが、コマンド成功前にLを押さない。

## 後日：同じ実機接続で使う順序

今日は実行しない。GPU/ハンコンPCで、従来の受信コマンドに次の指定を付ける。

```bash
--fixed-floor-reload-file "$FLOOR_RUN/floor_model_r01/prepared_floor.json"
```

`FLOOR_RUN`は受信の`--output-dir`と同じ未使用フォルダ。完全な受信コマンドは[読込み手順](../fixed_floor_live_load_r01/README.md)を参照し、モデルパスだけ上記へ合わせる。

1. matunuc側の診断映像送信とGPU側の受信を開始。カメラ・機体は静止し、接続は維持する。
2. 床へ平置きした剛性板をSキーで保存。画像は`FLOOR_RUN`直下に保存される。
3. GPU PCの別ターミナルで下記の形式によりモデル生成。`FLOOR_RUN`は受信時と同じ実在フォルダを指定する。`FLOOR_PNG`はそのPNG、`BOARD_X/Y/W/H`は床板の元1280×720画像内の範囲へ置き換える。**ROIはXYWHで、コーン対象ROIのXYXYとは違う。**
4. コマンド成功後、受信ウィンドウへ戻ってL。読込み完了後に届く画像から、既存の支持点品質・鮮度確認を経て比較ログが作られる。

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"
"$THETA_DISTANCE_PYTHON" src/derive_fixed_floor_live_bundle.py \
  --checkerboard-image "$FLOOR_PNG" --square-mm 20 \
  --roi "$BOARD_X" "$BOARD_Y" "$BOARD_W" "$BOARD_H" \
  --board-thickness-mm 15 --external-height-mm 590 \
  --board-on-floor --rigid-board --static-camera \
  --output-dir "$FLOOR_RUN/floor_model_r01"
```

20/15/590 mmは今回の既知条件を示す例。別の板・取り付け状態で未確認ならそのまま流用しない。平置き・剛性・カメラ静止のflagは、画像からの自動認定ではなく操作者の確認。

格子が読めなければここで保留。今回の小さい2枚も格子不検出だったため、外周4隅の明示JSONで処理した。外周経路は`references.json`の形式を使えるが、**新しいPNGの実際の角とhashを観測して入力する必要がある**。古いファイル名・座標・sessionの差し替えで通さない。

受信を再起動すると別sessionになる。古いモデルを現在の接続へ流用しない。画像から得た床モデルと物理的な床接点・絶対距離・base_link変換の正しさは別問題。比較値のGUI描画、本判定・TTC・ROS/FFBへの接続は今回行っていない。

## 次の段階

手順1の入出力は接続済み。次は手順2として、**既存の時系列画像/保存予測で、読込み前後の距離・保留・失効の一連の挙動を評価する**。今日この実装で実距離が正しくなったとは扱わず、独立した実測基準による物理確認は実機時に残す。

同日続報：[手順2の結果とデータ不足](../fixed_floor_lifecycle_replay_r01/README.md)。別sessionの実1,689行の拒否と合成入力の正常/異常遷移は確認したが、今回のモデルと同sessionの後続実画像/ログはなく、実モデルの正の連続評価は未完了。別sessionへ転用して埋めていない。

日付は11/2で整理。Git commit/push、追加撮影、GPU推論、カメラ/機体操作は行っていない。別作業中の赤のみ評価も変更していない。
