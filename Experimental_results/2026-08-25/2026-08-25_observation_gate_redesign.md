# 2026年8月25日 観測ゲート再設計候補のオフライン評価

## 1. 結論

左右非対称には、輪郭面積を補正前のカメラ幾何上の地面斜距離で正規化する方式が有効だった。
しきい値`2000`、NIS`9.210`、2フレーム確認を組み合わせると、既存の前後距離`z`方式が
25セッション中20セッション合格だったのに対し、補正前斜距離方式は24セッション合格した。
新位置の左4試行はすべて回復し、既存の3距離遮蔽6イベントも結果を維持した。

残る1セッションは、暗く輪郭が分断した新位置`z=0.8 m`遮蔽録画である。HSV明度下限を
`V=30`から下げると新録画は回復したが、旧録画が回帰した。新旧双方を満たす固定下限は
`V=20..30`に存在しなかったため、固定値の微調整は採用しない。

以上から、次候補は次の2段階とする。

1. 面積正規化は`raw_ground_distance`を採用候補とする。
2. 色抽出は露出固定、色恒常化、または局所照明へ適応する方式を別途比較する。

同じ録画を方式選定に使ったため、現行設定はまだ変更しない。候補を確定するには別の新規holdoutが
必要である。

## 2. 既存手法の確認

OpenCVの`inRange`はHSV各成分の固定上下限で画素を二値化する方式であり、Vは明るさ・強度を表す。
したがって現行の`V>=30`は、影で暗くなった青画素を直接失う構造である。

魚眼画像は画面位置に応じた投影を持つため、物体の見かけ面積を前後成分`z`だけで補正すると、
横位置と距離校正誤差が面積品質へ混入する。OpenCVも通常カメラとは別に魚眼カメラモデルと
校正APIを定義している。本件では新しい多項式モデルを先に導入せず、既に計算済みの床面斜距離を
使う低コストな補正から比較した。

照明変化への既存手法としてGray-World、Max-RGB、Shades-of-Gray等の色恒常化がある。
Shades-of-Grayはシーン統計から照明色を推定するが、シーン平均等への仮定があり、局所的な影を
必ず補償できるわけではない。このため本番経路へ直ちに入れず、新旧録画での比較が必要である。

参考:

- [OpenCV: Thresholding Operations using inRange](https://docs.opencv.org/5.0/tutorials/imgproc/threshold_inRange/threshold_inRange.html)
- [OpenCV: Fisheye camera model](https://docs.opencv.org/4.7.0/db/d58/group__calib3d__fisheye.html)
- [Finlayson and Trezzi, Shades of Gray and Colour Constancy](https://library.imaging.org/admin/apis/public/api/ist/website/downloadArticle/cic/12/1/art00008)

## 3. 面積正規化座標の比較

### 3.1 比較方式

各セッションの安定位置を追跡予測の代理とし、次の3方式を同一しきい値で比較した。

```text
forward_z                  = area_px * predicted_z^2
calibrated_ground_distance = area_px * hypot(predicted_x, predicted_z)^2
raw_ground_distance        = area_px * raw_ground_distance^2
```

`raw_ground_distance`では、追跡初期化後は補正済み予測`x`を横方向affine補正の逆変換でカメラ幾何座標へ
戻して斜距離を計算する。現在の異常観測自身の距離は使わないため、異常値が自分の面積スコアを
水増しできない。

### 3.2 複合ゲート再生結果

しきい値`2000`、NIS`9.210`、2フレーム確認で25セッションを再生した。

| 正規化座標 | 合格セッション | 主な不合格 |
|---|---:|---|
| 前後距離`z` | 20/25 | 新位置左4本、新位置0.8 m遮蔽 |
| 補正後斜距離 | 21/25 | 新位置左3本、新位置0.8 m遮蔽 |
| 補正前斜距離 | 24/25 | 新位置0.8 m遮蔽のみ |

補正前斜距離方式では、旧3距離遮蔽の正常採用率98.3～99.4%、外れ値棄却率100%、解除・再捕捉
6/6を維持した。新位置の1.0/1.3 m遮蔽も正常採用率99.7%、外れ値棄却率100%、解除・再捕捉
4/4を維持した。

## 4. HSV明度下限の感度

### 4.1 新位置録画

補正前斜距離、面積しきい値`2000`との組合せで、2026年8月25日の録画を全フレーム再処理した。

| V下限 | 0.8 m遮蔽 | 1.0 m遮蔽 | 1.3 m遮蔽 | 備考 |
|---:|---|---|---|---|
| 10 | PASS | FAIL | PASS | 1.0 mで追跡解除1/2 |
| 20 | PASS | PASS | PASS | 3距離6イベント合格 |
| 25 | FAIL | PASS | PASS | 0.8 m正常採用率91.2% |
| 30 | FAIL | PASS | PASS | 0.8 m正常採用率0%、再捕捉0/2 |

箱なし録画は全しきい値で背景の青候補を853/853フレーム拾った。これは既定`V=30`でも存在する
問題である。候補面積ゲートによる観測採用と追跡は全しきい値で0だったが、厳密な生検出0条件は
満たしていない。

### 4.2 旧位置録画への回帰

旧3距離遮蔽へ`V=20`を適用すると、0.8/1.0 mは合格したが、1.3 mは正常採用率96.8%、
最大`abs(vz)=0.336 m/s`で不合格となった。`V=21..24`でも旧1.3 mの正常採用率は
87.1～96.8%で、すべて98%条件を下回った。一方、旧1.3 mが合格する`V=30`では新0.8 mが
不合格である。

明度下限を下げると単純に同一輪郭が広がるのではなく、別の暗い青領域との結合や最大輪郭の切替が
起きる。このため固定V下限の微調整では新旧環境を両立できない。

## 5. 実装状態

- `ObstacleObservationGate.filter_measurement()`へ、前後距離以外の面積正規化距離を明示的に渡せる
  後方互換APIを追加した。
- `bird_eye.py`から`forward_z`、`calibrated_ground_distance`、`raw_ground_distance`を選べるようにした。
- HSVのH/S/V上下限をパラメータ化し、V下限のオフライン感度分析を再現可能にした。
- `detections.csv`へ実際に使った`normalization_distance_m`を追加した。
- 現行設定は`forward_z`、`V=30`のままであり、候補を有効化していない。
- 設定値の列挙範囲とHSV V範囲をpreflightで検査する。

## 6. 次の作業

1. 新旧録画でGray-World/Shades-of-Gray等の色恒常化、局所明度適応、カメラ露出固定を比較する。
2. 箱なし背景の青候補を、校正範囲以外でも抑える画像特徴または背景条件を調べる。
3. `raw_ground_distance`と選定した色抽出方式を開発設定で短時間確認する。
4. 方式としきい値を固定し、今回の録画を使わない新規holdoutで最終判定する。
5. `x=±0.40 m`が約`±0.30 m`に推定される横位置校正誤差は、観測品質ゲートと分離して再校正する。

## 7. 成果物

- `2026-08-25_area_normalization_mode_comparison.csv`
- `2026-08-25_area_normalization_combined_replay.csv`
- `2026-08-25_hsv_value_threshold_sensitivity.csv`
- `2026-08-25_hsv_value_threshold_old_occlusion_regression.csv`
- `2026-08-25_hsv_value_threshold_boundary_new.csv`
- `2026-08-25_hsv_value_threshold_boundary_old.csv`
