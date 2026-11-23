# コーン距離からFFBへの接続設計 r01（2026-11-23）

## 1. 目的

実機で成立した黄色コーンの距離（`webrtc_receive_ui --motion-distance`）を、リスク勾配のFFB経路へ接続する。マッピングはB案（障害物の側で方向、勾配は大きさ）を前提とする。

## 2. 現状の分離

| 経路 | 実装 | 状態 |
|---|---|---|
| コーン距離 | `webrtc_receive_ui.py`（motion-distance、RTP入力） | ライブで数値（数値率95%） |
| FFB | `bird_eye.py`＋`collision_ffb_publisher/relay`（青い障害物） | Phase 4まで接続済み・G923実機は未確認 |
| 接続 | なし | コーン距離はFFBへ未接続 |

## 3. 必要な入力と現状

| 入力 | 現状 | 課題 |
|---|---|---|
| 距離 | `horizontal_camera_foot_range_m`（カメラ直下基準の水平距離） | base_link/接触距離ではない |
| 横位置 | **未算出** | 検出枠の中心とカメラモデルから方位を出し、距離×sin(方位)で推定する必要 |
| 速度・ヨー | telemetryの`linear_mps`/`angular_radps`、IMUヨーレート | 姿勢は記録されない。指令値ベース |
| リスク段階 | 既存のcorridor/eta評価 | コーン用に同じ式を適用 |
| 勾配 | `evaluate_candidate_steering` | 入力の(forward,left)が必要 |

## 4. 接続方式の候補

**案1：コーンUI側で完結**
- `webrtc_receive_ui`のmotion-distance結果から、横位置・速度・ヨーを使って勾配を計算し、既存のpublisher/relayへintentを出す。
- 長所：既存のFFB安全機構（期限・watchdog・単一writer）をそのまま使える。
- 短所：UIプロセスにFFB依存が増える。ROSノードとの接続方法を決める必要。

**案2：bird_eye側で購読**
- コーンUIが距離と横位置をトピックで出し、bird_eyeが既存のFFB計算に使う。
- 長所：FFB計算が1箇所に集約。
- 短所：2プロセス間の時刻対応・順序・鮮度の扱いが増える。

**推奨：案1の変形**。コーンUIで勾配まで計算し、既存のpublisherへ渡す。FFBの安全機構は変更しない。

## 5. 横位置の推定（実装課題）

**経験的校正を試作済み**（[横位置校正](../lateral_estimate_r01/README.md)）。検出枠中心xと、距離ごとの基準`cx_ref(d)`・係数`k(d)`から `left ≈ k(d)·(cx_ref(d) − cx)` とする。

- 保存9点のin-sample残差：**絶対最大22.7 mm、RMS 11.9 mm**。右側が系統的に約2 cm大きい（魚眼非対称）。
- 側の判定（±0.05 m）には十分。勾配の`left`値としては±2 cmの誤差で、方向には使えるが値の精度は未保証。
- `cx_ref(d)`と`k(d)`は校正値として固定する必要があり、取付・構図が変われば再校正。
- 次の検証：校正に使っていない横位置・距離でのout-of-sample残差、左右別係数の比較。

物理モデルではなく、この取付に対する校正である点を明記する。

## 6. マッピングとゲート

- B案：方向は`left`の符号（±0.05 m）、大きさは`risk_level`基礎値×`(1+0.6|g|)`（|g|≤0.1は変調なし）。
- `DirectionConsistency`（3連続一致）を方向に適用。`confirmed=false`は保留（前値保持しない）。
- 方向は既定で無効。実機で方向の意味を確認してから有効化する。
- `risk_level`はCLEAR/PATHで0、WARNING/CRITICALで基礎値。

## 7. 安全要件（変更しない）

- FFBは指令ではなく提示。期限・watchdog・challenge・強度上限・単一writerを維持する。
- 距離の鮮度（受信age）を超えた値は使わない。既存の0.2 s期限に従う。
- `physical_metric_verified` / `floor_contact_verified` / `usable_for_ffb` / `published_to_ros`はfalseのまま。接続だけで認定しない。
- 方向が逆に出た場合は即中止し、`constant_direction_sign`とpolicyを確認する。

## 8. 段階

1. **横位置のオフライン検証**（保存9位置のbox中心と実測25 cmの対応）。
2. **コーンUIでの勾配計算**（publishなし、ログのみ）。
3. **dry-run publisher**（G923なし、intentのログ）。
4. **G923でのB案確認**（方向と重さ）。
5. 大きさ変調の比較。

## 9. 未解決

- コーン距離はradialで、base_link前方距離ではない。勾配の`forward/left`への変換を明示する。
- コーンと青い障害物でリスク段階の意味が同じか。
- 指令yawと実ヨーの差（低速度・旋回時）。
- 横位置推定の誤差が側デッドバンドを超える場合の扱い。
