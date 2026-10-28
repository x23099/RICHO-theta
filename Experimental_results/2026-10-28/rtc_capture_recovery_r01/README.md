# RTC入力途切れからの復帰とローカル入力診断（2026-10-28）

## 結論

映像専用`--diagnostic`送信について、短いカメラ読み込み途切れでプロセス全体を終了せず、
古い画像を送らないまま新しい画像を待てるようにした。
ネットワークを使わない`probe`も追加し、送信と同じ画像設定で実景／No Signalの差を切り分けられる。

**No Signalの原因が特定・解消したという結果ではない。**
No Signalという絵柄が画像として返ることと、`read()`の更新が途絶えることは別の現象。
本修正が対応したのは後者であり、カメラ・キャプチャ機器・配信モード等の状態を自動修復するものではない。

## 根拠

[ユーザー提供ログの整理](user_observations.json)を参照。
matunucでの単独読み込みは120/120回成功し、最初17.5 ms、途中最大957.4 ms、500 ms超が1回。
旧送信処理は500 ms超で終了するため、通信なしで発生する一時遅延でも停止し得た。
一方、単体bird_eyeでは実映像、従来RTCでもNo Signalだったとの報告がある。
同一機器・同一時点・同一設定の映像を同時比較した記録ではないため、No Signalの原因をソフトウェアだけへ断定しない。

## 変更した動作

|項目|変更前|変更後|
|---|---|---|
|送信対象画像の古さ|読み込み完了後200 ms以内|変更なし|
|同じ画像の再送|しない|変更なし|
|新規画像待ちの終了条件|500 ms待って終了|最後の成功読み込み／起動から3秒まで待つ|
|読み込み失敗・ブロックの監視|500 ms超で終了|3秒連続の取得停滞でエラーを確定|
|復帰|送信再起動が必要|期限内の新規画像で同じtrackを再開|
|受信側の期限|最終デコード受信から500 ms|変更なし|
|距離計算・校正・姿勢・FFB|条件付き診断、FFBなし|変更なし|
|通常の走行用送受信コード|既存経路|変更なし|

`--capture-timeout-sec`で連続取得停滞の終了基準を指定できる（既定3、範囲1～10秒）。
これは診断接続を維持する上限であり、有効な画像・距離の年齢を延ばす設定ではない。
200 ms超の画像は引き続き送信対象外。画像を水増しして受信側の期限を更新する処理はない。
一度timeoutを確定したreaderは、遅れて画像が返っても復活させない。

ログには`capture_wait`、復帰時の`Capture returned after ... ms`、最大完了read時間を出す。
RTPのPTSは読み込み完了時刻に基づき、途切れの時間を含めて増加させる。時間を詰めたり、以前の画像を新しい時刻で送り直したりしない。

### 制約

- 3秒は停止判断の基準。定常送信中は約50 ms間隔で監視するが、接続交渉には別のtimeoutがある。
- ブロック中のOpenCV呼出しを安全に強制中断する実装ではない。reader終了は最大1秒待ち、残れば警告する。
- 読み込み完了時刻はセンサー露光時刻ではない。機器内部のバッファ滞留、PC間のカメラ撮影から表示までの遅延は検証していない。
- No Signal画面も1280×720の画像として返ることがある。読み込み成功を実景の正常性と読み替えない。
- 走行中の距離精度やFFB接続を承認する修正ではない。

## 次に行うこと：matunucだけで5秒の入力確認

今回のコードをmatunucへ反映してから実行する。Git commit/pushは今回実行していない。
GPU PCの受信を動かす必要はなく、bird_eye・映像送信などmatunucのカメラ使用プログラムを先に終了する。

```bash
cd ~/theta_ws

./theta-env/bin/python3 src/theta_rtc_diagnostic.py probe --device 0 --fps 30 --duration-sec 5 --output-dir Experimental_results/2026-10-28/camera_probe_r01
```

表示ウィンドウは`THETA local capture probe (unannotated)`。
終了は5秒後、またはウィンドウにフォーカスを当てて`Q`。
GUIを使えない場合だけ`--headless`を追加する。
出力フォルダが既にあれば`r02`等の新しい名前を使う。上書きや削除は不要。

```text
Experimental_results/2026-10-28/camera_probe_r01/
  probe_summary.json
  capture_observations.csv
  first_frame.png          # 新規画像を取得できた場合
  last_frame.png           # 新規画像を取得できた場合
```

画像は1280×720のまま、注釈・切り抜き・色補正なし。
OpenCVでデコードしたキャプチャ画像であり、センサーの元データと保証するものではない。
`last_frame.png`は最後に取得できた画像の保存記録で、終了時点まで入力が有効だった証明ではない。
CSVは診断ループが観測した新規画像だけ。全読み込みの一覧やカメラの厳密なFPSではない。

**まず`probe_summary.json`と`last_frame.png`を確認・共有する。**

- 実景が写る：同じデバイス・同じ画像設定でRTCへ進み、ローカル画像との差を調べる。
- No Signalが写る：その時点でネットワーク／YOLOより手前から無信号画像が来ている。bird_eyeを起動したコマンドと、起動時のデバイス・画像設定のログを比較する。
- 3秒timeout：復帰上限を超えている。最大read時間・読み込み失敗回数・カーネルログを調べ、期限だけを延ばして実験合格にはしない。

`scene_content_verified=false`、`no_signal_detected=null`は意図的。画像内容を自動判別して合否を付けてはいない。

## 実景が確認できた場合のRTC再開

ローカルprobeは終了させてから実行する。GPU PCの測距受信を先に起動しておく。
今回はプロフィール・受信期限を変更していないため、復帰修正の必須反映先はmatunuc側。

```bash
cd ~/theta_ws
export THETA_RTC_PYTHON="$PWD/theta-env/bin/python3"

bash src/start_theta_stream_rtc.sh --diagnostic --receiver-ip 150.89.169.78 --device 0 --fps 30 --capture-timeout-sec 3
```

受信がNo Signalのままなら、この修正で解決したとは扱わない。実景が来るまでは移動・測距精度・FFBの実験へ進まない。
新しい画像が途絶れた間の距離表示は保留となる設計だが、PC間の実動作は今回未確認。

## 検証

最終結果：[verification_r02/summary.json](verification_r02/summary.json)、
[テスト一覧](verification_r02/tests.csv)、[過去の証拠との照合](verification_r02/offline_evidence_checks.json)。

|確認|結果|
|---|---|
|関連自動テスト|157件成功、失敗・エラー・skip各0（既存136＋新規21）|
|957.4 ms途切れの再現|制御時計とfake cameraで復帰、新規画像だけを返す|
|実AV trackの挙動|メモリ内で待機→復帰、画素の切替とPTSの増加を確認|
|500 ms超でfalseを返すread|3秒未満なら復帰、失敗readは期限を更新しない|
|3秒以上の停止・遅れて成功|エラー確定、古いreaderは復活しない|
|送信制御ループ|peer/HTTPをstub化し、待機・復帰と終了時のreader解放を確認|
|probe画像|fake画像との画素完全一致、元解像度、ネットワークなし|
|従来の数値解析・画像証拠|68ファイル・94照合、不一致0|
|構文・書式|py_compile、bash -n、git diff --check成功|

`verification_r01`は送信制御ループの追加3件前の154件検証として保存。
旧readerテスト1件の人工時計は、新しい3秒終了条件を検証する値へ更新している。
測距本体、校正設定、受信PROFILE、通常の走行用stream/UIと起動シェルがGitベースと一致することも自動確認した。

**未実施：学校PCの起動操作、実カメラ、socketを開く通信、CUDA推論、ROS、走行、FFB、パッケージ変更、Git commit/push。**
テストの待機・復帰に出る警告や、意図的な異常終了ログは試験シナリオの一部である。

再現（未使用の出力名を指定）。

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-10-28/rtc_capture_recovery_r01/verify_recovery.py \
  --output-dir Experimental_results/2026-10-28/rtc_capture_recovery_r01/verification_r03
```

変更前の送信コードは[source_snapshot](source_snapshot/theta_rtc_diagnostic_before_recovery.py)へ保存。
SHA256：`f7a7a782ea1a5f22f676850c7c6a0f1d3fd8b54d395c74d31571b5ff04bb8488`。
過去の実行証拠の参照用であり、この保存場所から直接起動することは想定しない。
設計参考：[aiortc Media API](https://aiortc.readthedocs.io/en/stable/api.html#media)。
