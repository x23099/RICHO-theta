# 2026-11-13 代表資料4点

本日の到達点である「走行中の数値→台座遮蔽による表示保留→後退後の復帰」を示す。
元録画は `Screencast from 2026年11月13日 20時27分27秒.webm`、約60.290秒、1920×1200。
詳細な根拠は [走行監査](../body_display_occlusion_live_audit_r01/README.md) と同フォルダのCSV／JSONにある。

| ファイル | 元の対応 | 用途 |
|---|---|---|
| [推移図](body_guard_display_timeline.svg) | screen_window.csv／plot.pyから生成 | 元値は残るが表示許可が途切れる区間を可視化 |
| [遮蔽前](body_guard_forward_numeric.png) | PTS15.001秒、frame50114、1.533m | 現参照での数値表示 |
| [遮蔽保留](body_guard_occluded_withheld.png) | PTS35.013秒、WITHHELD／possible_self_body_occlusion | 台座が隠れた状態の実画面。UIにframe表示はない |
| [復帰後](body_guard_reverse_numeric.png) | PTS55.007秒、frame51315、1.538m | 後退後の数値復帰 |

PNG3点は、既存抽出スクリプトが保存した原解像度画面の**バイト一致コピー**。
切抜き・リサイズ・注釈・合成・色補正はしていない。運転画面が元から持つ表示もそのまま保持した。
保留時の画面に表示されないframe番号を追加・推定描画していない。
SVGはカメラ画像ではなく数値だけのグラフで、根拠CSV・生成コードへ追跡できる。

`build_assets.py` が4点をコピーし、[manifest.json](manifest.json) に入力／出力SHA・元録画SHA・PTS・読取り値を保存する。
再生成は新規出力ファイル専用。同名ファイルを削除・上書きして作り直さない。
元webm・全ログ・全抽出画像群はGit対象外の `recordings/2026-11-13/body_display_occlusion_full_intake_r01` に保持する。

終業時の再検証は [checks_r01/summary.json](checks_r01/summary.json) と [tests.log](checks_r01/tests.log)。対象9ファイルの108テスト成功、代表4点のバイト一致と日報関連45リンクを確認した。実カメラ・CUDA・ROS・車体を起動した試験ではない。
