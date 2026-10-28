# 変更前の再現記録（2026-10-27）

対象は読み取り専用コーン測距受信処理。カメラ、GPU推論、実ネットワーク、ROS、FFBは起動していない。

ベースコミット：`2a453b8`。変更前workerのSHA256は
`5d7ff59725794abd5237ea7f94dad672b7f9c7d5b4abee4b6efbd13db58581cd`。
10/26の`scene_cadence_audit_r01/verification.json`とも一致する。

新規テストファイルの最初の8件を、worker変更前に実行した。

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 -m unittest discover \
  -s tests -p test_cone_distance_worker_lifecycle.py -v
```

結果：8件中、成功3・失敗2・エラー3。

|確認|変更前の観測|
|---|---|
|再接続後に旧sessionのscene Futureが例外終了|`worker.error = 'retired scene failure'`となり、新sessionも停止|
|注入したテストpredictorのログ|実CUDA推論ではないのに`live_cuda_yolo`と記録|
|開始前のclose|`RuntimeError: cannot join thread before it is started`|
|scene処理が残る状態でclose|返り値None。sceneが残っているか判定できない|
|推論中の短いclose待ち時間|timeout指定を受け付けずTypeError。停止要求後の挙動を分離検証できない|
|現sessionのscene例外|失敗を記録し表示しない：既存動作は正常|
|旧sceneが未完了のまま再接続|追加sceneのキューを積まない：既存動作は正常|
|推論中に複数フレーム到着|1→4のみ処理し、2・3へ追いつく処理をしない：既存動作は正常|

失敗2件と開始前closeは旧実装の実際の不具合を示す。残るclose APIの2件は、終了状態を明示的に検証するための新しい契約を示すもので、既存実験の不成功率ではない。
最終版のテストは追加ケースを含むため件数が異なる。最終結果は`verification_r01/summary.json`を参照。
