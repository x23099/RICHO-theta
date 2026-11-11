# 保存画像の実CUDA YOLO・比較worker負荷試験

2026-11-11。GPU PCの保存枠による再生は完了。matunuc／カメラなしで、同じ8 native画像を新規YOLO推論へ通す独立試験を追加する。運転runtimeは変更しない。

- 既存のCUDA専用YoloConePredictor、MotionRangeEngine、GuardedComparisonWorkerを再利用。CPU fallback、モデルdownload、新依存、カメラ／ROS／RTC／操縦は追加しない。
- 入力PNG／sidecar／index／元ログとprofile/configを事前照合し、原画像を変更しない。過去の検出枠は診断用で、新しい推論の入力にしない。
- モデルは1回だけ初期化し、8回のwarmupを別記録。測定はOFF→ON→ON→OFFの4 block、各block20周×8画像を上限30回/秒で繰返す。遅れたときに追い付くための連続投入はしない。setupとwarmupを測定分布から除外する。
- ON blockの参照は、同一元画素の再生用pinを明示生成し、その再生session専用としてloadする。過去参照を実機の別sessionへ転用した証拠にはしない。
- 各画像の検出／主距離・保留の一致率と差分を記録。GPU非決定性や時系列順序の影響もあり得るため、OFF/ON差だけで比較workerが原因と断定しない。数値出力数を成功条件にしない。
- 呼出しwall時間のP50/P95、受信を模擬した時刻からの主処理時間、loop間隔、比較drop／鮮度／参照失効、終了を保存。純GPU kernel時間・カメラ遅延・運転負荷・物理精度とは呼ばない。
- このPCでは入力preflightと合成predictorによる機能試験のみを行う。実YOLO／CUDAはGPU PCの明示コマンドで実施してもらう。失敗時はfailed summaryを残し、黙って保存枠へ戻らない。
- 新規試験ファイルだけの転送パッチと短いGPU PC手順を作る。既に反映済みの13ファイルパッチやカメラ再生試験を繰り返させない。commit/pushは別依頼時のみ。
