# 手順3：未検証の比較距離を別GUIパネルに表示

2026-11-02。実機を使わず実装・検証。**比較表示の機能ができた段階であり、実カメラでの連続測距・物理精度の合格ではない。**

## 画面上の区別

既存の映像表示の下へ、独立した260 pxのパネルを追加した。`--fixed-floor-models`または`--fixed-floor-reload-file`を使う場合だけ表示し、追加の起動引数は不要。既定OFF時の表示と処理は変更していない。

| 領域 | 表示 | 意味 |
| --- | --- | --- |
| 従来の上部 | `forward ... m` または `WITHHELD` | 元の距離判定。今回変更なし |
| 新しい下部 | `UNVERIFIED COMPARISON ONLY`、`MODEL SPAN ... m` | 未選択の固定床候補から得た条件付き水平距離。本判定・FFBへ使わない |
| 下部の各行 | モデル名・値、または保留理由 | bundle順。距離が都合よい順ではない |

**主判定の`WITHHELD`を、比較値が出たことで解除しない。** 比較値はカメラ直下の床への射影点からの水平距離で、前方成分、車体前端距離、実測base_link距離、接地の保証とは異なる。

`MODEL SPAN`は数値が得られたモデルの最小～最大。精度・誤差・信頼区間ではない。`available 4/8`等で有効な候補数と全数を示す。行は先頭4モデルまでとし、省略数と「全結果はJSONL」を表示する。省略したモデルも範囲の計算とログには含まれ、採用/棄却の選別ではない。

## 古い数値を残さない条件

- 読込み中、待機、拒否、終了、対応する新しい結果がまだない場合は保留。
- 現在のloaderと結果のgeneration、bundle hash、sessionを再照合。新しいL要求で旧結果が残っていても表示しない。
- 表示対象のsession/frame/受信時刻が結果と一致するか確認。
- 保存済みの処理時ageに加え、**画面を組み立てる時点**の局所時刻でも500 ms上限を再確認。
- 支持点・品質・モデル結果・未承認flag・時刻を既存の行検証器で検査。不正な値があれば比較表示を保留。
- 表示関数は前回値をキャッシュしない。欠測、遮蔽、失効、再読込み失敗を前回数値で埋めない。

これはGUI更新時の検査。OSの画面提示遅延や、画面が実際に更新されるまでの時間を計測したものではない。実機のリアルタイム鮮度保証を追加したとは扱わない。

## 元画像と保存

GUIキャンバスは1280×980（従来1280×720＋パネル260）。従来部分を縮小・変形せず、表示用のコピーへ付加する。元のフレーム配列・判定dictは変更しない。

**Sキーは従来どおり無加工1280×720の復号PNGを保存する。パネル付き画面は保存しない。** 保存先も従来の受信出力フォルダで、L/Qの操作も変更なし。

今回保存した表示例は、実カメラ写真を注釈加工したものではなく、すべて新規の**合成テスト画像**。実機の成功画像として使わない。

- [数値表示の合成例](verification_r02/SYNTHETIC_preview_f000015.png)
- [600 ms経過による保留の合成例](verification_r02/SYNTHETIC_preview_f000060.png)
- [再読込み中に旧数値を消した合成例](verification_r02/SYNTHETIC_preview_f000111.png)

各例の元パターンは`verification_r02/SYNTHETIC_native_cone.png`。UIの値・表示文字列・hashは`preview_manifest.json`へ記録した。`RECORDED RECOMPUTATION`は保存された合成観測の再表示であり、下部の`SYNTHETIC PREVIEW - NOT REAL CAMERA`も常に明記している。

## 検証結果

正式結果：[verification_r02/verification.json](verification_r02/verification.json)。

- 新規17件を含む**関連393テストPASS**、failure/error/skipとも0。今回は既存の関連試験も再実行した。
- L読込みの状態/世代/hashの不一致、500 ms超、画像/結果の対応違い、NaN/無限大/不正な数値、物理承認flag、支持点不一致を保留する。
- 仮想GUI経路で、機能OFFは720行、ONは980行になることを確認。Sで保存関数へ渡るのが表示キャンバスではなく元の`NativeFrame`であることも確認した。実ウィンドウ/カメラ/ソケット/CUDAは起動していない。
- [手順2](../fixed_floor_lifecycle_replay_r01/README.md)の合成180行で、比較数値88行が表示対象になることを確認。実ログ1,689行の別session拒否は、表示側でも数値0行。
- 元の距離/支持点/scene/worker/校正/RTC/FFBの実装は前段から未変更。変更は`src/run_cone_distance_live.py`のGUI合成呼出しと、新規`src/cone_fixed_floor_display.py`のみ。

追加パネルのローカルCPU描画コストは合成入力60試行で中央値約1.90 ms、p95約2.57 ms（`synthetic_cpu_render_cost.csv`）。このPC上の参考値であり、学校GPU PCのFPSや映像/画面遅延の実測ではない。

`source_snapshot/run_cone_distance_live.py`にGUI変更前を保存した。過去のmanifestは書き換えず、意図したGUI変更前のhashはsnapshotに照合している。`verification_r01`は392テスト成功後、検証器が相対パスを正規化せず2件の旧hash照合に失敗した版。検証器を修正し、記録表示の状態引継ぎテストも加えたr02を正式版とする。

再現コマンドは新しい出力先を指定する。

```bash
cd /home/robo25/theta_ws/RICHO-theta
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-11-02/fixed_floor_display_r01/verify.py \
  --output-dir "Experimental_results/2026-11-02/fixed_floor_display_r01/verification_$(date +%Y%m%d_%H%M%S)"
```

## 実機で使うとき

GPU/ハンコンPC（hsr）で[床モデル導出・L読込みの手順](../fixed_floor_derivation_r01/README.md)を実行すると、受信画面に比較パネルが付く。カメラ送信側matunucのコマンドは変更なし。今この解析PCで実カメラの起動コマンドを打つ必要はない。

今回は表示準備まで。モデルを導出したsession `15ae...`の後続実画像/観測ログがないため、**その実モデルでの数値の継続出力は依然として未確認**。表示できることを精度確認やFFB接続の許可と混同しない。

撮影、学校PCの操作、GPU推論、ROS/FFB、依存追加、Git commit/pushは実施していない。別作業中の赤のみ評価も未変更。
