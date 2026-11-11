# 比較側だけの診断コピー削減

2026-11-11。二重抽出削減後もGPU比較ONは約23.86件/秒、主P95約55.59ms。既存CPU profileには診断観測辞書のdeepcopy負担が大きく残る。まずこれに限定し、比較頻度・thread設定・process配置は変更しない。

1. 通常の公開比較関数は従来の独立した診断コピー・両bbox policyを既定のまま残す。比較workerの1回の計算内だけにcompact経路を追加する。
2. compactは毎回元画素から観測を新規抽出し、使用するhalf_pixel_overlapだけを評価。baseline／proposalを構築する間、読み取り専用で扱う入れ子の診断情報を同一呼出し内で共有する。棄却によるpoint/support/reasonの書換えは必ず別のtop-level dictへ行う。主ログ・前フレーム・参照witnessの借用にはしない。
3. MotionRangeEngineが所有する結果コピーとstream／workerの外へ返す結果の所有権は維持する。compactの一時graphはworker内で消費し、呼出し間キャッシュを設けない。既存のデフォルトAPIのコピー独立性は変えない。
4. 全診断値のdefault/compact一致・nested aliasの範囲・入力不変・例外と失効を合成／元8ケースで確認。CPU wall時間・cProfileをfull→compact→compact→fullで比較し、GPU改善や実時間30fpsとは呼ばない。
5. 合格した候補だけを既定OFFの比較streamへ接続し、関連回帰・GPU提出320比較行・実子pipe再生を検証する。主測距、500ms鮮度、参照pin/load/失効、元点・幾何・棄却条件、操縦／ROS／FFBには変更を加えない。
6. GPU PCへ今回の差分だけを渡し、変更後の実CUDA試験は新しいr03へ保存する。カメラ／matunuc／新規撮影は不要。GPU結果が必要になるまでこのPCで検証する。commit/push・実機操作は今回行わない。
