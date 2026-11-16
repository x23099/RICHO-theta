# 研究の最終目標と現在の測距作業

更新日: 2026-11-16。ユーザー指定の最終目標は、単純な距離通知ではなく、**差動2輪ロボットの遠隔操縦で、操舵入力に対する衝突リスクの勾配をG923へ抵抗型の力覚として提示すること**。

## 最終目標

- 左右の回避余裕の差を、同一スナップショットの `ω−Δ / ω / ω+Δ` の経路評価から求める。
- 危険側への操作を重くする。安全側へ操舵を誘導するトルクは出さず、操縦者が手動権を保持する。
- FFBなし／大きさのみ／大きさ＋勾配を比較し、危険方向への操作率等で評価する。
- 期限・watchdog・challenge・有限effect・強度上限・方向ゲート・単一writerは安全要件であり省略しない。

目標の根拠はユーザー指定の以下の計画書。別リポジトリの原本は今回変更していない。

`/home/robo25/FFB_feedback_control/FFB_feedback_control/docs/2026-10-21_risk_gradient_ffb_plan.md`

読取り時SHA256: `331dbab8c3879f443f49202334de5517df204820f113f8fab5cb8cfd175088ab`。
原本の11/13更新にはPhase 1〜4実装・synthetic/replay dry-run成功、実カメラ／G923確認は未実施と記載されている。これは原本の報告であり、今回新たに全段階を再検証したという意味ではない。

## 距離計算の位置付け

現在のコーン測距はG923への接近情報・リスク評価の入力を準備する中間段階。これまでの校正、走行時の表示、自己遮蔽保留、遅延、実測3地点の検証はそのまま利用する。途中成果を破棄したり同じ撮影をやり直したりしない。
ただし、現在の値は**カメラ直下基準の水平距離**で、車体接触距離・車体座標の前後左右位置・対象追跡IDではない。スカラー距離だけから `obstacle_forward_m`／`obstacle_left_m`／左右の勾配を捏造しない。
既存の `collision_risk.evaluate_candidate_steering()` には車体基準の障害物位置、車速・ヨー入力、車幅が必要。この対応と同時刻性の確認を経て、実カメラ由来のデータを既存FFB経路へ接続する。

## 現在の作業範囲

1. 保存ログで距離・有効／保留・元時刻・session/frameの受け渡しを検証する。
2. その後、車体座標・対象対応・運動情報との結合条件を設計する。現在の測距値を無条件に既存の有効トラックへ昇格しない。
3. ROS接続・FFB dry-run・G923実出力は段階を分ける。今回の依頼は1までで、ROS送信やG923出力の起動は含まない。

当面の `physical_metric_verified=false`、`floor_contact_verified=false`、`controlling_distance=false`、`usable_for_ffb=false` は維持する。最終目標の更新は、現在値の物理精度や出力権限を自動認定することではない。

本日の根拠は [全ログ監査](Experimental_results/2026-11-16/body_display_range_audit_r01/README.md)、[感度](Experimental_results/2026-11-16/range_sensitivity_r01/README.md)、[受け渡し検証](Experimental_results/2026-11-16/motion_range_handoff_r01/README.md)。
