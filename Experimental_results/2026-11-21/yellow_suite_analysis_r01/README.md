# 黄色コーン30枚スイート：S下限スイープ結果（2026-11-21）

## 1. 入力と来歴

- 同じ30 frame（session `5d142cea522045c283e7136ab83cb460`、ROI 270 0 350 720）。
- S下限だけを変えた4run。`manifest_run.json`の`yellow_saturation_min`で確認済み（80 / 130 / 150 / 170）。
- archiveとmanifest_runは `recordings/2026-11-21/yellow_suite_intake_r02/`。

## 2. 結果

| S下限 | state | 両方数値 | gate反転 | 元のみ保留 / packetのみ保留 | 差0 cm | \|差\|≤3 cm | 差の中央値 | 最大\|差\| |
|---:|---|---:|---:|---|---:|---:|---:|---:|
| 80（現行） | complete | **4 / 30** | 4 | 23 / 25 | 1 | 3 | −0.08 cm | 5.02 cm |
| 130 | complete | 22 / 30 | 2 | 6 / 8 | 4 | 22 | −0.08 cm | **0.49 cm** |
| 150 | complete | 23 / 30 | 7 | 0 / 7 | 12 | 22 | 0.00 cm | 5.15 cm |
| **170** | complete | **30 / 30** | **0** | 0 / 0 | 13 | 29 | **0.00 cm** | 5.15 cm |

- S=80では30枚中26枚が保留。床のベージュが黄色maskに入り、支持成分がcrop端に接するため。
- S=130/150では保留が大きく減るが、packet側の完了context（pad 8/10）がまだ`colour_contour_reaches_roi_edge`で拒否される例が残る。
- **S=170では30枚すべて数値、gate反転0。**

### 保留の内訳（S=80/130/150）

| S | 主な理由 |
|---:|---|
| 80 | `completed_point_outside_original_bbox`、`context_rejected:colour_contour_reaches_roi_edge`、`not_lateral_only_contact` |
| 130 | `context_rejected:colour_contour_reaches_roi_edge`（元6枚・packet8枚） |
| 150 | 同理由（packet7枚） |
| 170 | なし |

## 3. 距離差の外れ値

S=150/170の最大差5.15 cmは同一frame **f001982**。

| 項目 | 値 |
|---|---:|
| 元画像 | 1.5295 m |
| packet | 1.5810 m |
| 同距離帯の他frame | 約1.5818 m |

**外れ値はpacketではなく元画像側**（元が約5 cm近い）。packetは同距離帯の他frameと一致している。したがって「VP8が5 cmずらした」のではなく、元画像の支持点がこの1枚でずれた例として扱う。

## 4. 判断

**このシーンではS=170を採用候補とする。**

理由：
- 30/30で数値が出て、gate反転がない（FFBへ連続的に渡せる）。
- 距離差は中央値0、29/30が3 cm以内。
- 床のS最大は約104、コーンのSは235〜255。170は両者から十分離れている。

条件・注意：
- **照明が暗い場所ではコーンのSが下がる**。170を下回ると同じ保留に戻るため、別照明で再確認が必要。
- S=130は距離差が最も小さい（最大0.49 cm）が、8/30が保留。連続性を優先するなら170。
- 赤コーンは別のHSV範囲なので、この変更の影響を受けない（既定80は不変、`--yellow-s-min`は実験用の上書き）。

## 5. 失敗したrun（r01）と修正

s80/130/150のr01は`NameError: name 'colour_support' is not defined`でfailed。`src/cone_upper_support_candidate.py`のimport追加漏れが原因。修正済みで、`_upper_context`を直接呼ぶテストを追加した（[tests/test_yellow_saturation_floor.py](../../../tests/test_yellow_saturation_floor.py)）。r02はすべてcomplete。

## 6. 次

1. S=170で、**別の照明・距離**のフレームを数枚だけ確認（同じ30枚スイートでなくてよい）。
2. 問題なければ、黄色の既定S下限を170へ上げる設計変更を、赤を含む回帰テストとセットで提案。
3. それまでは`--yellow-s-min 170`の実験用上書きで運用し、既定80は変えない。

`controlling_distance` / `physical_metric_verified` / `floor_contact_verified` / `usable_for_ffb`はfalseのまま。

## 7. 距離を変えた追加確認（約2.7 m、10 frame）

同じコーン・同じ床で、距離だけ約2.7 mへ変えた10 frameをS=80とS=170で比較した。

| S下限 | 両方数値 | gate反転 | 差の中央値 | 最大\|差\| | 元の距離 |
|---:|---:|---:|---:|---:|---|
| 80 | 9 / 10 | 0 | −0.20 cm | 0.20 cm | 2.6905〜2.6945 m |
| **170** | **10 / 10** | **0** | 0.00 cm | 0.21 cm | 2.6986 m（全frame同一） |

- 2.7 mではS=80でもほぼ通る。**Sの差が効くのは近距離（1.0〜2.0 m）**で、コーンがcropを埋めて床と連結する場合。
- S=170は2.7 mでも10/10・反転0で、距離による破綻は見られない。
- これは**距離（スケール）の確認**であり、別の床・別のコーン・色かぶりの確認ではない。

原archive：`recordings/2026-11-21/yellow_suite_intake_r02/yellow_lighting_check_s{80,170}_20261121_r01.tar.xz`。
