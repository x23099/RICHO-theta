# 2026-11-02 代表資料

今日は新規撮影なし。数値グラフ2点、既存の無加工カメラ画像1点、明示した合成GUI例1点を保存した。**合成例を実機の成功画像として使わない。** 4点とも出典ファイルをバイト同一で複製している。

| ファイル | 出典・用途 | 読み方の制限 |
| --- | --- | --- |
| [01_recorded_range_timeline.png](01_recorded_range_timeline.png) | [連続再生](../fixed_floor_contiguous_replay_r01/README.md)、`results_r02/conditional_range_timeline.png` | 10/15の実録画を11/2に再計算。新しい実機取得や絶対精度ではない |
| [02_lifecycle_timeline.png](02_lifecycle_timeline.png) | [観測再生](../fixed_floor_lifecycle_replay_r01/README.md)、`results_r04/lifecycle_timeline.png` | 上段は実ログの別session拒否、中・下段は合成入力。範囲は信頼区間ではない |
| [03_floor_reference_original_20261030_f001655.png](03_floor_reference_original_20261030_f001655.png) | `Experimental_results/2026-10-30/floor_board_pair_r01/originals/decoded_15ae673c24484d119952ae391df611aa_f001655.png` | 10/30取得の1280×720 PNG。紙を使ったモデル導出の根拠。注釈・切抜き・縮小・色補正なし |
| [04_SYNTHETIC_comparison_panel.png](04_SYNTHETIC_comparison_panel.png) | [比較GUI](../fixed_floor_display_r01/README.md)、`verification_r02/SYNTHETIC_preview_f000015.png` | 合成図形＋保存された合成観測の再表示。実カメラ写真ではない |

グラフ1の根拠は`fixed_floor_contiguous_replay_r01/results_r02/frame_comparison.csv`と`run.py`。グラフ2は`fixed_floor_lifecycle_replay_r01/results_r04/real_wrong_session/timeline.csv`、`synthetic_lifecycle/timeline.csv`と`run.py`。GUI例は`fixed_floor_display_r01/verify.py`および`verification_r02/preview_manifest.json`から追跡できる。

SHA-256:

```text
102c2594345163883bf3475a750f6c45d34b6b52f653d24c124fda041a9f6d1c  01_recorded_range_timeline.png
8aeae7f59adc842a12cd80ec45b29ca038533daa0ab44272dc77419612baa105  02_lifecycle_timeline.png
2243e7c9873c0ccdd2950502209b9e4db5b5e04a56b356a94e30a3d21f3f45d7  03_floor_reference_original_20261030_f001655.png
f8ee86b808358fe240c92292dc0ea123a513145c70101f85dc5ff090d4cda03f  04_SYNTHETIC_comparison_panel.png
```
