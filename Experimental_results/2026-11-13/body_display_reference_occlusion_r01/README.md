# 遮蔽試験pin1677の確認：画像は正常、load前に再pinが必要

2026-11-13 JST。提出 `body_guard_occlusion_pin_r01.tar.xz` は必要4点完備。
**不足ファイルや画像の破損ではない。ただしコピー時の最新理由が `comparison_input_gap` のため、pinの照合情報が継続しているとは確認できず、今回の画像でload用参照は発行しない。**

## 確認結果と判断

- session `24e1146277d043fa8c01d36e2ebe0651`、pin1677、コピー時latest2945。state=pinned、snapshots_saved=1、writer_done=false、error=null。
- 原PNGは1280×720。PNG SHA／復号BGR SHA／同名JSON／status内pinが一致。元画像は無加工で確認した。台座の手前辺は見える。今回は境界CSV・reference.jsonを作成していない。
- 表示ゲートenabled=true、元主結果非変更、棄却専用。比較9＋表示7コードのSHAが現在ローカルと一致（重複を除く12ファイル）。profile/config・記録重みSHAも一致。checkpoint本体の独立再hashは未実施。
- 最新の主数値は約1.589464mだが別比較は参照なし。数値は距離精度・新表示許可の証明ではない。
- 最新reasonは **comparison_input_gap**。入力時刻が既存の0.5秒上限より飛ぶとstreamは参照とwitnessを消去する。単に次の新鮮なframeを受けても、古いpin照合情報は自動復元されない。

重要：`state=pinned` は直近pin要求の処理状態で、内部witnessが今も存在する証明ではない。
ただしworkerは「admit→pin」の順で処理するため、gapがpinと同じframeのadmitで起きた後にpinを作った場合は、reasonがinput_gapのままでもwitnessは残り得る。
したがって **この4点だけで「pin後に必ず失効した」とは断定しない**。gap発生frame・原因は全ログ未提出で不明。
load失敗を避けるため、コピー時の理由がpin待機に戻ったことを確認できる新pinへ進む、という保守的な判断である。待機秒数や期限を緩めたり、古い参照へsessionを付け替えたりしない。

最終判断は [assessment_r02/audit.json](assessment_r02/audit.json)。初回 `results_r01/audit.json` は4点のファイル整合性の確認で、load可能性の判定ではない。assessment_r01から時系列の不確実性を明記したr02へ更新した。どの段階でも参照は発行していない。
原本は `recordings/2026-11-13/body_display_occlusion_pin_intake_r01` にバイト一致保存。pinの主JSONL完全行SHAは主ログ未提出のためまだ照合していない。

## GPU PC：同接続で1回だけ再pin

送受信は継続。車体・カメラを触らず、コーンも現在の見える位置に置いたまま行う。
再録画・実機走行・新受信・Lキー・loadはまだ不要。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/body_guard_occlusion_r01 pin
```

数秒後：

```bash
./yolo-env/bin/python3 src/manage_guarded_comparison.py \
  --directory recordings/2026-11-13/body_guard_occlusion_r01 status
```

確認条件は `state=pinned`、pin.frameが1677より大きい、同session、snapshots_saved=2、writer_done=false、error=null、latest.reason=`comparison_pin_requested`。
**再びinput_gap／input_staleや別の理由になる場合、さらにpinを繰り返さず、そのstatusを共有する。** 原因確認へ切り替える。接続が切れた／sessionが変わった場合も共有し、新旧を混ぜない。

## 新しいpinの4点だけを圧縮

同じ元フォルダには旧pin1677も残るので、前の `decoded_*.png` の一括コピーは使わない。
下記はstatusが指す**最新pinだけ**のPNG／同名JSON、コピーしたstatusの原バイト、engine summaryを、メモリ上で固定して圧縮する。
元データは移動・削除・加工しない。archiveは新規作成専用で、同名ファイルがあれば上書きせずエラーになる。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
./yolo-env/bin/python3 - <<'PY'
import io
import json
from pathlib import Path
import tarfile

base = Path('recordings/2026-11-13/body_guard_occlusion_r01')
status_blob = (base / 'comparison_status.json').read_bytes()
s = json.loads(status_blob)
assert s['state'] == 'pinned' and s['writer_done'] is False and s['error'] is None, 'share status; do not load'
assert s['pin']['session'] == '24e1146277d043fa8c01d36e2ebe0651' and s['pin']['frame'] > 1677, 'new pin in same session required'
assert s['latest'] is not None and s['latest']['reason'] == 'comparison_pin_requested', 'share status; pin continuity uncertain'
name = s['pin']['image_file']
assert Path(name).name == name and name.endswith('.png'), 'unexpected image name'
sidecar = Path(name).with_suffix('.json').name
payload = {
    'comparison_status.json': status_blob,
    name: (base / name).read_bytes(),
    sidecar: (base / sidecar).read_bytes(),
    'motion_engine_summary.json': Path('Experimental_results/2026-11-13/driver_body_guard_occlusion_r01/motion_engine_summary.json').read_bytes(),
}
assert json.loads(payload[sidecar]) == s['pin'], 'pin sidecar mismatch'
output = Path('/home/hsr/Downloads/body_guard_occlusion_repin_r01.tar.xz')
with tarfile.open(output, 'x:xz') as archive:
    for filename, blob in payload.items():
        member = tarfile.TarInfo('body_guard_occlusion_repin_submit_r01/' + filename)
        member.size = len(blob)
        archive.addfile(member, io.BytesIO(blob))
print(output)
PY
```

作成された `/home/hsr/Downloads/body_guard_occlusion_repin_r01.tar.xz` を提出する。
Assertエラーならその出力とstatusを共有し、チェックを削除して強行しない。
送受信と停止状態は維持。新pin確認後に現在画像用の参照・SHA・load手順を提示する。

## ローカル変更・検証

実機コード・閾値・校正・環境は変更していない。
4点intakeへ明示 `--archive-prefix` を追加（従来既定1113bodyは維持）。共通intakeに最新reasonとpin継続不確実フラグを記録し、参照生成器はその場合の発行を拒否する。
これはローカルの解析・生成時だけの変更で、GPU PCへ新パッチを当てる必要はない。

合成データで「pin後gapならwitness消去」と「pinと同frameのgapが先ならwitness保持」の両方を検証し、今回の時系列を断定しない根拠にした。
現在のstatusから参照発行を拒否すること、4点CLIの新prefix指定と既定の隔離、再提出のスクリプトの最新pin選択／原本保持／gap時拒否／既存archive非上書きを検証した。UI・実カメラ・実CUDA・ROS・車体はこのPCから起動していない。日報・commit/pushは今回未依頼。

関連60テスト成功（current pin intake／body pin intake／stream comparison／occlusion repinの4テストファイル）。
