# 黄色コーン30枚スイート：S下限スイープの現状（2026-11-21）

## 1. 受領物

- `yellow_suite_manifest_r01.json`（30枚、ROI 270 0 350 720）
- archive 4点：s80 / s130 / s150 / s170
- 原archiveは `recordings/2026-11-21/yellow_suite_intake_r01/`

**未提出：各runの`manifest_run.json`。** そのためS値はファイル名からの推定で、archive内には記録されていません。

## 2. 結果

| run | state | 結果 |
|---|---|---|
| s80 | **failed** | `NameError: name 'colour_support' is not defined` |
| s130 | **failed** | 同上（200/600サンプルで停止） |
| s150 | **failed** | 同上（200/600サンプルで停止） |
| **s170** | **complete** | 30枚・300対、**全件数値** |

### 失敗原因（こちらの不具合）

`src/cone_upper_support_candidate.py`で黄色マスクを`colour_support.YELLOW_SATURATION_MIN`へ置換した際、**importの追加が失敗**していました。S=80/130/150ではupper完了経路に入り、その時点でNameError。S=170ではbaselineが成功してupper経路に入らず、完走しました。

修正：`import cone_colour_support_candidate as colour_support` を追加。`_upper_context`を直接呼ぶテストを追加し、同じ不具合を検出できるようにしました（[tests/test_yellow_saturation_floor.py](../../../tests/test_yellow_saturation_floor.py)、5テスト成功）。

## 3. s170の定量結果（有効なrun）

- 30/30画像で original・packet とも**数値**。gateの保留・反転は0。
- 距離は3群：約1.06 m、約1.58 m、約2.13 m（公称1.0/1.5/2.0 m）。
- 元 vs packet の差：

| 指標 | 値 |
|---|---:|
| 差が0 cm | 19 / 30 |
| \|差\| ≤ 0.5 cm | 27 / 30 |
| \|差\| ≤ 3 cm | 29 / 30 |
| 中央値 | 0.00 cm |
| 最大 | +5.15 cm（f001982） |
| 2番目 | +2.65 cm（f002519） |

- `support_pixel_changed` 170/300、`support_observation_changed` 290/300。支持点は頻繁に1 px程度動くが、距離は量子化されてほぼ一致。
- 同一画像内10反復は距離・理由とも一致。

## 4. 判断

- **黄色コーンはS≥170で安定して数値化できる**（このシーン・この照明）。赤で起きたgate反転は発生していない。
- ただしS=170は高い。薄暗い環境ではコーンの彩度が下がり、170を下回る可能性がある。**採用閾値は「床を落とせる最小値」に近い方が安全**なので、s80/130/150を修正後に再実行して比較する必要がある。
- s170の5.15 cm外れ値は、支持点の1〜2 px差が距離へ効いた例。閾値を下げると支持点が変わるため、外れ値の出方も変わる。

## 5. 次に必要なこと

1. 修正をGPUPCへ反映（`cone_upper_support_candidate.py`のimport追加とテスト）。
2. s80 / s130 / s150を再実行（s170は再実行不要）。
3. 各runの`manifest_run.json`も提出（`yellow_saturation_min`が記録される）。
4. 4つのrunで、数値率・距離差・外れ値・支持点の安定性を比較し、採用S下限を決める。

`controlling_distance` / `physical_metric_verified` / `floor_contact_verified` / `usable_for_ffb` はfalseのまま。
