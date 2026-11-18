# PNG送信待ち・混雑・連続入力のoffline検証

正式結果: [audit.json](results_r01/audit.json)、[集計CSV](results_r01/summary.csv)、[11条件の全カウンタ](results_r01/scenarios.jsonl)、[受取trace](results_r01/consumed.jsonl)、[回帰検証](verification_r01/audit.json)。作業日2026-11-18。

## 結論

PNG用の[LosslessLatestSender](../../../src/driver_lossless_frame_sender.py)を追加した。**進行中1packet＋待機最新1packet**に限定し、source scope/order/PTS、送信元時計のcapture age 200ms、channel buffer上限を検査する。新しい入力のたびに進行中を中断せず、待機中だけ最新へ置換する。満杯時にも期限切れは破棄し、invalid/閉鎖/時計逆行で旧packetを救済しない。

新規20 scheduler＋8 modelテスト、旧221と旧VP8 flow27を含め、**276成功・失敗skip 0、12.37秒**。旧VP8/runtime/UI/操縦/前段PNG codec/fragment/元画像はSHA不変。実通信・カメラ・CUDA/G923・Git操作なし。

## モデル結果

保存4原画を順に循環し、4秒間の合成入力を1ms tickで扱った。以下の「受取」は**画像/candidateが一致し、初片200ms内で一度だけ取り出せたpacket数**。距離が数値化できた件数・正しい距離の件数・実ネットワークでの成功率ではない。

| 仮想回線（純データ容量） | 5Hz入力 | 10Hz入力 |
|---|---:|---:|
| 15Mbps | 0/20 | 0/40 |
| 30Mbps | 0/20 | 0/40 |
| 100Mbps | 20/20 | 40/40 |

15/30Mbpsではsender期限までにpacketを渡し切れず、全件破棄。100Mbpsの受取初片→takeは最大153msだった。ただし、この値には実GPU推論・IPC・表示・通常の運転映像・実通信overheadが入っていない。

100Mbps・10Hzでの追加条件:

| 条件 | 受取 | 判明した動作 |
|---|---:|---|
| 1.0〜1.6秒の回線停止 | 34/40 | 6件を期限破棄、停止後に復帰 |
| 127片ごとに1片欠損 | 21/40 | 19片欠損、画像の部分受理なし |
| 受信CPU仕事を2.5倍 | 0/40 | 待機16件置換、24件処理後期限破棄 |
| 送信CPU仕事を2倍 | 0/40 | capture待機15件置換、25件のencode出力を送信完了できず |
| 全片に一方向500ms遅延 | 40/40 | 初片後は間に合うが、撮影から最大744ms経過 |

**最後の条件は「鮮度が良い」とは扱わない。** 通常100Mbpsモデルでも合成capture→takeは最大244ms。送信側capture→handoff 200ms以内と受信側初片→take 200ms以内は別々のローカル予算であり、撮影→表示/制御まで200ms以内という意味ではない。500msの経路遅延は初片到着前に発生し、ローカル受信期限だけでは検出できない。source_freshness_verified/usable_for_ffb等はfalseを維持する。これはPC時計同期を追加した結果ではなく、simulation oracleだけが全体経過を知っている診断である。

## 上限と時間条件

- worker同期offerはPNG全検査を行う。live RTC/UI callbackへ接続していない。将来のadapterは検査後のsender時刻を取得し、callback入場時刻を使い回さないこと。
- senderは手元の進行中・最新待機だけを破棄できる。transportへ既に渡したbytesは取り消せない。channel閉鎖時の消去と実インスタンスclose後の再利用禁止はunit testで確認。
- sender retained wireの実測モデル最大2,016,257bytes/2slot、decode待ちwire最大2,049,144bytes/2slot。capture処理とdecode処理にも1 active＋1 latest pendingをモデル化したが、これらのlive worker実装を追加したわけではない。
- channelの未送出量は32KiB以下、実際に保持するmessage bytesも今回最大32KiB。再構成bufferは1packet、最大1,025,942bytes。元のpayload2MiB/header8KiB/fragment16KiB/200msを変更していない。
- 遅延モデルの経路内flight bytesは最大5,130,742bytes。channel bufferとは別で、モデル上限は8×MAX_PACKET。経路bufferの実容量を測った値ではなく、モデル自体のメモリを有界にする設定である。overflow dropは全条件0。
- held_for_bufferは1ms tick中のpump呼出し回数で、失敗packet数や欠損率ではない。

## 実測とモデル入力を区別する

[model.py](model.py)はsocket・sleep・実時計同期を使わない有限モデル。send clock=1000+仮想時刻、receive clock=5000+仮想時刻を各実装へ渡す。sender/receiver実装は相手PCの時計と減算しない。traceのoracle_capture_to_take_msのみモデル内部の共通経過時間から算出し、実運用で利用できる値にはしない。

CPU仕事は前段lossless_frame_packet_r01/results_r02の画像別中央値を使う。sender=encode+初片前検査で79.91〜88.22ms、receiver=初片からtakeまで全仕事で65.56〜71.38ms。初片前検査は前段の各stage差分から導出し、[auditのtemplates欄](results_r01/audit.json)に式の入力を保持した。GPUPC・送信側の速度ではない。受信仕事は保守的に再構成完了後のsingle worker serviceとして集約する。

4枚は実PNG encoderでメモリ内変換して元全画素SHAを検査した後、payloadを再利用する。各frameのcandidate/packet framing・scheduler・fragment・再構成・decode/画素SHA検査は実コードを使う。5/10Hzで毎回新画像を連続encodeした負荷測定ではない。candidateは合成capture/no-odomであり、元撮影の運動記録を復元していない。原画を書き換えたり派生画像を保存したりしていない。

モデルの転送は理想的なbyte drainで、message完了を次の1ms境界へ切り上げる。SCTP/DTLS/IP、輻輳制御・実損失分布・通常映像・OS/GPU競合は省略している。**100Mbps条件の合格を実機採用条件や実回線100Mbps保証へ読み替えない。**

## 検証

新scheduler20テストは既存PNG fragment generatorとのbyte一致、進行継続/最新置換、slot/bytes、buffer満杯、idle/進行中の期限、scope/order/PTS/future時刻、invalid/閉鎖/時計逆行/closeを確認。新model8テストは再現性・全画素/一度きり受取・部分欠損・500ms遅延の限界・送受信CPU遅延・停止復帰・入力上限を確認する。

初回model unit testは単色の小PNGでも32KiBが満杯になるというfixtureの誤った前提で1件失敗した。圧力試験だけnativeの大きい合成PNGへ差し替え、production/modelの上限や採否を変えずに修正した。正式回帰は276成功。前段結果・manifestは上書きしていない。

## 次の実測へ

1. GPUPCの保存原画を使い、PNG encode/検査/fragment/復号/既存CUDA測距を同一条件で計測する手順を準備する。今回の解析PCコストをそのままGPUPCへ採用しない。
2. その結果を使って最低容量と待機予算を見直したうえで、送受信PCの実回線容量・遅延と通常映像との共存を、操縦/FFBから分離した観測専用試験で確認する。実送信開始は今回行っていない。
3. 初片前の経路遅延を含めた撮影情報の鮮度を別に設計・検証する。PC時計同期の必須化には戻らず、ローカル期限の合計をend-to-end保証へ取り違えない。元鮮度・接地・車体基準・FFB未認定のまま。

現時点の追加撮影・機体走行・ユーザー側の操作は不要。

## 再現（解析PC、未使用の出力先）

```bash
cd /home/robo25/theta_ws/RICHO-theta
OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/lossless_sender_load_r01/run.py --output-dir Experimental_results/2026-11-18/lossless_sender_load_r01/results_r02
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-18/lossless_sender_load_r01/check.py --results Experimental_results/2026-11-18/lossless_sender_load_r01/results_r02 --output-dir Experimental_results/2026-11-18/lossless_sender_load_r01/verification_r02
```
