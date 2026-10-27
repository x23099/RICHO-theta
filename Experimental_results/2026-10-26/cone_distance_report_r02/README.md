# 固定格子の中間再計算r04

原点固定の1秒格子を追加した最初の再計算を保存した中間版。
その後、表現不能な極端なsource時刻を無限ループせず拒否する入力防御を追加した。
最終検証は[report_r03](../cone_distance_report_r03/README.md)と
[cadence監査](../scene_cadence_audit_r01/README.md)を参照。

r04が使ったclockの完全コピーは `source_snapshot/scene_sampling_clock.py`、
SHA256は `cf9ab0707cebf658c55e6a33764f15751bc6c6cfcbea395c96700d62bd84afa3`。
元画像、CSV、数値、以前のsummaryは上書きしていない。
