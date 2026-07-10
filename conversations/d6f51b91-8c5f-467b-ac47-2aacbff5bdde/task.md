# birds_eye_view 開発タスク

- [x] **フェーズ 1: ディレクトリ作成とベースコードの複製**
  - [x] 作業ディレクトリ `/home/robo25/.gemini/antigravity/scratch/birds_eye_view` の作成
  - [x] `/home/robo25/theta_ws/RICHO-theta/src/zc33s_ui.py` を `birds_eye_view_ui.py` として複製
  - [x] 必要に応じて関連プログラム（webrtc_stream.pyなど）も複製
- [x] **フェーズ 2: BEV描画クラス `BEVVideoLabel` の改修**
  - [x] `BEVVideoLabel` にオドメトリからの予測軌跡を取得する処理を追加
  - [x] 予測軌跡を床面ピクセル座標にマッピングして、青い帯（半透明）を描画するロジックを実装
  - [x] 車体アイコンをスイフト（角丸矩形）から Kobuki（円形）に変更し、実寸比率でスケール調整
- [x] **フェーズ 3: 動作検証とパラメータ調整**
  - [x] モックデータ（またはダミーオドメトリトピック）を用いて、予測線がBEV上に描画されるかオフライン検証
  - [x] 実機またはシミュレータ環境におけるROS 2 Humbleトピック（odom, cmd_vel）との連携確認
