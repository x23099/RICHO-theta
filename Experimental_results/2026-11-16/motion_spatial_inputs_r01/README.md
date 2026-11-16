# 保存ログから床面位置を復元し、車体・運動入力への接続条件を確認

2026-11-16。**距離の受け渡しに続き、表示許可19,297点のカメラ基準床面ベクトルを復元できた。車体基準XYや実データ由来のリスク勾配へはまだ変換していない。** 距離推定の失敗や精度悪化を意味せず、異なる座標系・時計の入力を誤結合しないための切り分け。

## 実行結果

根拠: [正式監査](results_r01/audit.json)、[既知3点](results_r01/point_vectors.csv)、[検証記録](verification.json)。

| 項目 | 件数・結果 |
|---|---:|
| 同一session/frame/元時刻で主ログと受け渡しr02を照合 | 51,202 |
| 表示許可→条件付き床面ベクトルを復元 | 19,297 |
| 保留→位置もnullのまま | 31,905 |
| ベクトル長と元距離の最大差 | 1.333e-15 m未満 |
| 床面内条件の最大残差 | 3.749e-16 m未満 |
| 関連テスト | 82成功、0失敗 |

数値差は計算上の丸め誤差で、物理精度の改善や保証ではない。ユーザー実測との3地点比較は既存結果を継承し、再撮影していない。

元提出16ファイルを正式全ログ監査のSHAへ、受け渡しJSONLを正式handoff r02のSHAへ結んだ。全主行でsession/frame/受信時刻/primary model/profileの同一性を確認し、許可点の元支持画素と距離を照合。元計算・表示判定12ソースのSHAも不変。

派生全件: `recordings/2026-11-16/motion_spatial_inputs_r01/conditional_optical_vectors.jsonl`。元ログ・画像・profile・参照は変更なし。新moduleは実行UI・bridge・ROS・FFBへ未接続。

## 復元できたもの／まだできないもの

新実装: [driver_motion_spatial.py](../../../src/driver_motion_spatial.py)。光学座標はx右/y下/z光軸。単位光線r、仮定床上向きu、高さhに対し、カメラ原点からの交点は `p=h*r/(-u·r)`、カメラ直下から交点までのベクトルは `q=p+h*u`。`q·u=0`、`|q|`が既存の水平距離に一致する。

この3成分は**光学座標で表した水平ベクトル**で、光学yが0である必要はない。車体前後左右ではない。元の仮定床法線・高さ・現在支持画素に依存し、床接地や取付再現性は未認定。保留を幾何計算で救済しない。

車体↔光学の剛体変換を `(R,t)` と定義できれば `p_vehicle=R*(q-h*u)+t` と接続できる。直下点も `t-h*R*u` として変換する。**光学原点とカメラ直下原点を混同しない。** 床法線は車体の水平面内の向きを決めず、距離は車体までの空き距離でもない。合成単体テストは、同じ床法線・距離でも前方0.8mと左0.8mの両方の車体座標解が可能であることを示す。どちらも実機に採用していない。

既存の紙基準profileは `arbitrary_metric_board_NOT_vehicle_or_base_link`。表示用UIの高さ/pitch/offset既定値や `bird_eye.py` の車幅既定値0.354mも存在するが、今回の取付・native光線・車体基準との整合性を認定する資料ではない。値を暗黙採用しない。

## 運動情報と時計の確認

提出16ファイルのJSON/JSONLフィールドを全件確認した範囲では、`linear_x` / `angular_z` / `imu_yaw_rate` / odometry / ROS header / 車幅 / 車体↔光学変換は記録されていない。照会キーと全フィールド一覧は正式監査内。**現地PCに別のrosbag等がないという主張ではない。**

- [webrtc_stream.py:79](../../../src/webrtc_stream.py#L79): odometryの速度/ヨーを保持するが、元header時刻や受信済み状態を保持していない。初期0と実測0を現在の辞書だけでは区別できない。
- [webrtc_stream.py:114](../../../src/webrtc_stream.py#L114): 値をtelemetryへ載せる。最後の値の保持だけでは元計測の鮮度は分からない。
- [webrtc_stream.py:385](../../../src/webrtc_stream.py#L385): `timestamp` は送信時PCのwall clockで、ROSメッセージ元計測時刻ではない。
- [webrtc_receive_ui.py:2080](../../../src/webrtc_receive_ui.py#L2080): telemetryをUIへ通知する。今回の測距用保存経路へ時刻付き運動レコードを追記する実装ではない。
- [webrtc_receive_ui.py:2107](../../../src/webrtc_receive_ui.py#L2107): 距離の元時計は受信側monotonic。動画露光時刻・送信PC wall clock・ROS時刻と同一視できない。
- [webrtc_receive_ui.py:352](../../../src/webrtc_receive_ui.py#L352): 既存の表示経路予測は指令値優先。指令を測定車速/ヨーの代わりに無断で使わない。
- [collision_risk.py:486](../../../src/collision_risk.py#L486): 既存勾配評価の入口は車体前方/左方向位置、v、ω、車幅。同じスナップショットを3経路へ使う。

## 次に進めること

まずローカルで**時刻・有効性付きの運動情報の保存/結合形式**を準備し、未受信・古い値・時計不明・欠落時には結合しないことを合成データで検証する。ROSの配信・操縦・FFB出力は変更しない。GPU反映・追加撮影は今回不要。

実データの結合前に必要な情報は次の3つ。既存資料・既存rosbagがあれば先に利用し、同じコーン撮影のやり直しは求めない。

1. 現取付の車体↔光学の向き・並進、車体基準原点と左右定義、根拠と適用session。再取付やpitch/roll変化を無条件で同一としない。
2. 符号付き実測v/ω、計測元・元計測時刻・受信時刻・有効性、受信monotonicへの時計対応と誤差/遅延の扱い。受信時刻の近接だけで露光同時刻とは認定しない。
3. 車幅の意味と値、障害物点（観測支持点/近辺中央/物体の広がり）の意味。単一点を物体全体や追跡IDへ自動昇格しない。

結合の時間許容差・FFB用期限は未選定。測距の0.5秒をそのままFFBの100ms要件へ流用せず、今の履歴データを現在時刻で再包装して実出力に使わない。既存FFBの期限/challenge/watchdog/方向ゲート/単一writerは維持する。

## 再現

このPC用。生出力・集計フォルダは未使用名へ変更してから実行する。同名出力への上書きは拒否する。

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/motion_spatial_inputs_r01/audit.py \
  --audit Experimental_results/2026-11-16/body_display_range_audit_r01/results_r01/audit.json \
  --handoff-audit Experimental_results/2026-11-16/motion_range_handoff_r01/results_r02/audit.json \
  --intake-dir recordings/2026-11-16/body_display_full_intake_r02 \
  --raw-output-dir recordings/2026-11-16/motion_spatial_inputs_r02 \
  --output-dir Experimental_results/2026-11-16/motion_spatial_inputs_r01/results_r02

env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q \
  tests/test_driver_motion_spatial.py tests/test_driver_motion_handoff.py \
  tests/test_angular_fisheye_geometry.py tests/test_cone_motion_range.py tests/test_range_sensitivity.py
```

この結果は接続前の保存ログ検証。ROS伝送、実運動同期、物理接触、車体座標、実勾配、G923出力の動作確認ではない。全制御/FFB認定フラグfalseを維持。
