# 3地点の測距感度と、診断表示の利用条件

## 結論

保存済みの支持点から元の主モデル距離を再計算し、3点すべてが記録値に1e-12m以内で一致した。距離計算と表示の対応に不整合は見つからなかった。
一方、2m地点では支持点yの1px差で最大約3.90cm、高さ1cm差で約3.40cm、対象方向の床法線1度差で最大約13.42cmの距離変化が生じる。**遠方ほど画素・取付・床方向の影響が大きい。**
これは現行モデルの感度であって、今回の差の原因特定、実際の取付誤差の測定、誤差保証ではない。3地点へ合う補正値は作らず、runtime・profile・しきい値を変更していない。

## 1条件だけ変えた計算

| 申告実測地点 | 支持点x±1pxの最大絶対変化 | 支持点y±1px | 高さ±1cm | 対象方向の法線±1度 |
|---|---|---|---|---|
| 1.0m | 0.043cm | 1.26cm | 1.74cm | 4.19cm |
| 1.5m | 0.067cm | 2.36cm | 2.57cm | 8.00cm |
| 2.0m | 0.108cm | 3.90cm | 3.40cm | 13.42cm |

各列は個別に他の入力を固定した計算で、足し合わせた誤差帯ではない。正負の効果は必ずしも対称ではなく、表は両側の最大絶対値。生の正負差は [scenarios.csv](results_r01/scenarios.csv)、入力・コードSHAと結果は [sensitivity.json](results_r01/sensitivity.json)。3点×9ケース＝27件。

- 基準支持点：frame34957=(311,417)、45469=(313,389)、46432=(311,373)。すべてnative1280×720。
- 元モデルippe_0の高さは0.5767672744708221m。これは記録profile値であり、今日の実測取付高さではない。
- 法線は各対象の光線と法線が作る平面で回転した。対象ごとの感度方向なので、同一の車体pitch/roll変化を3地点へ与えた計算ではない。
- 画素移動は仮想入力であり、実画像から別の接地点を検出したものではない。
- 高さ±1cm、法線±1度は検討用の仮定で、実測された不確かさや信頼区間ではない。

距離式は [現行horizontal_range](../../../src/cone_motion_range.py:92) と同じ。別途、水平距離 `h / tan(俯角)` による数式対照、高さの線形性、法線の単位長をテストした。
計算再現の1e-12m許容は浮動小数点比較のためであり、物理測距精度ではない。実ログと先行監査に記録された元値は完全一致を要求したまま、幾何再計算では最大4.45e-16mの丸め差を許容した。初回試行は幾何再計算値にまで完全一致を課した条件で止まったが、入力データの不整合ではなかった。

## 今、使える範囲

[利用条件と次段階](operating_scope.md) に確認済みと未確認を分離した。現在の判断は「前方中央の実験的な運転者向け診断表示として使用を進める」であり、距離を制御・FFB・停止判断へ自動接続することではない。
11/13の走行中表示／自己遮蔽保留／復帰と、11/16の再接続・3地点の画面値一致をそれぞれの条件の実績として保持する。静止3点の誤差を走行全体へ転用しない。

次に優先するソフトウェア改善は、狭い対象範囲と保留理由を運転者へ明示すること。今回「画面にはコーンがあるがno_candidate」になったことに直接対応する。数値を出す範囲やしきい値を緩める修正とは分け、保留・元値・非制御属性を維持する。後続で[UI説明改善を実装済み](../motion_panel_guidance_r01/README.md)だが、GPU PC反映・実画面確認はまだ未実施。
物理精度をさらに認定する場合には、必要な精度を決めた上で、再取付／傾斜／支持点のどれを独立確認すべきかを選ぶ。今回の感度計算だけを根拠に追加撮影・走行を依頼しない。

## 再現・検証

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/range_sensitivity_r01/analyze.py \
  --audit Experimental_results/2026-11-16/body_display_range_audit_r01/results_r01/audit.json \
  --intake-dir recordings/2026-11-16/body_display_full_intake_r02 \
  --output-dir Experimental_results/2026-11-16/range_sensitivity_r01/results_r02
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q \
  tests/test_range_sensitivity.py tests/test_body_display_range_audit.py \
  tests/test_cone_motion_range.py tests/test_driver_body_display_guard.py
```

検証は [verification.json](verification.json)。新規10テスト＋関連計69件成功。前段階67件などと重複があるため独立件数へ合算しない。
元主JSONL全体SHA、対象3フレームの完全元行SHA、保存profile、カメラ／設定、先行監査、使用コードのSHAを保存。出力は新規ディレクトリ限定で、原本・画像・profileを変更しない。カメラ／CUDA／ROS／実機を起動せず、日報・commit/pushも今回未依頼。
