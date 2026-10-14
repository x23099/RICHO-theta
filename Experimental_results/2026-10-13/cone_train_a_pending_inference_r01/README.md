# 不成功の推論試行（再利用しない）

2026-10-13、Aの未注釈170枚を外部manifestで推論しようとした初回試行。
manifestの`image`列と内部キーの二重指定によるTypeErrorで、完了前に停止した。
`provenance.json`のSTARTED状態を成功と扱わない。正解ラベル・学習モデル・元画像の変更は行っていない。

修正と回帰テスト追加後の正常結果は[cone_train_a_pending_inference_r02](../cone_train_a_pending_inference_r02/)。
確認用画像集・手順は[準備報告](../cone_train_a_hardcase_preparation_r01/README.md)。
