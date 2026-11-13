# 停止確認のpin取得メモ

2026-11-13。ユーザーがGPU PCで実行したstatus出力の貼付けを根拠に記録する。
元JSONファイルやPNGはまだ未提出であり、貼付けを原本JSONとして再作成しない。

| 項目 | 貼付けで確認した状態 |
|---|---|
| 比較保存先 | recordings/2026-11-13/body_guard_static_r01 |
| state / action | pinned / pin |
| session | e011664e9b994ce1b070439efa875b6a |
| pin frame | 361 |
| pin PNG SHA256 | 6e6a75523a7ba040d36229a003d87479ab38da698a785944072bf24a04012d28 |
| latest frame | 1297 |
| 原主距離 | 約1.438868m（表示可否・精度の確認ではない） |
| 参照 | generation0、reference_scope_verified=false、未load |
| 比較理由 | comparison_pin_requested |
| error / writer_done | null / false |
| offered / processed / slot上書き | 1259 / 1257 / 1 |

変更対象のdriver_guarded_comparison.py・cone_guarded_stream_comparison.py・driver_motion_process.pyの
記録SHAは現在のローカルファイルと一致した。少なくともこの3コードのGPU反映と整合する。
ただしstatusには表示ゲート有効化フラグやUI bridge・新ヘルパーのSHAがないため、
新コード一式の反映・`--motion-body-display-guard`の有効化・実画面の保留はまだ認定しない。
全ての物理検証・制御・FFB・ROS権限フラグはfalseのまま。

## 次に受け取るもの

更新中の元フォルダ全体ではなく、次を別フォルダへコピーして圧縮してもらう。

1. recordings/2026-11-13/body_guard_static_r01/decoded_e011664e9b994ce1b070439efa875b6a_f000361.png
2. 同名の.json
3. 同フォルダのcomparison_status.json
4. Experimental_results/2026-11-13/driver_body_guard_static_r01/motion_engine_summary.json

4点目で新ゲートのenabledと関連コードSHAを確認する。
PNG・復号画素・sidecar/statusのpin情報を照合し、現在PNGから境界を読んで新参照を生成する。
まだ旧r02等の参照をloadしない。送受信・現在接続を維持し、機体とカメラは停止状態のまま。
再pin・再起動・走行・追加録画は今は不要。保存時点から現在までのwitness残存は別途load時に確認する。
このターンではruntime変更・実機操作・日報・commit/pushなし。
