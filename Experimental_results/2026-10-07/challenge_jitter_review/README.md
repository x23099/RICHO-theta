# 9/29 challenge間隔の揺らぎ：図示と原因の切り分け

作成日：2026-10-07。対象は2026-09-29 v11試験。既存bagを読み取り専用で再集計した。ROS送信・実機操作・本番変更・画像編集なし。

## 図

1. [challenge間隔と安定時間](challenge_interval_and_stability.png)
   - 上：ハンコン接続PC（発行元側）bagのchallenge記録間隔。
   - 中：Kobuki PC（受信側）bagのchallenge記録間隔。赤い点が60 ms超。
   - 下：当時のrelay診断に記録された連続安定時間と、安定待ちによるintent見送り。
2. [v11実記録とv12オフライン許可の比較](relay_gate_recorded_vs_offline.png)
   - active intent 27件に対し、v11記録ではcommand 12件、v12ゲートの過去bag再生では許可26件。
   - 実記録とオフライン判定の比較であり、同じ実験をv12実機で繰り返した比較、物理振動回数、通信遅延改善を示す図ではない。

## 元bagで確認できたこと

対象窓：2026-09-29 15:35:20.912～15:36:41.934 JST。
各PCで、元SQLiteのnanosecond記録時刻から連続challengeの差を取った。窓内先頭は直前の窓外messageからの差も計算する。各PCの時刻差を引き算した片道遅延ではない。

| bag記録間隔 | 発行元側：ハンコンPC | 受信側：Kobuki PC |
|---|---:|---:|
| 窓内challenge | 4,051 | 4,051 |
| 中央値 | 20.000 ms | 19.944 ms |
| p95 | 20.227 ms | 32.458 ms |
| 最大 | 21.014 ms | 129.436 ms |
| 60 ms超 | 0回 | 25回 |
| 200 ms超 | 0回 | 0回 |

50 Hzの目安は20 ms。発行元側ではほぼ周期的に記録され、受信側の記録では間隔が広がったり、短い間隔でまとまったりしていた。これにより「発行元の50 Hz timer自体が毎回大きく止まっていた」とする説明は支持されにくい。ただし発行元bagも発行callbackの直接計測ではない。

下段のrelay診断は歴史CSVを利用しているため横軸時刻はms丸め。上・中段の間隔は元bagのns精度を使用した。ms丸めCSVだけでは閾値付近の1件を落とし、60 ms超を24回と数えるため、25回の根拠は元bagとする。

## なぜ転送が止まっていたか：確認済みの設計上の原因

challengeはハンコンPCが発行する、commandの鮮度確認用token。relayは最近受け取ったtokenをcommandへ付け、adapterは自分が発行したtokenを照合する。カメラの各画像をchallengeのタイミングへ同期させる仕組みではない。

v11では、次の二つへ同じ60 msを使っていた。

- **個々のtokenの鮮度**：古いchallengeを使うcommandを拒否する。
- **challenge流の継続性**：受信間隔が60 msを超えると安定時間を0へ戻す。

さらに起動／再起動後の安定を1秒要求していた。そのため、約0.06～0.13秒の一時的なgapでも、新しいchallengeが戻った後に**もう1秒intentを見送る**。gapが繰り返されると待ち直しも繰り返され、録画窓の`receiver_challenge_stream_not_stable`が567件になった。これはFFBの強さではなく、relayがcommandを出す前の問題である。

v12はtoken鮮度60 msを維持し、stream断の基準だけ200 msへ分離した。60 msより古いtokenしかない瞬間は引き続き安全拒否する。新しいtokenが200 ms以内に戻れば1秒の再待機を発生させない。200 ms超の断やreceiver session変更では再安定化する。

既存オフライン再生ではactive許可26/27となり、残る1件はtokenが古いための正しい拒否だった。これは揺らぎを消した対策ではなく、短い揺らぎを長い転送停止へ増幅しない対策。

実装根拠：[relayの受信gap処理](../../../src/collision_ffb_relay.py)、[v12実装記録](../../2026-09-29/phase5_v12_reliability_implementation.md)、[元v11診断](../../2026-09-29/phase5_v11_reliability_dryrun_r01_diagnosis.md)。

## なぜ受信間隔が揺れたか：未確定

候補は、PC間ネットワークの待ち・再送、DDSのキュー／配送、受信PCのOSスケジューリング、カメラ処理やbag書き込みと共有するCPU／I/O負荷など。**今回のbagだけではどれが主因か切り分けられない。** 独立プロセスのrelayでもPC資源は共有する。

bag timestampはrecorderがmessageを記録した時刻で、relay callbackに入ったmonotonic時刻そのものではない。長いbag間隔すべてが、そのままrelayの同じ長さの受信gapだったとも断言しない。実際にrelayが安定待ちを繰り返したことは、別途記録された安定時間・理由が裏付ける。

この図の間隔は各PC内の差なので、2PCの時計が一定量ずれているだけでは説明できない。一方、bagのwall-clock補正の有無までこのデータで独立検証したわけではない。relay本体のgap判定はmonotonic時間を使う。

さらに原因を分けるなら、同じtokenに対する発行・relay callback受信・bag受信の時刻と、CPU/I/O・ネットワークの記録が必要。クロック同期だけを繰り返して解決したことにはしない。

## 再生成・来歴

```bash
/home/robo25/theta-env/bin/python3 \
  Experimental_results/2026-10-07/challenge_jitter_review/create_challenge_jitter_plots.py \
  --kobuki-archive /home/robo25/Downloads/K_rosbug_phase5_v11_reliability_kobuki_r01.tar.xz \
  --hsr-archive /home/robo25/Downloads/H_rosbug_phase5_v11_reliability_hsr_r01.tar.xz
```

`create_challenge_jitter_plots.py`は元診断のarchive SHAを要求し、既存の安全な展開関数で一時フォルダへ展開、SQLiteをread-onlyで読み取る。元bagは変更しない。challenge 4,051件／PC、受信側60 ms超25回、relay安定待ち567件を照合し、集計CSV・PNG・入力／出力SHAを保存する。仮想出力やROSノードを起動しない。

- `challenge_intervals.csv`：8,102間隔、元timestampと経過時刻。
- `recorded_relay_diagnostics.csv`：録画窓の記録済みrelay診断。
- `summary.json`：統計、対象窓、比較の出典、精度制約、入力／出力SHA。
- 上記2PNG：グラフ。カメラ生画像を編集したものではない。

両図を表示確認済み。Matplotlibの未使用3D機能警告は出るが、今回の2Dグラフ生成には影響しなかった。
