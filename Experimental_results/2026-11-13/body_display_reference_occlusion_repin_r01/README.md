# 遮蔽試験・再pin17327：参照作成済み、次はSHA照合→load

2026-11-13 JST。提出 `body_guard_occlusion_repin_r01.tar.xz` の4点は完備。
現在画像を確認し、**session 24e1146277d043fa8c01d36e2ebe0651／frame17327専用**の [reference.json](reference.json) を作成した。旧pin1677や別sessionの参照ではない。

## コピー・load

このPCの本フォルダにある `reference.json` を、GPU PCの次のファイルへコピーする。

`/home/hsr/yopi_ws/RICHO-theta/recordings/2026-11-13/body_guard_occlusion_r01/reference.json`

新規の参照ファイルなので、現時点ではPullだけでは届かない。旧パッチの再適用は不要。
ファイル名は `reference.json` のまま。受信・送信・車体停止と現在のコーン位置を維持し、新pin・再起動・Lキーは使わない。

GPU PCでSHAを確認：

```bash
cd /home/hsr/yopi_ws/RICHO-theta
sha256sum recordings/2026-11-13/body_guard_occlusion_r01/reference.json
```

正しいSHA：

`2b75af07233ad001628e3be8277a8e0c90818acad2c78a56b24067fee5032f87`

一致した場合だけ、1回load：

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/body_guard_occlusion_r01 load
```

数秒後：

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/body_guard_occlusion_r01 status
```

このstatusと画面下部の距離欄を共有する。まだコーンを動かさない。
確認したいのは `state=active`、同session、`latest.reference_frame=17327`、`latest.reference_scope_verified=true` と、画面下部の数値＋ `body-review gen`。
generationは初回loadなら1を想定するが、数字だけで有効と判定しない。

`load_rejected`／失効／WITHHELD継続の場合は理由をそのまま共有する。load連打やsession書換えでの復旧はしない。
画像確認時点で妥当でも、コピー後からloadまでの接続・witness保持はこのPCから保証できず、実際のloadで検証される。

## 次の試験（loadと表示復帰を確認してから）

[遮蔽・復帰の手順6〜7](../body_display_occlusion_live_r01/README.md)へ進む。
車体は停止のまま、録画中表示を確認して「見える位置の数値→コーンを床上で近づけ台座が隠れる位置の保留→戻した位置の数値復帰」を各約5秒ずつ記録する。
安全に置ける範囲で台座が隠れない場合は無理をせず、接触・持ち上げ・カメラ操作はしない。
`no_candidate`／ROI端等だけの保留は自己遮蔽ゲート成立とは分けて解析する。終了後は主／比較フォルダ全体＋画面録画を提出する。

## 4点の照合と新しい境界

- 原本：`recordings/2026-11-13/body_display_occlusion_repin_intake_r01`。元PNGの画角／1280×720解像度を維持し、一切加工していない。
- 最新pin17327だけのPNG／同名JSONが含まれ、旧pin1677は今回の圧縮に混在していない。
- PNG SHA／復号BGR SHA／sidecar／status内pin一致。コピー時はpinned、saved2、writer_done=false、error=null、latest30613。
- latest.reason=`comparison_pin_requested`。コピー時点で継続不確実のフラグはfalse。前回のinput_gapは今回のstatusには出ていない。pinからlatestまで約442.916秒だが、秒数が経っただけでpinを失効扱いしない。
- 表示ゲートON、元主結果非変更、棄却専用をengine summaryで確認。比較9＋表示7コードの記録SHAがローカルと一致（重複を除く12コード）、profile/config・記録重みSHAも一致。checkpoint本体の再hashは未実施。
- 現在のPNGを新規に見て、局所天板境界x270〜380、中央y450付近を [reviewed_boundary.csv](reviewed_boundary.csv) に記録。画素の明暗遷移も数値で確認した。x300〜340の黄色テープ部分は両端の見える境界から補間する。読取り目安2pxは精度の信頼区間ではない。
- 旧静止pin361の中央y455付近とは異なるため、旧境界座標を流用していない。ただし画像上の差だけでカメラ姿勢変化量や物理誤差は断定しない。新参照は自己遮蔽の表示棄却用で、床法線・高さ・距離精度の校正ではない。

根拠は [intake audit](results_r01/audit.json) と [reference validation](reference_validation.json)。元主JSONLが未提出のため、pinの完全元行SHAは終了後の全ログで照合する。現在までの実GUI・新参照load成功・遮蔽時の表示切替は未確認。

## 再現・検証範囲

本成果物は既存の4点intakeと参照生成器を再利用した。新規保存先を使う場合のコマンド：

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/body_display_reference_static_r01/intake.py \
  --archive /home/robo25/Downloads/body_guard_occlusion_repin_r01.tar.xz \
  --archive-prefix body_guard_occlusion_repin_submit_r01 \
  --intake-dir recordings/2026-11-13/body_display_occlusion_repin_intake_r02 \
  --output-dir Experimental_results/2026-11-13/body_display_reference_occlusion_repin_r02/results_r01
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/guarded_static_reference_r02/build_reference.py \
  --input-dir recordings/2026-11-13/body_display_occlusion_repin_intake_r02 \
  --audit Experimental_results/2026-11-13/body_display_reference_occlusion_repin_r02/results_r01/audit.json \
  --boundary-csv Experimental_results/2026-11-13/body_display_reference_occlusion_repin_r01/reviewed_boundary.csv \
  --output-dir Experimental_results/2026-11-13/body_display_reference_occlusion_repin_r02
```

関連60テストは前段階で成功済みで、今回intake／生成器のコード変更はない。今回の実入力についても4点照合と参照生成が成功し、入力SHA／生成物SHA／session・pin・PNGの結び付きを再確認した。
runtime・閾値・校正・GPU環境の変更なし。このPCから実カメラ・CUDA・ROS・車体は起動していない。診断値は非制御／非ROS／非FFBのまま。日報・commit/pushは今回未依頼。
