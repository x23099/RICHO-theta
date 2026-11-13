# 新sessionのpin確認と、同接続でのload

2026-11-13。提出 `1113r02.tar.xz`（内部フォルダ1113r02）は、必要なPNG／同名JSON／statusの3点だけで足りている。ファイル名が異なることは問題ない。開始HEAD `22d6f39`（1113v2）、clean。rawを実行せず、元画素を変更しない。

## 今回の確認

| 項目 | 結果 |
|---|---|
| session／pin frame | 9e961a39b4f54b0395eb140f52625755／330 |
| pin画像 | 1280×720、PNG SHA・復号BGR SHA一致 |
| sidecarとstatusのpin | 全項目一致 |
| コピー時のworker | state=pinned、writer_done=false、error=null |
| コピー時の最新frame | 2794、同session、参照未load |
| pin〜最新frameの入力時刻差 | 約82.17秒 |
| 記録された依存コード | 既知9ファイルのローカルSHA一致 |

**コピー時点では稼働中だが、その後も接続が継続しpinのwitnessが残っているかは、この保存statusだけでは分からない。** 現在のworkerでloadし、activeを確認して初めて実読込み成功とする。失効や別sessionの場合に旧JSONのsessionを書き換えない。

新しいnative画像を見て局所天板境界を読み直し、[reviewed_boundary.csv](reviewed_boundary.csv) に保存した。x270〜380のみ使用、中央黒い天板の上端はy450付近。黄色テープで明暗が弱いx311〜339は隣接点間の補間。画像は注釈・切抜き・リサイズ等なし。目安2pxの読取りは物理精度や統計的信頼区間ではない。

その新画像・pin frame330・PNG SHAに明示対応させた [reference.json](reference.json) を用意し、既存validatorでschema・bounds・未承認flagsを確認した。前回sessionやr01の読取りを単に書き換えて転用していない。対象PNG SHAは `ad3b05f660523c8ef1196c85bd3a4c5a02463e40643dd7c513d753cf763d90d2`。

**これは自己遮蔽の比較用参照で、床姿勢・カメラ高さ・取付再現性・距離精度を校正するものではない。** カメラは毎回取り外すというユーザー条件を維持し、既存profileの取付仮定は未検証のまま。主表示・ROS・FFB・制御へ比較値を接続しない。

## GPU PCで次に行うこと

受信・送信は継続し、機体とカメラを動かさない。新たなpin、Lキー操作、再起動は今は不要。

1. このPCの `Experimental_results/2026-11-13/guarded_static_reference_r02/reference.json` をGPU PCへコピーし、次のファイル名で保存する。

```text
/home/hsr/yopi_ws/RICHO-theta/recordings/2026-11-13/guarded_static_r02/reference.json
```

2. GPU PCの別端末でloadする。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
/home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
  src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_static_r02 load
```

3. 数秒後にstatusを確認する。

```bash
/home/hsr/yopi_ws/RICHO-theta/yolo-env/bin/python3 \
  src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/guarded_static_r02 status
```

**まず、このstatusの出力を共有する。** activeが読込み成功。latest.baseline_reproduced=true、reference_scope_verified=trueが比較照合の目印。比較数値はlatest.comparison_distance_available=trueの時だけあり、未検出・複数候補・自己遮蔽などでは正常に保留する。保留だけで読込み失敗とは判断しない。

load_rejected／invalidated／errorや「not explicitly pinned」などが出た場合は、出力をそのまま共有する。旧参照を修正したり無条件にpin／loadを繰り返したりしない。

読込み成功後、停止状態で20〜30秒、主画面更新・比較ログ・保留・鮮度を確認する。主画面は現行のままで、比較値の新規表示は追加していない。映像や主更新が止まる／大きく遅れるなら進めず共有する。走行はまだ行わない。

その確認後は普段の停止・UI終了方法で終了してよい。終了後の次の2フォルダ全体を圧縮して提出すれば、更新中ファイルの問題はない。

- `Experimental_results/2026-11-13/driver_guarded_static_r02/`
- `recordings/2026-11-13/guarded_static_r02/`

元出力が別名ならその実フォルダを使う。ロード前のstatusだけでは、主保留の理由・負荷・距離精度・終了を独立監査できないため、最終的に両方が必要。画面録画や距離再測定は今は要求しない。

## 保存・検証

- raw：`recordings/2026-11-13/guarded_static_intake_r02/`、元3ファイルを無変更保存、Git対象外。
- `results_r01/audit.json`：3点のSHA・元画素・snapshot照合。主／比較ログは未提出と明示。
- `reference_validation.json`：参照SHA、pin画像・現在の読取り・生成コードの対応。実workerでのloadを実行した証拠ではない。
- `intake.py`：小さいtarの件数／サイズ／パス／リンク／重複の拒否、既存strict JSON parserと既知依存SHA確認を再利用。
- `build_reference.py`：検証済み3点と現在CSVから参照を生成。schema・ハッシュのローカル検査のみで、remote loadや実機認定は行わない。
- `checks_r01/`：今回の3ファイルintake helperの7テスト。未変更の測距runtime・実CUDA試験の再実行はしない。

今回runtime・環境変更、カメラ／CUDA／ROS／機体の起動、日報・commit/pushはしていない。参照はこのPCで生成したので、GPU PCにはファイルコピーで渡す。未pushの参照がPullだけで入るとは案内しない。
