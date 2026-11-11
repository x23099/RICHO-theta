# 比較専用worker接続・実カメラ確認前までの計画

2026-11-11。前日commit `49f5c40` の参照管理prototypeを、既存主測距の後段へ既定OFFで接続する。主測距・操縦・ROS・FFBの値やIPCは変更しない。別作業collision_risk.py／test_collision_gradient.pyは対象外。

1. 容量1の最新slotを持つdaemon workerをGPU子プロセス内に置く。主結果のpipe送信後に、不変の元画像とJSONL文字列だけをnon-blockingで渡す。比較・hash・PNG・ファイル読込みはworkerで行う。CPU/GIL/メモリは共有するため実GPU負荷は別確認が必要。
2. `--motion-comparison-dir` の明示指定時のみ起動。新規recordings配下へ比較JSONL、状態、明示snapshotを保存する。ログ容量、画像8枚、要求数、行容量、終了待ちを制限し、例外や上限では比較側だけを停止する。
3. local requestファイルによるpin／load／invalidateと、要求を発行・状態確認する端末コマンドを用意。勝手に画像を撮り溜めず、pin要求後の処理対象1枚だけを保存。loadでは同じ接続内でpinした元PNG／画素を照合し、読込み完了後に受信したframeだけに適用する。別sessionへの参照転用は禁止。
4. 主測距OFF時の拒否、既定OFF、非同期drop、遅い比較、切断／session変更／古い結果、保存失敗、サイズ上限、pin/load順序、shutdownをテストする。既存driver回帰・操縦AST／shell回帰も確認。
5. 保存画素＋同frameの保存枠を実worker main・pipeへ通し、比較OFF/ONで主結果が一致すること、pinとloadの後の比較数値、PNG無加工、参照不一致の保留を検証。保存枠代用は専用検証だけで、運転経路にfallbackを加えない。
6. 実カメラ段階の手順・必要提出物をまとめる。次の不足は現在sessionの未展開1画像（通常受信のpin）と実GPU追加負荷。追加校正撮影・実走行をその前提にしない。実機・カメラ・ROS・CUDA・RTC待受けはこちらから起動しない。

新規依存は追加せず、既存のPython thread/lockと標準ライブラリを使う。[前日の接続設計](../../2026-11-10/driver_motion_bridge_r01/README.md)に記載された公式subprocess/threading仕様を継承する。別プロセス追加と比べ、主画像の追加IPCコピーを避けられるが推論process内のCPU資源を共有する。別workerの所有状態・容量1・期限・障害隔離をテストし、負荷の実測はカメラ／GPU PC段階まで未確認とする。
