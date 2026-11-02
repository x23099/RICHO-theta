# 同一録画の過去姿勢で作る固定床：連続実画像での比較

作業日: **2026-11-02**。今日は撮影できないというユーザー回答を受け、既存録画だけで実施した。実機、GPU推論、通信、ROS/FFB、モデル学習、内部校正変更、Git commit/pushは行っていない。作業中の赤のみ評価フォルダ/テストは未変更。

## 結論

**既存の連続実画像1,547フレームで、同じ録画の過去4枚から作った固定床モデルを、完成後の画像だけへ適用できた。**

| 経路 | 条件付き出力frame数 | 数値の種類 |
| --- | ---: | --- |
| 元の背景姿勢・元の支持点 | 326 | paper7方位の前方成分 |
| 固定床・元のunion支持点（対照） | 1,107 | カメラ鉛直足元からの水平距離 |
| 同じ固定床・補完支持点 | 1,120 | 同じ定義の水平距離 |

固定床同士では、両方出力1,107、補完側のみ13、union側のみ0。**支持点候補の違いに対応する追加出力は13件**だった。326→1,120の全差を補完の効果とはしない。固定床を保持する仮定や元の動的sceneゲートとの違いも含む。

共通1,107件の水平距離は1,003件で完全一致、104件で差があり、差の最大は約3.83 cm（中央値0、p95約3.74 cm）。これは同じ固定床に異なる支持点を入れた**推定値同士の差**であり、真値からの誤差ではない。どちらが正しいかはこの比較だけでは認定しない。根拠は`frame_comparison.csv`の共通出力行。

これは**成功が既知の過去sessionを使った開発用・録画後の配線検証**。現在の学校PCで距離が出た、絶対距離が正しい、新しいholdoutへ一般化した、という結果ではない。出力件数は正解数・表示時間率ではない。

## 前回から何を進めたか

10/30は、別sessionのモデルを拒否できることと、合成画像で比較距離が出ることを確認した。同じ紙sessionの2画像は連続3フレームの確認に足りず保留だった。

今回は十分な連続画像がある10/15の床→コーン系列を使い、**別録画の法線を無条件に貼り付けず、その録画で先に得た姿勢だけから固定床候補を作る**対照を追加した。元の実行系の動作は変更せず、オフライン解析adapterとして使用した。

## 入力と出所

- session: `floor_cone_same_pose_r01_20261015_160621_378`。
- 原動画: `recordings/2026-10-15_floor_cone_same_pose_intake_r01/`内の同名sessionの`raw.avi`。
- 保存YOLO: `Experimental_results/2026-10-15/floor_cone_same_pose_analysis_r01/inference_r01/`。
- 元のsceneスケジュール: `Experimental_results/2026-10-26/cone_distance_replay_r05/declared_central_scope/scene_jobs.csv`。
- bbox・信頼度・画像は新たな推論や人手枠に置換していない。`load_saved_run`で原動画/metadata/CSVのhash、全frame・時刻・検出件数・重み/推論条件を照合した。
- native1280×720を1枚ずつ復号して処理。画像の保存加工・切抜き・縮小・注釈はなし。入力配列も各frameで処理前後hash一致を確認した。
- ROIは以前と同じ`(270,0,350,720)`。範囲外を監視する本番の全画角検証ではない。

## 過去限定の床モデル作成

| 項目 | 内容 |
| --- | --- |
| 学習姿勢の元frame | 62、152 |
| 後の確認姿勢の元frame | 272、302 |
| 最後の根拠frame | 302 |
| 論理上の計算完了 | 10.178240297秒 |
| 固定床を渡せる最初のquery | frame306、元時刻10.190310秒 |
| 実際に最初の比較距離が出るframe | 350（モデル完成後も支持点・品質を要求） |
| 法線 | `[-0.0203898612,-0.9941040205,0.1064962445]` |
| 高さ | **0.59 mの外部入力**。録画から新たに推定した値ではない |

最初に`PastOnlyPose`の既存2枚学習＋2枚検証が成立したときにだけモデルを凍結した。後の距離値やnominalラベルで時点・法線・高さを選んでいない。元の高さ・heading referenceは既存configの条件付き根拠を引き継ぎ、その来歴と仮定をbundleへ記録する。

以後、モデルを作る根拠より前のframeや計算完了前の画像へ比較距離を出さない。frame1～305は`bootstrap_not_ready`のまま保持。元のscene採否・方向計算は同じコードで52標本を再計算し、元スケジュールの採否/理由と52/52一致した。

**固定姿勢を保持できるという仮定は独立確認されていない。** 後の背景が拒否されても固定床比較は保持するため、元の毎秒scene確認とは別の実験条件。カメラ移動・取り付け変化を安全に見逃さないことを実証した処理ではない。別session・現在の実カメラへこのbundleを転用しない。

## 欠測・品質・本判定との分離

| 補完側の比較理由 | frame数 |
| --- | ---: |
| bootstrap_not_ready | 305 |
| support_point_unavailable | 74 |
| image_support_quality_not_confirmed | 48 |
| unverified_comparison_only | 1,120 |
| 合計 | 1,547 |

- モデル完成後も各支持列を既存品質ゲートで3フレーム確認。点なしを0 m・前回値・未来値で補わない。
- union対照も同じモデル、同じ外部高さ、同じframe/時計で比較し、支持点の違いだけを分離した。
- 比較フィールド追加前後で、元の判定フィールドは全1,547行一致。実行系`src/`は変更していない。
- 元の前方距離と固定床の水平距離は異なる量。同じ数値として引き算して「誤差改善」とは呼ばない。
- `physical_metric_verified=false`、`usable_for_ffb=false`を維持。姿勢・接地点・絶対距離を検証した成功数ではない。

## 時計・保存ログの制限

scene完了にはr05で保存した計算完了時刻を使う。支持点/比較は全frameとも元時刻+10 msの論理時計を与える。これは現在のGPU負荷、リアルタイムFPS、通信遅延の測定・保証ではない。sceneを待たずに未来の姿勢を使うことを防ぐための機能再計算である。

録画後の派生JSONLであり、`inference_source`を保存検出利用と明記。実機の正常終了を偽装するlive_summaryは作らない。標準reportの`INCOMPLETE_CAPTURE`は、元録画が壊れているという判定ではなく、この再計算を実機の成功ログにしないための区別。

## 正式結果と検証

正式版は`results_r02/`。r01にunion支持点対照・frame証拠を追加したもので、既存の本番抽出条件を変更した版ではない。

- [全frame比較CSV](results_r02/frame_comparison.csv)
- [bootstrap床モデル](results_r02/bootstrap_models.json)
- [scene再構築CSV](results_r02/scene_reconstruction.csv)
- [summary・入力/コードhash](results_r02/summary.json)
- [条件付き距離と出力有無の時系列図](results_r02/conditional_range_timeline.png)（数値から生成した図）
- [検証JSON](verification_r01/verification.json)、[テスト一覧](verification_r01/tests.csv)、[テストログ](verification_r01/tests.log)

**関連283テストPASS、失敗0・エラー0・skip0（新規12件＋前回関連271件）。** 未来frame/未来完了の参照拒否、4枚未満の拒否、後の姿勢変化が凍結済み値を書き換えないこと、session契約、prefixへの未出力を追加試験した。最初の新規テストで非単位の合成ベクトルを渡して失敗したため、正しい単位ベクトルに直して再実行した。実装の方向条件を緩めて通したものではない。

`src/`の追跡済みPython/JSON/shellは基準`ccf5665`から変更0。元動画・保存推論・校正・入力source hashも一致。ログにある故障注入のエラー表示は、失敗/エラー件数とは別。作業中の赤のみ評価は試験集合からも外した。

## 次に必要なこと

今回、固定床の数値経路が実画像の連続入力でも成立することは確認できた。一方、現在の学校映像は背景6平面が成立していないため、この過去録画のbootstrap成功をそのまま使えない。

さらに、受信側は接続時にsession IDを新規生成する一方、固定床bundleは起動前に読む設計である。今の実装では、同じカメラでも再起動でIDが変わり、昔のbundleは拒否される。

次は[同じ接続内で床モデルを確認・読み込む設計](next_live_model_lifecycle.md)を進める。これは現在のsession拘束を名前だけで回避する設計ではない。今日は撮影や操作を求めず、モデル再利用の物理根拠と、同session内の読み込み手順を分けて準備する。

## 再現

元録画と保存推論がある解析PCで、新規出力先を指定する。GPU・学校PC・ハンコンは不要。

```bash
cd /home/robo25/theta_ws/RICHO-theta
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-02/fixed_floor_contiguous_replay_r01/run.py --output-dir Experimental_results/2026-11-02/fixed_floor_contiguous_replay_r01/results_r03
env OPENBLAS_NUM_THREADS=1 /home/robo25/theta-env/bin/python3 Experimental_results/2026-11-02/fixed_floor_contiguous_replay_r01/verify.py --results-dir Experimental_results/2026-11-02/fixed_floor_contiguous_replay_r01/results_r03 --output-dir Experimental_results/2026-11-02/fixed_floor_contiguous_replay_r01/verification_r02
```

`recorded_comparison/`、`recorded_union_control/`のJSONLは大容量の再生成可能なローカル派生ログ。将来Git整理時は生録画と同様に対象から外し、小さい集計・コード・hashを保存する。今回commit/pushは依頼されておらず未実施。
