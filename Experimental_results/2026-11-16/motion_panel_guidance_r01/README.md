# 運転画面：対象範囲・保留理由の日本語説明

## 完了した変更

運転画面下部の測距欄に日本語の対象範囲・状態説明・用途の注意を追加した。元の距離・frame・receive-age・body-review世代・英語の理由コードと注意文は保持している。測距の有効／保留は既存snapshotの判断をそのまま使う。

| 状態 | 追加する説明の例 |
|---|---|
| 対象範囲 | 前方魚眼の指定範囲内に検出枠の中心がある候補1本のみ。画面全体の測距ではない。実際のnative ROIを表示 |
| no_candidate | 対象範囲内でコーン候補を取得できていない。範囲外・故障のどちらとも断定しない |
| possible_self_body_occlusion | 台座付近が車体境界に重なる可能性があるため保留 |
| colour_contour_reaches_roi_edge | 色領域が解析枠端に達し、支持点を確定できない |
| 参照未読込・失効・不一致 | 現在接続の参照状態を確認するよう説明。自動loadや連打はしない |
| 古い入力／結果 | 現在の結果を待機し、古い数値を出さないことを説明 |
| 未知の理由 | 元コードを残し、原因を作らず詳細確認を促す |

`src/driver_motion_presentation.py` は説明専用。UIのラベル初期化／更新から呼び、QLabelはPlainTextに設定する。理由コード内の文字列をHTMLとして解釈しない。ROIは実際の起動引数を使い、未指定時に中央ROIを勝手に補わない。
元魚眼座標とリマップ後画面座標が違うため、今回映像へROI枠や支持点を重ねていない。元画像・保存画像を加工していない。

## 表示例・確認範囲

以下はQt offscreenの**合成ラベル表示例**で、実機画面や再走行の証拠ではない。

- [候補なし](previews_r01/no_candidate.png)
- [数値あり](previews_r01/numeric.png)
- [自己遮蔽の可能性](previews_r01/self_body_occlusion.png)

全1650×220、英語コード・日本語描画・折返し・PlainTextと必要ラベル高さを確認した。原本・入力・コードSHAは [preview manifest](previews_r01/manifest.json)。offscreen pluginのpropagateSizeHints非対応メッセージは出たが、描画と高さ検査は全3件成功。実GPU PCのフォント・全運転画面の配置は未確認。

[検証結果](checks_r01/summary.json)は71テスト成功（新規表示12＋既存関連、他段階の件数と重複あり）。受信更新の前に説明を更新できること、保留snapshotに古い元数値が残っていても数値を出さないこと、未知理由、ROI、入力非変更、既存の操縦・ROS・キーボード・sender経路のAST不変を確認。
11/16全ログに記録された測距・表示ゲート・参照・bridge・protocol等12コードは**全バイト不変**。距離計算・profile・しきい値・採否・非制御属性を変更していない。過去の実機ログをこの新しいUIで再描画した実績とは扱わない。

## GPU PCへの反映（まだ未実施）

この変更は現在ローカル未commit／未pushで、Pullだけでは届かない。GPUでの実機動作確認もまだ行っていない。日報・commit/pushは今回依頼されていない。

1. [motion_panel_guidance_update_r01.patch](motion_panel_guidance_update_r01.patch) をGPU PCの `/home/hsr/Downloads/motion_panel_guidance_update_r01.patch` へコピーする。
2. 受信を終了した状態のGPU PCで以下をそのまま実行する。既存実験フォルダ・ユーザー変更は削除しない。

```bash
cd /home/hsr/yopi_ws/RICHO-theta
git status --short
if ! printf '86dbd43a0188690adbc48c21ef924daac1762fb75f95f7cf76351adf6c7c4b7c  /home/hsr/Downloads/motion_panel_guidance_update_r01.patch\n' | sha256sum --check; then
  printf 'SHA不一致です。適用せず出力を共有してください。\n'
elif git apply --reverse --check /home/hsr/Downloads/motion_panel_guidance_update_r01.patch >/dev/null 2>&1; then
  printf '反映済みです。git applyの再実行は不要です。\n'
elif git apply --check /home/hsr/Downloads/motion_panel_guidance_update_r01.patch; then
  git apply /home/hsr/Downloads/motion_panel_guidance_update_r01.patch
else
  printf '適用条件が一致しません。変更せずエラーを共有してください。\n'
fi
```

変更はUIと新表示moduleの2ファイルだけ。[patch manifest](patch_manifest.json) に基準commit・更新前後SHAを保存した。reverseは必ずcheck付きで使い、戻す操作は行わない。正方向チェックの失敗をforce／reject／resetで回避しない。
同じ基準ファイルからの正方向適用、更新後SHA、逆方向チェック成功、二重適用拒否は隔離した一時フォルダで確認済み。

3. 反映できたら、カメラを使わずGPU PCの端末で日本語説明のimportと出力を確認できる。

```bash
PYTHONPATH=src ./yolo-env/bin/python3 -c 'from driver_motion_presentation import panel_text; print(panel_text(dict(available=False, reason="no_candidate"), target_roi=[270,0,350,720]))'
```

この出力を共有すれば、まず反映確認を進められる。追加測定・走行・録画は不要。実際の運転画面の配置は次の通常使用時に確認すればよく、そのためだけの新しい測距実験は要求しない。終了済みの本日r01へ受信を再起動しない。新接続が必要なときだけ新しい保存先・現在pinを使う。

## ローカル再現

```bash
cd /home/robo25/theta_ws/RICHO-theta
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/motion_panel_guidance_r01/preview.py \
  --output-dir Experimental_results/2026-11-16/motion_panel_guidance_r01/previews_r02
/home/robo25/theta-env/bin/python3 Experimental_results/2026-11-16/motion_panel_guidance_r01/check.py \
  --output-dir Experimental_results/2026-11-16/motion_panel_guidance_r01/checks_r02
```

check.pyは現在のソースと固定したpatch／previewのSHAも検査するため、今後さらにUIを変えた場合は新しい版のpatch／previewとして作り直す。旧manifestを新しいコードへ合わせて書き換えない。
この作業でROS・カメラ・RTC接続・GPU推論・機体・FFBを起動していない。
