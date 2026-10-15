# 友人が使用した可能性のある参考動画の確認（2026-10-15）

## 結論

提出ZIPの動画は、**640×360の長方形の単一前方映像、屋外コース、低い撮影視点**だった。
THETAの1280×720 dual-fisheye二眼円形画像・室内撮影とは、画面構成と撮影環境の両方が異なる。
この差は前回の精度差の原因候補になるが、カメラだけ/背景だけの寄与を分離した比較ではない。
型番・光学モデル・カメラ校正・友人が実際に学習に渡した画像の形式は、このZIPからは特定できない。

**この動画を学習元と確定して扱わない。**
`cone.pt`内部の保存日時は2026-09-21T22:57:24+09:00。
今回の`camera_stamps.csv`のstampは2026-10-12 15:51:11.682744～16:02:17.401582 JST。
両方の時刻が正しければ、この動画そのものは当該checkpointの学習には使用されていない。
友人の推論試験/撮影環境の例、または別日動画と似た撮影条件である可能性はあるが、未確認。
metadataの日付だけを根拠に時計の正確性や学習dataの来歴を証明しない。

代表12枚へ友人modelの推論も実施したが、confidence0.25以上は0枠だった。
これは画像12点だけの出力数であり、動画全体のRecall0%、モデルの故障、THETA以外でも利用不可能という意味ではない。
現在進めている自作候補による静止距離試験は継続し、友人modelを本番採用する変更はない。

## 受入れ・デコード

| 項目 | 確認結果 |
|---|---|
| ZIP | `/home/robo25/Downloads/video-20261015T041958Z-1-001.zip`、約102MiB |
| ZIP SHA256 | `8fb8c82c6a92269be22ef888b56083d04ec8f1bc878d710c139a0c49765b2cb6` |
| 中身 | `video/camera.mp4`、`camera_stamps.csv`、`camera_ffmpeg.log`の3ファイル |
| video | H.264、640×360、全9,746frameデコード成功 |
| stream duration | 665.72秒、約11分6秒 |
| average frame rate | 22150/1513 ≈14.64 fps。要求/実時間の一定fpsを証明する値ではない |
| timestamp CSV | 9,746行、frame index0～9,745連続。動画のframe数と一致 |
| stamp/receive | どちらも有限・狭義単調増加。非増加区間0 |
| 保存画像 | 全区間から等frame間隔で12枚。640×360のままPNG保存、画素hash一致 |
| 原本の保管 | `recordings/2026-10-15_friend_video_intake_r01/`。Git対象外 |

ZIPの正確な3パスだけを許可し、リンク・暗号化・余分なpath・512MiB超を拒否して展開した。
同梱logやCSVの内容はデータとして読み、コマンドとして実行していない。
MP4 headerに`nb_frames`がなく、初回のmetadata取得はそこで停止。原本を上書きせずZIPとのhash一致を確認して再利用し、`ffprobe -count_frames`の実デコード件数で再開した。
ffprobeとOpenCVの双方で9,746frameを確認。新しい推論画像はcrop/resize/overlay/色補正をせず、元フレーム全体を保持。
OpenCVによる自動回転も無効にし、streamのnative width/heightと照合した。

原logにはdeprecated pixel format、non-strictly-monotonic PTS、non-monotonous DTSの警告がある。
**CSVのstamp自体は今回単調だった**ので、PTSの警告とCSVの逆行を混同しない。
動画コンテナの時刻とstamp/receiveの関係は未検証。距離/TTC/FFB遅延の正解には転用しない。
sample manifestの`time_sec`はframe index/平均fpsによる便宜上の値で、実際のcapture timestampは別の`stamp_sec`に保存した。

根拠：[intake_summary.json](intake_summary.json)、[ffprobe.json](ffprobe.json)、[raw_sample_manifest.csv](raw_sample_manifest.csv)。

## 原画像の所見とTHETAとの差

12枚を目視。白線・緑色路肩・アスファルト・空・建物・人物・遠方の赤系コーン/誘導物などが写る。
全動画の目視、コーン全数のbbox annotation、人によるGT確認は実施していない。
細く小さい誘導物を全て同じtraffic_cone classと断定しない。

| 比較点 | 今回の動画 | 自分の主なTHETA録画 |
|---|---|---|
| 画面 | 640×360、単一の前方シーン | 1280×720、前後2つの円形画像と黒い周辺領域 |
| 場所・背景 | 屋外コース、路面・空・建物 | 室内、棚・机・窓・床の反射など |
| 対象の大きさ | 代表点では遠方の小さい対象が多い | 床置き近距離、持ち運び、画角端などを含む |
| 光 | 日光、逆光、長い影 | 主に室内照明・窓からの光 |
| モデル入力前の処理 | 実際の友人pipelineは未提供 | 記録した全画角をrect=falseの固定条件で推論 |

「魚眼ではないカメラ」「同じコーンが何m先にある」といった光学・幾何の断定はしない。
表示形式が違うことは確認できるが、カメラ型番の違い自体が原因という証明ではない。

代表画像（各リンクは無加工の全フレーム）：

- [frame1：前方の屋外コース](raw_samples/camera_f000001.png)。
- [frame1772：人物・建物付近](raw_samples/camera_f001772.png)。
- [frame4430：遠方の赤系の小物体](raw_samples/camera_f004430.png)。
- [frame5316：走路脇の誘導物](raw_samples/camera_f005316.png)。

## 代表12枚のオフライン推論

既存のRTX3070環境を使用。batch1、FP32、rect=false、NMS IoU0.7、診断用floor0.01、保存画像なし。
ネット取得・外部loggerを無効化。GPU/driver/venvを変更しない。
画像の推論内部でのletterbox/resizeと、保存原画像の加工は区別する。保存PNGのhashは推論後も一致。

友人モデルは、前日に安全確認・hash固定したtensor-only checkpointから、インストール済みのYOLO11nを新規構築し全stateをstrict=Trueで読込。
友人の元serialized moduleを実行せず、`weights_only=False`にも切り替えない。
class0の`cone`を比較用に`traffic_cone`と対応させるだけで、再学習や他classの追加はない。

| profile | imgsz | confidence≥0.25の合計枠 / 出力画像 | confidence≥0.50の合計枠 / 出力画像 | floor0.01以上の最大score |
|---|---:|---|---|---:|
| 友人 | 640 | 0 / 0枚 | 0 / 0枚 | 0.14482 |
| 友人 | 960 | 0 / 0枚 | 0 / 0枚 | 0.01133 |
| 自作36枚版 | 960 | 6 / 4枚 | 2 / 1枚 | 0.63360 |

これはTP/FP/FNの表ではない。正解bboxがないので「自作が友人より高精度」という比較はできない。
自作36枚版の0.50以上2枠はframe1772の建物側の小領域に出ており、それをコーン正解と確定していない。
THETAの正面で有望な候補も、未検証の屋外前方映像へそのまま汎化すると保証しない。

友人640のframe4430にはscore0.14482/0.07697/0.06514の候補があり、bbox高さは約8～9pxだった。
小さい対象が多いことや推論サイズの影響は考えられるが、対象の正解/元の推論処理/学習来歴がない以上、原因は確定しない。
0.25から単純に閾値を下げる本番変更はしていない。

同じモデルでも、THETAの既存E画像では前日に20/32のhuman bboxへ対応（960/0.25）していた。
今回の代表画像では0.25以上0枠なので、「THETAのカメラだけが原因で検出できない」という説明では不十分。
ただし異なる画像群・対象サイズであり、カメラ以外が主因だと証明する結果でもない。

根拠：[各画像の出力数](inference_r01/sample_detection_counts.csv)、
[友人640の予測](inference_r01/friend_640/predictions.csv)、[友人960の予測](inference_r01/friend_960/predictions.csv)、
[自作36枚版の予測](inference_r01/own36_960/predictions.csv)、[推論来歴](inference_r01/provenance.json)。

## 現在の判断

1. 提供動画は撮影環境差を確認する資料として保管する。学習元・独立testとしては登録しない。
2. コーンの新しい学習データに自動追加しない。予測を正解ラベルとして採用しない。
3. 友人モデルを即座に捨てたり本番採用したりせず、必要なら将来、実際の入力前処理と学習/検証データの対応を調べる。
4. 今はユーザーが優先した[自作候補の床置き静止距離試験](../cone_static_distance_capture_procedure.md)を続ける。
5. camera intrinsicsが異なるこの640×360へ、THETA用の距離投影やFFB経路を流用しない。

確認は全frameデコード、12点の原画像目視、同じ12点×3条件のGPU推論まで。
実距離・全frameの認識精度・友人の元pipeline再現・実機FFBは未実施。
入力ZIP/動画/CSV/ログ、model/原PNGのhash保持、native geometry、strict state load、Python構文を確認。
既存コーン関連179件PASSは直前の成功を再利用し、変更のない本体へ再試験を繰り返していない。
本体の検知/ROS/FFBコード、設定、datasetレビューは変更しない。Git commit/pushは今回依頼されていないため未実施。
