# b559e424：上端比較ログ試験用の新接続床モデル

ユーザーが床PNGを提出し、モデル準備前なのでLを押していないと報告した。
**正しい順序は、S保存→PNG提出→モデル準備・配置→同じ接続のままL。**
受信・送信を切ると接続IDが変わるため、この手順中は維持する。

## 入力・観測・制約

- native PNG：`decoded_b559e4240e364166935f9ede9ac3e7ae_f005755.png`。
- session：`b559e4240e364166935f9ede9ac3e7ae`、frame5755、1280×720。
- SHA256：`382ccb5992ab80cfb69290ef057d7010d30e9a6392e434832a70a5613404d76b`。
- 元バイト保存：`recordings/2026-11-04/floor_reference_b559e424_r01/`（Git外）。画像は加工・再保存しない。
- 格子全体は既存の完全検出で不成立。別の窓/背景格子を使っていない。
- 白い紙の外周が床の反射とつながるため、紙角の物理対応は不確か。
  170閾値/輪郭係数0.025の観測四角形を主仮説、190/0.04を別対照として残した。
  従来の係数0.02では7頂点なので、同じ条件で四隅を検出できたとは扱わない。
- 主仮説：`[[297,407],[348,406],[353,423],[299,426]]`。
  別対照：`[[303,404],[348,407],[353,422],[298,425]]`。
  特に左上の読取りに差があり、距離精度の保証はできない。
- 紙296×210mm、板厚概算15mm、レンズ床上高さ590mmを従来の申告として明示入力。
  高さ・コーン距離に合う四隅や解を選択していない。
- 主仮説のas_listed解0の紙面推定高さは約566.7mm、別対照は約633.2mm。
  どちらが実際の床を表すかは未確定。全8候補を比較専用として保持する。
- 今回の目的は同じ床モデルで旧/新支持点を比較記録すること。
  上端候補の記録ができても、絶対距離や床モデルの精度が確定するわけではない。

## 配布用モデル

[prepared_floor_b559e424_f005755.json](prepared_floor_b559e424_f005755.json)

SHA256：`414ea62787afdc829900c12d109202ae5a0f75999e16259e12dccf109a87e92e`。
`derived_primary_r01/prepared_floor.json` とバイト同一。
別対照は `derived_control_t190_r01/` に残し、この配布ファイルへ混ぜていない。

GPU PCの `~/Downloads/` へ上記ファイルを保存後、GPU PCの別ターミナルで配置する。
出力先は [上端比較の実機手順](../upper_support_live_r01/live_procedure.md) の起動例を前提とする。

```bash
cd ~/yopi_ws/RICHO-theta
python3 -c 'from pathlib import Path; import hashlib; data=(Path.home()/"Downloads/prepared_floor_b559e424_f005755.json").read_bytes(); assert hashlib.sha256(data).hexdigest()=="414ea62787afdc829900c12d109202ae5a0f75999e16259e12dccf109a87e92e", "model hash mismatch"; out=Path("Experimental_results/2026-11-04/upper_support_capture_r01/prepared_floor.json"); f=out.open("xb"); f.write(data); f.close(); print("Saved:",out)'
```

既存ファイルを削除・強制上書きしない。別の出力先で起動した場合は実際のL読込み先と照合する。
`Saved:` が出たら映像ウィンドウでLを1回。
`load_requested` → `active reason=accepted_comparison_only` を確認する。
モデル読込み後は板を片付け、車体とカメラを動かさずコーンだけ正面約1mへ置き30秒静止。
距離の基準は車体中心の床面位置から台座手前辺中央の水平直線距離で、実測値をメモする。

新比較は画面へ置換しないので、通常画面が変わらなくても別JSONLを確認する。
有効フラグ `--upper-support-shadow` が起動時に指定されている必要がある。
試験後のQ終了、専用report、フォルダ全体の圧縮・提出は上記手順書の通り。

## 検証と再現

`verification_r01/verification.json`：本PNGの観測点、無加工/hash、frame5755、
8未選択モデル、主候補との配布バイト一致、旧session/未来frame/config不一致の拒否を確認。
直前のソフトウェア435件成功はruntime hashが同じことを照合して再利用し、無変更の全試験を再実行していない。
このファイルの照合成功は、学校GPUでLが受理された・距離が正確だったという判定ではない。

```bash
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 src/derive_fixed_floor_live_bundle.py --references Experimental_results/2026-11-04/floor_reference_b559e424_r01/references.json --image-dir recordings/2026-11-04/floor_reference_b559e424_r01 --board-thickness-mm 15 --external-height-mm 590 --board-on-floor --rigid-board --static-camera --output-dir Experimental_results/2026-11-04/floor_reference_b559e424_r01/derived_primary_r01
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-04/floor_reference_b559e424_r01/verify.py --output-dir Experimental_results/2026-11-04/floor_reference_b559e424_r01/verification_r01
```

出力先は既存なので再実行時は未使用名へ変更する。
本作業で既存runtimeや運用設定、元画像、校正値は変更していない。
カメラ/学校PC/機体/FFBを直接操作しておらず、Git commit/pushや外部転送もしていない。

## 後続の実機提出で確認できたこと

モデル配布後、ユーザーの `upper_support_capture_r01.tar.xz` を受領。
このモデルSHA・参照frame5755が同じb559セッションでframe32629からactiveとなり、
正常終了まで比較記録されたことを [提出物の解析](../upper_support_capture_analysis_r01/README.md) で確認した。
モデル読込後3,852行で旧3,776行、新3,779行の条件付き数値あり。
ユーザーの実測は1m。これは配布後の実機結果であり、上記のファイル検証だけから推定した結果ではない。
床モデルの不確定性は [終了前の幾何監査](../floor_support_final_audit_r01/README.md) に整理した。
