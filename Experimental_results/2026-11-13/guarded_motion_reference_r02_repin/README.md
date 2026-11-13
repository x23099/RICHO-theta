# r02再pin frame18497：現在参照

提出 `1113motionr02_1.tar.xz`（内部rootは1113motionr02）の原本3点を検証した。
session `24aad0a8d31d46eeb33ef252b0d18475`、最新pin frame18497、snapshots_saved=2。
コピー時pinned・latest20232・writer_done=false・error=null、PNG/BGR/sidecar/status一致、記録9コードSHA一致。
元主JSONL未提出のためpin元行SHAは終了後に照合する。現在までのwitness残存は未保証。

## 経緯と今回の変更

ユーザーがr02の最初のloadを行った際、r01のframe516 PNGを探してFileNotFoundErrorになった。
これは旧参照の取違えと整合する。その失敗でworkerのinvalidateが内部witnessも消去したため、
正しいframe1062参照へ替えた次のloadも「reference source was not explicitly pinned in this stream」で拒否された。
statusのpin欄は履歴であり、内部witnessの残存証明ではない。そこで同接続で新pinを明示取得した。
再起動やsession書換え・古い画像の追加は行わない。

今回はframe18497の現在PNGを無加工で読み直し、x270〜380／中央y455付近の天板境界を記録した。
境界座標は前のr02と同じ読取りとなったが、現在画像を独立に確認した上で新PNG SHA/frameへ結び付けた。
黄色テープx311〜339は隣接点補間、読取りの目安2px。床接地・高さ・物理精度や取付再現の認定ではない。

ローカルintakeだけを初回pin限定のsnapshots_saved==1から、実runtime上限どおり整数1〜8へ拡張した。
最新pin/request/画像照合・鮮度・同session・権限false等は維持。関連テスト19件成功。
runtime・GPU環境・主表示・ROS・FFB・安全判定は変更していない。

## コピー・照合・load

このフォルダの新しいreference.jsonをGPU PCの次の場所へコピーする。

`/home/hsr/yopi_ws/RICHO-theta/recordings/2026-11-13/guarded_motion_r02/reference.json`

同名の過去参照との取り違え防止に、GPU PCのコピー先SHAをreference_validation.jsonのreference_sha256と照合する。
未pushなのでPullだけでは届かない。正しいSHA確認後にloadし、数秒後statusを提出する。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
sha256sum recordings/2026-11-13/guarded_motion_r02/reference.json
```

一致時だけ：

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_motion_r02 load
```

数秒後：

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_motion_r02 status
```

まだ送受信を終了せず機体とカメラを停止維持。active・同session/frame18497・reference_scope_verifiedの確認前には走行しない。
失敗したらloadを繰返さず出力を共有する。新pinも今回ファイルの確認中には行わない。
成功後の画面録画・低速短距離直進・停止・r02の3フォルダ提出は
[r02手順](../guarded_motion_reference_r02/README.md)を参照する。

## 再現と保存

原本はrecordings/2026-11-13/guarded_motion_repin_intake_r02へバイト一致保存。
archive/PNG/BGR/コード等のSHA根拠はresults_r01/audit.jsonとreference_validation.json。

```bash
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/guarded_static_reference_r02/intake.py \
  --archive /home/robo25/Downloads/1113motionr02_1.tar.xz --archive-prefix 1113motionr02 \
  --intake-dir recordings/2026-11-13/guarded_motion_repin_intake_r02 \
  --output-dir Experimental_results/2026-11-13/guarded_motion_reference_r02_repin/results_r01
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-13/guarded_static_reference_r02/build_reference.py \
  --input-dir recordings/2026-11-13/guarded_motion_repin_intake_r02 \
  --audit Experimental_results/2026-11-13/guarded_motion_reference_r02_repin/results_r01/audit.json \
  --boundary-csv Experimental_results/2026-11-13/guarded_motion_reference_r02_repin/reviewed_boundary.csv \
  --output-dir Experimental_results/2026-11-13/guarded_motion_reference_r02_repin
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/robo25/theta-env/bin/python3 -m pytest -q tests/test_guarded_current_pin_intake.py
```

出力新規パス必須。こちらでremote load・走行・実CUDAを実行したわけではない。日報・commit/push未依頼。
