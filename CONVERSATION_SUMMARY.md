# RICOH THETA 360°環境認識プロジェクト 会話・作業引き継ぎ

## 文書の目的

この文書は、Codexとの会話で確認したプロジェクトの目的、GitHub調査結果、現在の実装評価、設計判断、実施済み変更を別PCへ引き継ぐための要約である。

会話セッションID：`019fcacf-5750-7fe3-94fd-e37c5e6bbc83`

> セッションIDは共有URLや復元キーではない。ローカルCodexの会話は基本的に実行したPCに保存されるため、別PCへの確実な引き継ぎには、本ファイルとGitリポジトリを使用する。

---

## 1. ワークスペースでは何を開発しているか

### ユーザーの質問

このワークスペースで行われているプロジェクトをまとめ、分かりやすく説明してほしい。

### 回答の要約

本プロジェクトは、RICOH THETA Sの360°映像を使ってKobukiまたはAI-FORMULA機体を遠隔操縦し、周囲環境を俯瞰表示するシステムである。

最終的には、LiDARやGPSに依存せず、カメラ映像を中心としてTesla FSD風のリアルタイム環境マップを生成することを目指している。

主要機能は次のとおり。

- THETAのデュアル魚眼映像取得
- 前方・後方・左右ミラー・BEVへの再投影
- WebRTCによる低遅延映像配信
- ROS 2テレメトリのWebRTC DataChannel転送
- G923による遠隔操縦
- 速度、ギア、バッテリーなどのUI表示
- 予測走行経路の描画
- 白線検出
- オドメトリ連動の局所地図蓄積

### 現行の主要ファイル

| ファイル | 役割 |
|---|---|
| `src/webrtc_stream.py` | ロボット側の映像・テレメトリ送信 |
| `src/webrtc_receive_ui.py` | 操縦PC側の受信・表示・操作 |
| `src/handle.py` | G923入力とROS 2操作指令 |
| `src/bird_eye.py` | BEV、白線検出、地図蓄積、AI認識の実験環境 |
| `src/bird_eye_config.json` | カメラ投影・車体・白線検出の設定 |
| `src/zc33s_ui.py` | 従来の統合ドライバーUI |
| `src/start_theta_stream_rtc.sh` | WebRTC送信側起動スクリプト |
| `src/start_theta_receive_rtc.sh` | WebRTC受信側起動スクリプト |

---

## 2. 最終的に作りたいもの

### ユーザーの説明

360°カメラ1台の映像から、Tesla FSDの表示に近いものを作りたい。

具体的な目標は次のとおり。

- 俯瞰映像の表示
- FSD風の道路・白線・障害物地図生成
- 障害物に応じたForce Feedback（FFB）
- 障害物の危険度に応じた予測経路の色変更
- 最初はKobukiで検証し、最終的にはAI-FORMULA機体へ搭載

### 必要になる処理構成

```text
360°カメラ映像
  ↓
パノラマ／複数方向の透視画像生成
  ↓
物体検出・Semantic Segmentation
  ↓
深度または接地点の推定
  ↓
BEV上の実座標へ変換
  ↓
物体追跡・静的地図蓄積
  ↓
予測経路との衝突判定・TTC計算
  ├─ 経路色の変更
  ├─ 警告表示
  └─ FFB指令
```

---

## 3. 類似するGitHubオープンソースの調査

### ユーザーの質問

自分の目標に近いGitHubオープンソースを探し、そこで発生した問題、解決方法、依存関係を詳しくまとめてほしい。コード修正はまだ行わない。

### 調査結果

#### 3.1 Dur360BEV

- GitHub: <https://github.com/Tom-E-Durham/Dur360BEV>
- 論文: <https://breckon.org/toby/publications/papers/e25bev.pdf>
- データセット: <https://huggingface.co/datasets/TomEeee/Dur360BEV>

今回の目標に最も近い研究である。実車に搭載した単一360°カメラから、自動運転向けBEV意味地図を生成する。

解決している問題：

- 複数カメラの同期と外部キャリブレーションの複雑さ
- 球面画像特有の位置依存歪み
- 背景・道路に対して白線などが少ないクラス不均衡

解決策：

- 単一球面カメラへ統合
- SI2BEVによる球面画像専用の特徴サンプリング
- 適応的Focal Lossによる少数クラス重視

注意点：

- 推論時はカメラのみでも、学習用正解データの生成にはLiDAR、RTK GNSS/INS、OpenStreetMapを利用する。
- RICOH THETAや現在の屋内テープコースへ直接適用できる完成アプリではない。
- 時系列追跡、FFB、Tesla風UIは別途必要。

#### 3.2 OneBEV

- GitHub: <https://github.com/JialeWei/OneBEV>
- 論文: <https://openaccess.thecvf.com/content/ACCV2024/papers/Wei_OneBEV_Using_One_Panoramic_Image_for_BirdAos-Eye-View_Semantic_Mapping_ACCV_2024_paper.pdf>

1枚のパノラマ画像から道路環境のBEV意味地図を直接生成する。

解決策：

- 複数カメラではなく単一パノラマを入力
- Mamba View Transformationでパノラマの歪みを考慮してBEV特徴へ変換

注意点：

- `nuScenes-360`などの研究用パノラマと実THETA映像にはDomain Gapがある。
- スティッチ境界、露出差、カメラ高、屋内コース環境への再学習または適応が必要になる可能性が高い。

#### 3.3 360BEV / 360Mapper

- プロジェクト: <https://jamycheung.github.io/360BEV.html>
- GitHub: <https://github.com/jamycheung/360BEV>

単一360°パノラマと深度情報から屋内BEV意味地図を生成する。

解決策：

- 幾何学的なInverse Radial Projectionで初期位置を求める
- 360Attentionでスティッチ・投影誤差を学習的に補正
- 深度マスクで有効地図領域を制約

注意点：

- 屋内建築空間向けである。
- RGB画像だけでなく深度入力を必要とする。
- 道路、白線、車両向けにそのまま使用できない。

#### 3.4 stella_vslam

- GitHub: <https://github.com/stella-cv/stella_vslam>
- ROS連携: <https://github.com/stella-cv/stella_vslam_ros>

BEV意味地図ではなく、カメラ移動量と自己位置を推定するVisual SLAMである。

有用な点：

- Perspective、Fisheye、Equirectangularへ対応
- RICOH THETAシリーズの利用例がある
- 地図保存と再ローカライズに対応
- 360°映像では特徴点を長時間観測しやすい

制約：

- 疎な特徴点地図であり、道路・白線・障害物の意味は持たない。
- 単眼SLAMには絶対スケールの曖昧性がある。
- 動的物体や模様の少ない床で追跡が不安定になる可能性がある。

#### 3.5 pySLAM

- GitHub: <https://github.com/luigifreda/pyslam>

単眼・ステレオ・RGB-D SLAM、深度推定、Semantic Segmentation、3D voxel意味地図、物体単位の意味統合を含む研究フレームワークである。

参考になる点：

- フレームごとの意味ラベルを多数決または確率的に統合
- 物体IDを時系列で安定化
- 3D物体バウンディングボックス表示

制約：

- Python/C++、PyTorch、CUDA、複数モデルなど依存が重い。
- THETAの正距円筒画像への対応はstella_vslamほど明確ではない。

### 調査から得た結論

| 目的 | 参考候補 |
|---|---|
| 単一360°画像からBEV意味地図 | Dur360BEV |
| パノラマから学習型BEV変換 | OneBEV、360Mapper |
| 360°カメラ自己位置推定 | stella_vslam |
| 時系列Semantic Map | pySLAM |
| 360°単眼深度 | Depth Any Panoramasなど |
| Tesla風UI・FFB | 本プロジェクト側で統合実装 |

---

## 4. YOLO導入後の`bird_eye.py`評価

### ユーザーの質問

別PCで`bird_eye.py`へYOLOを導入した。最新版を踏まえ、最終目標へどう進むべきか。

### 確認した実装

直近コミットでは次が追加されていた。

- YOLOv8n/s/mモデル
- Ultralytics YOLO読み込み
- モデル切り替えUI
- 信頼度0.25での物体検出
- Tesla風ワイヤーフレーム表示
- PyTorch 2.6以降のモデル読み込み対策

### 発見した主要課題

#### YOLOへの入力位置

現状は床面へBEV変換した画像に標準YOLOを適用している。COCO学習済みYOLOは通常の透視画像を想定しているため、BEVで放射状に引き伸ばされた人物・パイロンなどの検出には不利である。

推奨順序：

```text
THETA画像
  → 前・左・右・後の透視画像
  → YOLO
  → 検出物の接地点をBEVへ投影
```

#### 3D Boxの意味

現状の3D Boxは2D矩形を上方向へずらして描いたワイヤーフレームであり、実際の距離・高さ・向き・3D位置を推定していない。

最初に必要なのは完全な3D Boxではなく、障害物の地面上の位置 `(x, y)` である。

#### 重複推論

現状は`bev_img`と`lane_mask_visual`の両方へYOLOを適用している。白線マスク画像へのYOLO推論は有効性が低く、計算量と誤検出を増やす可能性がある。

#### GUIブロック

YOLO推論がQt GUIスレッド内で同期実行されている。将来はAIワーカースレッドへ分離し、古いフレームをキューに蓄積せず最新画像だけを処理する必要がある。

#### 依存関係

`torch`と`ultralytics`を使用しているが、実行環境によっては未導入で起動できない。AIなしでもBEV調整を継続できる設計が必要である。

### 推奨する実装順序

1. 固定テスト映像と評価指標を準備
2. YOLOをBEV画像ではなく透視投影画像へ適用
3. 2D矩形またはマスクの接地点をBEV実座標へ変換
4. 実測点を使って距離誤差を評価
5. THETA専用データを収集して再学習
6. BEV座標上で物体追跡
7. 地図を静的・動的・走行可能領域などに分離
8. 予測経路との交差判定とTTC計算
9. 経路色変更
10. 仮想FFB値をログで検証
11. 弱いFFBから実機試験
12. AI処理をワーカースレッド化
13. WebRTC受信UIへ統合
14. 必要になった段階でVisual SLAMを追加

---

## 5. Kobuki固定ではなくAI-FORMULAへ移行可能にする変更

### ユーザーの説明

- 現在のTHETA搭載高は約40 cm
- Kobukiの車幅は約35 cm
- 一旦はKobukiで検証する
- 最終的には添付卒業論文に記載されたAI-FORMULA機体へ搭載する
- Kobuki専用の設計にはしたくない

参照PDF：`/home/robo25/Downloads/卒業論文_最終版_鳴田瀬名 (1).pdf`

### PDFから確認した事項

- AI-FORMULA機体は左右独立駆動の差動二輪方式
- 従属輪を持つ
- 機械的なステアリング機構を持たない
- 左右駆動輪の回転速度差で旋回する
- 最高時速30 km/hを目標とする
- G923を用いたテイクオーバー、車体挙動同期、FFBが研究対象

PDF内では、車幅・全長の数値仕様を確認できなかった。このため、写真から推測した寸法を固定値として採用しない方針とした。

### 実施したコード変更

#### 車体プロファイル

`bird_eye.py`へ以下を追加した。

- `Kobuki (354 mm circular)`
- `AI-FORMULA (use measured dimensions)`
- `Custom vehicle`

Kobukiプロファイル：

- カメラ高：`0.40 m`
- 車幅：`0.354 m`
- 全長：`0.354 m`
- 形状：円形

AI-FORMULAプロファイル：

- 形状：矩形
- 車幅・全長・カメラ高：実機の実測値を入力
- 未確認寸法を自動設定しない

#### UI

- `Kobuki Silhouette Offset`を`Vehicle Geometry & Camera Offset`へ変更
- 車体プロファイル選択を追加
- 車幅と全長を別々に調整可能に変更
- カメラの左右・前後オフセットを継続して調整可能

#### 描画

- Kobukiは円形フットプリント
- AI-FORMULAは矩形フットプリント
- 車体幅と全長に合わせて車体表示、境界線、車輪、進行方向表示を更新
- 予測経路の幅は設定された車幅を使用

#### 設定ファイル

`src/bird_eye_config.json`の現在値：

```json
{
    "camera_height": 0.4,
    "scale": 0.024,
    "vehicle_profile": "kobuki",
    "footprint_shape": "circle",
    "car_width": 0.354,
    "car_length": 0.354
}
```

#### PyTorchのオプション化

PyTorch未導入環境では、以前は`import torch`でプログラム全体が停止していた。現在は警告を表示してAI機能のみを無効化し、BEVキャリブレーション画面を起動できる。

### `scale`について

`scale = 0.024 m/px`は車体寸法ではなくBEV画像の空間解像度である。

500×600 pxのBEVでは、概算表示範囲は12×14.4 mになる。Kobuki専用値ではないため、今回の変更では維持した。

ただし、実測による校正が必要である。床に1 m間隔の基準点を置いた場合、`0.024 m/px`ならBEV上で約41.7 pxになることを確認する。

### 検証結果

- `python3 -m py_compile src/bird_eye.py`：成功
- `python3 -m json.tool src/bird_eye_config.json`：成功
- `git diff --check`：問題なし
- PyTorchなし・Qt offscreen・モックカメラでのGUI継続起動：成功
- YOLO実推論：検証PCにPyTorchがないため未実施

### Gitの状態

車体プロファイルと設定値の修正は、コミット`8216f45`（`codexでの修正`）に含まれている。

本会話要約を作成した時点で未コミットなのは、本ファイル`CONVERSATION_SUMMARY.md`のみである。

---

## 6. AI-FORMULA搭載前に必要な実測

以下の値を実機で測定する。

- 車体最大幅
- 車体全長
- 地面からTHETA光学中心までの高さ
- 車体中心からカメラまでの左右オフセット
- 車体中心からカメラまでの前後オフセット
- 左右駆動輪間距離（トレッド）
- 車体外形に追加する安全マージン

カメラの「高さ」は筐体下端ではなく、THETAの実効光学中心までを測定する。

---

## 7. 別PCへの引き継ぎ

### セッションIDについての質問

セッションIDを使えば別PCでこの会話を閲覧できるか。

### 回答

セッションIDだけでは別PCで会話を開けない。IDは識別子であり、共有URLや復元キーではない。

ローカルCodexの会話と未コミットファイルは、そのPCに残る。別PCへ確実に移すには次を行う。

1. 変更内容を確認する。
2. 本ファイルを含めてGitへコミットする。
3. リモートリポジトリへpushする。
4. 別PCでpullする。
5. Python、ROS 2、PyTorch、Ultralyticsなどの実行環境は別途構築する。

Gitで共有されるのはリポジトリ内のファイルだけであり、以下は自動共有されない。

- 仮想環境
- インストール済みPythonパッケージ
- `/dev/video*`などのデバイス設定
- ROS 2ワークスペース
- 未追跡・未コミットファイル
- Codexのローカル会話履歴

---

## 8. 次回作業の推奨開始点

次回は、車体形状の追加修正よりも、YOLO検出結果を実際のBEV座標へ変換する処理を優先する。

推奨する最初の小目標：

1. THETA画像から前・左・右・後の透視画像を生成する。
2. 各透視画像へYOLOを1回ずつ適用する。
3. 検出矩形下辺中央またはSegmentationマスク下端を接地点とする。
4. 接地点を車体基準のメートル座標へ変換する。
5. BEV画面へ一定半径の障害物として描画する。
6. 実測した障害物位置と比較し、距離誤差を記録する。

この段階では見た目だけの3D Box、FFB、Visual SLAMを同時に実装しない。まず障害物位置の正確性を確立する。
