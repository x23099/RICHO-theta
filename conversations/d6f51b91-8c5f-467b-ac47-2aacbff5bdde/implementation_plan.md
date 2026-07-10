# birds_eye_view 実装計画 (ROS 2 Humble)

本計画は、ユーザーが指定した `theta_ws` 内のプログラムおよび `zc33s_ui.py` をベースにし、作業ディレクトリ `birds_eye_view` において、ROS 2 Humble 環境で動作する「Kobuki向け俯瞰映像＋走行予測線表示システム」を構築するための手順です。

---

## 主な変更・設計方針

1. **作業ディレクトリ**:
   `/home/robo25/.gemini/antigravity/scratch/birds_eye_view` を作成し、関連ファイルをコピー＆改修します。
2. **ベースコードの継承**:
   `/home/robo25/theta_ws/RICHO-theta/src/` にある `zc33s_ui.py` および通信関連プログラム（WebRTC等）をベースとして利用します。
3. **BEV（俯瞰）映像上への予測線描画の追加**:
   * 現行の `zc33s_ui.py` は、正面映像 (`front_view`) にのみ予測線を描画しています。これを `BEVVideoLabel` (俯瞰表示) にも描画できるように拡張します。
   * BEVは真上から見た映像（平面）であるため、透視投影（パースペクティブ）の補正は不要で、オドメトリ座標（$x$: 前方, $y$: 横方向）から画素座標へのシンプルな線形変換（拡大縮小・回転・平行移動）で描画可能です。
4. **Kobukiの車体モデルへの最適化**:
   * 現行の `BEVVideoLabel` で描画されている車体は、スイフトを模した角丸矩形（幅42px, 長さ86px）になっています。
   * これを Kobuki の形状（直径約35.4cmの円形）に変更し、BEVのメートル画素スケールと一致させます。

---

## 開発ロードマップと実装手順

### フェーズ 1: ディレクトリ作成とベースコードの複製
* **[NEW] Directory [birds_eye_view](file:///home/robo25/.gemini/antigravity/scratch/birds_eye_view)**
* `theta_ws` から `zc33s_ui.py` や必要なストリーミングスクリプトを複製します。
* 複製先:
  * **[NEW] [birds_eye_view_ui.py](file:///home/robo25/.gemini/antigravity/scratch/birds_eye_view/birds_eye_view_ui.py)** (コピー元: `zc33s_ui.py`、これをKobuki/BEV用にカスタマイズ)
  * **[NEW] [webrtc_stream.py](file:///home/robo25/.gemini/antigravity/scratch/birds_eye_view/webrtc_stream.py)** などの通信用モジュール

### フェーズ 2: BEV描画クラス `BEVVideoLabel` の改修
* `birds_eye_view_ui.py` の `BEVVideoLabel` を改修し、予測経路を重畳表示できるようにします。
* **主な改修内容**:
  * `paintEvent` の中で、`OdomSpeedNode` から予測軌跡ポイント `predict_path_points` を取得。
  * メートル単位の座標 $(x, y)$ を、BEV表示のピクセル座標にマッピング。
    * スケールファクタ（例: 1mあたり何ピクセルか $S_{px/m}$）を定義。
    * 自車中心位置（画像中心）を原点とし、上方向を前方に変換。
  * 半透明の青い帯（Kobukiの車体幅を考慮した太さ）を描画します。
  * 車体アイコンを、角丸矩形から Kobuki の円形（実寸スケールに合わせた半径）に描き換えます。

### フェーズ 3: 動作検証とパラメータ調整
* `birds_eye_view_ui.py` を起動し、映像が受信できていることを確認します。
* ダミーの `cmd_vel` または `odom` データを配信し、旋回時・直進時に予測線が正しく円弧を描いて表示されるかを検証します。
* Kobukiの実機がある場合は、オドメトリの変化に同期して予測線が滑らかに追従するかを確認します。

---

## 検証プラン

### 1. パラメータの確認と描画テスト
* 実装した `birds_eye_view_ui.py` を実行（モックまたはログ映像を使用）し、車体幅に合わせた予測帯が、直進・左右旋回において歪みなく表示されるか目視確認します。

### 2. ROS 2 Humble トピック購読テスト
* `odom` トピックの速度情報が正しく取得され、予測線計算に反映されているか、ログ出力等で検証します。
