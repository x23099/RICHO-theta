# 11/16：参照有効化と1／1.5／2mの表示・実測対応

**後続の全ログ照合は[こちらで完了](../body_display_range_audit_r01/README.md)。** 以下は画面受領時の観測と提出手順を残した記録で、再提出は不要。

## 確認できたこと

ユーザー提出statusではsession `e52bb32f03d6488ebf37d769f46ec37a`、state=active、error=null、reference_generation=1、reference_frame=5186、reference_scope_verified=true。frame24780では元測距・比較ともno_candidateで保留、baseline_reproduced=true。参照の読込み成功と、元候補の不在を区別する。

続く会話添付画面では、候補なしの画面と、同session短縮表示・frame28079・0.955m・body-review gen1の画面を確認した。これらは異なる時刻／位置の画面であり、frame24780との同一フレーム照合ではない。前方中央限定ROIのため、画面内にコーンが見えるだけで測距可能とは限らない。

その後、ユーザーが「カメラ直下の床上の点から、コーン台座の手前辺中央までの床面上の直線距離は1m、表示1.005m」と申告。同時提出画面にsource e52bb32f／frame34957／1.005m／receive-age16ms／body-review gen1を確認した。

続けてユーザーが同じ測定基準で依頼した1.5m／2mの画面2点を提出し、「1枚目1.5m、2枚目2.0m」と申告。画面値はそれぞれ1.480m（frame45469、receive-age32ms）、1.960m（frame46432、receive-age48ms）。いずれもsource e52bb32f／body-review gen1。3地点の表示と申告実測を以下に整理した。

| 実測距離（申告） | 表示距離（画面） | 表示−申告実測 | 相対差 | frame |
|---|---|---|---|---|
| 1.000m | 1.005m | +0.005m（+0.5cm） | +0.50% | 34957 |
| 1.500m | 1.480m | -0.020m（-2.0cm） | -1.33% | 45469 |
| 2.000m | 1.960m | -0.040m（-4.0cm） | -2.00% | 46432 |

全点参照pin5186・世代1。[observations.csv](observations.csv) に記録。今回の画面3点では絶対差最大4cmだが、全範囲の保証誤差や時系列の最大誤差ではない。遠方2点では小さめに表示されているが、3点だけから原因や補正係数を決めない。実測方法の不確かさ・表示変動の全幅は未申告であり、5mm精度や常時±4cmを認定しない。画面にはカメラ直下の水平距離・固定取付／平面床仮定・非制御／非FFBの注意書きがある。

## 根拠と未確認範囲

- ユーザーの実測申告・貼付status・会話添付スクリーンショットが根拠。スクリーンショットのローカル原本パスは今回提示されていないため、ファイル保存・SHA照合済みとは扱わない。画像を再作成・加工していない。
- [参照ファイルと原本4点の照合](../body_display_reference_r01/README.md)は別記録。今回のstatusは貼付テキストで、原本comparison_status.jsonとのバイト一致までは未検証。
- frame34957／45469／46432の主ログ・レビュー・bridgeの正確な対応は、後続の全ログ監査で全3点一致を確認済み。receive-ageは画面上の値で、露光から表示までの総遅延ではない。
- 物理精度・床接地・取付再現性・傾斜補償・制御利用の認定はしていない。参照作成後にカメラ／取付を変えていない条件での再開確認として扱う。

## 次：追加測定せず、終了後の全ログを照合

現地の3地点確認は完了。受信を通常終了し端末が戻るまで待ってから、次をGPU PCで実行する。主・比較の正常終了がそろわない場合はhelperが拒否するので、ログを共有し強制killや削除で進めない。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 Experimental_results/2026-11-14/guarded_display_operations_r01/pack_submission.py closed \
  --primary-dir Experimental_results/2026-11-16/driver_body_guard_live_r01 \
  --comparison-dir recordings/2026-11-16/body_guard_live_r01 \
  --output /home/hsr/Downloads/body_guard_full_20261116_r01.tar.xz
```

出力archiveだけを提出する。同名archiveがある場合は出力名だけr02へ変え、元の主／比較フォルダは変えない。送信側も通常終了してよい。追加の走行・測定・再pin・再load・受信再起動・画面録画は要求しない。
受領後、画面3点と完全主ログ・レビュー・bridgeの同frame対応、参照／pinの結合、終了状態を照合する。前後の数値変動は確認するが、実測に対応する静止時間区間はスクリーンショット3点だけでは確定できないため、移動中ログを静止精度評価へ混ぜない。
既存校正・閾値をこの観測へ合わせて調整せず、設定を固定して比較する。11/13の走行試験のやり直しではない。
