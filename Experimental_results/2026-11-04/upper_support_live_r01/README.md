# 上端支持点の別比較ログ：既定OFFのライブ接続

## できるようになったこと

GPU距離受信へ `--upper-support-shadow` を追加すると、従来の
`distance_frames.jsonl` と**別ファイル** `upper_support_comparison.jsonl` に、
同一frameの旧/新支持点、別の3フレーム品質確認、同じ床モデルによる比較値を記録する。
新しい候補を通常の距離表示・元の支持点・TTC・FFBへ置換する機能ではない。

**既定OFF。指定しなければ別ログ・画像保存・追加観測は作られず、従来の動作を維持する。**
ONでは追加のCPU処理・ファイル書込みが発生し、通常側の最終時間計測にも含める。
追加処理で500msを超えた場合は通常側・新比較側とも古い数値を見送る。
ON時のフレーム処理速度が従来と同一だという保証ではなく、実GPU負荷は未測定。

## 実装範囲

- 新規 `src/cone_upper_support_live.py`：独立した品質状態、比較値、証拠PNG、検査・集計。
- `src/cone_distance_worker.py`：既定OFFの接続。通常ログと別JSONLを書き分ける。
- `src/run_cone_distance_live.py`：追加フラグと前提条件の検査、有効時のみsummaryへ記録。
- `src/cone_upper_support_candidate.py`：直前に作成したオフライン比較候補をそのまま使用。

通常のcore、GUI renderer、HSV、校正、既存の3フレーム条件、500ms条件、
同一接続のモデル読込みロジック・モデルファイルは変更していない。
変更前worker/entrypointは `source_snapshot/` に保存し、過去検証のhashを上書きしていない。

現在は、`--support-completion-shadow`、`--frame-evidence`、明示した固定床モードが必要。
固定床の元支持点sourceは `support_completion_shadow` に限定する。
誤った組合せはGPU・ネットワーク起動前に拒否する。

## ライフサイクル・時間・非制御の境界

- 既にロードされた同じモデルを使用し、ファイルの再読込み・session付替え・自動選択はしない。
- 新候補の品質ゲートは旧候補と別。モデル世代・接続・モデルのidentityが変われば再確認する。
- L再読込みで旧モデルが失効した場合、新側も旧比較値を保持しない。
  拒否された読込みから旧モデルへ戻らない。読込み後に届いたframeという既存条件も維持。
- 入力不在では新品質状態も失効。500msを超えた最終結果は数値を消し、次の確認をやり直す。
- モデルが未受理・別session・支持点なし・品質未確認なら数値を出さない。
- 生候補は品質受理前でも診断用に記録されるが、`upper_completion_granted` は
  単一画像上で候補を取得したという意味だけで、品質や距離精度の合格ではない。
- モデル要求のlock内で同一世代を参照し、処理途中の新しい要求で世代が混ざらないようにする。
- 新側の観測処理エラーは新候補なしとして記録し、旧候補を上書きしない。
  JSONL書込みやモデル所有関係の不整合等は診断workerの失敗として通知し、黙って正常扱いしない。
- 通常の画面下パネルも従来の固定床比較のまま。新側が改善しても画面が変わるとは限らない。
  新側の確認先は別JSONLと専用reportである。

新ログの検査は元の固定床幾何validatorを再利用するが、検査時のコピーだけで
source名/field名を対応付ける。保存データのsourceは明示的に `upper_support_shadow`。
型・同frame・同じbundle hash・候補との支持点一致・品質・500ms・非制御flagを維持し、
元のvalidatorの条件を緩めていない。

## 未加工PNGの限定保存

モデルがactiveかつ同sessionで、旧比較の支持点が欠けた場合、または新たに上端候補を取得した場合に、
その処理frameを `upper_support_evidence/decoded_<session>_f<frame>.png` へ保存する。
無注釈・1280×720の受信デコード画素であり、送信元カメラの無劣化原画像とは主張しない。
PNG再デコードの画素が入力と同一であることをテストしている。

- 1実行全体で最大20**試行**。失敗も試行数に含め、モデル世代変更で予算を戻さない。
- 試行間隔は受信側source時刻で1秒以上。全フレームを保存する機能ではない。
- 1ファイル最大4MiB。最大20枚なら画像だけで上限80MiB、別途JSONLは継続する。
- 排他作成で既存ファイルを上書きしない。安全なsession名・通常の保存フォルダを使う。
- 保存エラー、間隔制限、試行上限到達は各行の `evidence.status` へ記録する。
- 保存時間を含めてworkerが最終stampを付ける。保存が遅くても古い距離を新鮮と扱わない。

## ログとレポート

保存先の意味：

| ファイル | 内容 |
| --- | --- |
| distance_frames.jsonl | 従来の距離・支持点・固定床比較。新候補で上書きしない |
| upper_support_comparison.jsonl | 同frameの旧候補、新候補、別品質判定、モデル状態、比較値、PNG来歴 |
| upper_support_evidence/*.png | 上記条件で限定保存した無加工デコード画素 |
| fixed_floor_model_events.jsonl | 既存のL要求・受入れ・失効・拒否 |
| live_summary.json | 終了状態と、新機能を有効にした場合の保存方針 |

GPU不要の専用集計（GUI・機体・FFBは起動しない）：

```bash
cd ~/yopi_ws/RICHO-theta
./yolo-env/bin/python3 src/cone_upper_support_live.py --input-dir Experimental_results/2026-11-04/upper_support_capture_r01 --output-dir Experimental_results/2026-11-04/upper_support_capture_report_r01
```

新しいreport出力先が必要。通常の `./start_cone_distance.sh report` は従来ログのためのままである。
専用reportは逐次読み、全ての大きなJSON行をメモリへ保持しない。
行の型・鮮度・非制御flag・時間順序・session引退・config固定・NaN等を検査し、
旧/新の比較値件数・新規候補取得件数・保存状態・モデル別のcount/min/max/meanを集計する。
中央値、精度、実表示率、カメラFPSを計測したものではない。
PNGのhashは記録されるが、report単体ではPNGファイルの実体検証やrun終了の承認まではしない。
書込み途中のJSON行は黙って捨てず拒否するため、reportは受信をQ終了した後に実行する。

## 検証結果

[verification_r01/verification.json](verification_r01/verification.json)：**関連435件成功、failure/error/skip 0**。
既存415件＋新規20件。各件は `tests.csv` / `tests.log`。

新規では既定OFF・前提不足の起動前拒否・独立3回確認・モデル世代変更・失効・
別session・後段の遅延による数値取消・PNG画素一致・間隔/上限/上書き禁止・
候補例外・複数/未検出・不正データ拒否・専用reportを確認した。
実ワーカースレッドで別ログ生成と通常ログの保持、local reload成功後の新側数値、
失敗した置換で数値が消えること、画像保存相当の600ms遅延が最終鮮度へ含まれることも確認。
テストのカメラ/推論/ネットワークは合成入力またはstubで、学校の実機を起動していない。

同一frameの既存PNG2枚も旧候補を変えず再計算した。
2枚は時間間隔が離れているため、新品質ゲートで3回連続確認したとは扱わず、
数値なしのまま記録。例は `verification_r01/RECORDED_RECOMPUTATION_NOT_LIVE/`。
予測元も「録画済みbox＋過去時刻を使う再計算」と明示し、実GPUのライブ成功と混同しない。

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-04/upper_support_live_r01/verify.py --output-dir Experimental_results/2026-11-04/upper_support_live_r01/verification_r01
```

既存出力先には上書きしない。再実行時は未使用名へ変更する。
実GPUの追加負荷、保留81件の実画素での改善率、絶対精度は未確認。
モデルや校正の数値補正もしていない。

## 次回の実機手順

[live_procedure.md](live_procedure.md) を参照。今すぐの撮影・再起動は要求しない。
フラグを有効にするにはコード共有と新しい受信起動が必要で、その時は接続IDが変わる。
旧df33e833向けprepared_floorを流用せず、新接続で床PNG→同sessionモデルを準備する。
今回Git commit/push・学校PC操作・カメラ/機体/FFBの起動は行っていない。
