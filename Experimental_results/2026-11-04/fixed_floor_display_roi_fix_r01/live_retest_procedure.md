# 比較距離GUI修正後の再確認（11/4）

目的は、実ログに存在していた比較値を修正済みGUIで確認すること。
モデルの精度保証、モデルの単一採用、走行、ROS/FFB試験へは進めない。
基準の概算実測は横ずれを含む155～158cm。旧148cm比較は撤回済み。

## 0. 修正コードを共有する（解析PC→GPU PC）

今回こちらではcommit/pushしていない。ユーザーがGitを反映する従来の進め方に合わせる。
修正対象のruntimeは `src/cone_fixed_floor_display.py`、対応テストは
`tests/test_cone_fixed_floor_display.py`。関連397テストは既に成功済み。
他の作業中ファイルをまとめてstageしない。

必要なら解析PCで下記を使う。commitはstage済みの全変更を含むため、
最後の `git diff --cached --stat` が今回意図した2ファイルだけか確認してからcommit/pushする。

```bash
cd /home/robo25/theta_ws/RICHO-theta
git add -- src/cone_fixed_floor_display.py tests/test_cone_fixed_floor_display.py
git diff --cached --stat
```

2ファイルだけであると確認できた場合の共有操作：

```bash
git commit -m "明示ROI指定時の固定床比較GUI表示を修正"
git push
```

GPU/ハンコン接続PC `hsr-Alienware-m16-R2` で取得する。

```bash
cd ~/yopi_ws/RICHO-theta
git pull --ff-only
sha256sum src/cone_fixed_floor_display.py
```

修正済みファイルのSHA256は
`dcc4adecc8e3e2f91c7e2aa06f1ade9a29504f77e006df7b0ba5e62fcd5cc8b4`。
pullが失敗した場合やhashが異なる場合は上書き・resetせず、そのログを確認する。

## 1. 旧プロセスを通常終了

- GPU PC：現在の距離表示ウィンドウでQ。終了ログを待つ。
- カメラ/Kobuki PC `matunuc-NUC13ANHi5`：現在の送信ターミナルでCtrl+C。
- 元の結果フォルダやprepared_floor.jsonは消さない。旧プロセスはコード更新を自動反映しない。
- カメラ・車体・コーンは静止したまま。ROS/FFBは不要。

## 2. GPU PCで修正版の受信を先に開始

以下の出力先は新規専用。自分で先にmkdirしない。
同じ手順を再度行う場合は、下記コマンド中の **2か所** のr01を同じ未使用番号へ変更する。
以前の出力先へ上書きしたり、既存のモデルをコピーしたりしない。

```bash
cd ~/yopi_ws/RICHO-theta
export THETA_DISTANCE_PYTHON="$PWD/yolo-env/bin/python3"
./start_cone_distance.sh receive --weights "$HOME/Downloads/cone_distance_v03.pt" --target-roi 270 0 350 720 --colour-support-shadow --support-completion-shadow --frame-evidence --fixed-floor-reload-file Experimental_results/2026-11-04/floor_display_fix_live_r01/prepared_floor.json --output-dir Experimental_results/2026-11-04/floor_display_fix_live_r01
```

まだ映像もモデルもないので黒画面・待機表示は正常。別受信器を同じport5002で起動しない。

## 3. カメラ/Kobuki PC（matunuc）で送信

受信GPU PCのIPが以前と同じ150.89.169.78、キャプチャが/dev/video0の場合。
異なる場合は実際の値へ変える。GPU PCのIPはそのPCで `hostname -I`、
deviceはmatunucで `v4l2-ctl --list-devices` により確認する。

```bash
cd ~/theta_ws
export THETA_RTC_PYTHON="$PWD/theta-env/bin/python3"
bash src/start_theta_stream_rtc.sh --diagnostic --receiver-ip 150.89.169.78 --device /dev/video0 --fps 30
```

1280×720の映像専用経路。bird_eye.pyや別送信器を同じカメラで同時に動かさない。
GPU PCの実映像が更新することを確認する。`ICE completed`だけでは判定しない。

## 4. 同じ新接続で床画像を1枚保存して提出

1. 前回と同じ剛性板（白紙実寸296×210mm、格子20mm）を床へ平置きする。
2. 左レンズ内で白い紙の四隅が全て見え、車体・人・コーンで角が隠れないことを確認する。前回と同様の配置でよく、長い撮影や板の移動は不要。
3. GPU PCの映像ウィンドウをクリックして、英字Sキーを1回押す。
4. 保存された `decoded_<新session>_f<frame>.png` を提出する。
5. **受信・送信を起動したまま維持する。Lはまだ押さない。**

PNGの保存場所はGPU PCの
`~/yopi_ws/RICHO-theta/Experimental_results/2026-11-04/floor_display_fix_live_r01/`。
保存確認はGPU PCの別ターミナルで行える（shell変数の引継ぎは不要）：

```bash
cd ~/yopi_ws/RICHO-theta
find Experimental_results/2026-11-04/floor_display_fix_live_r01 -maxdepth 1 -type f -name 'decoded_*.png' -print
```

格子が小さくても、紙の四隅を実際の新画像で観測して明示入力できる可能性がある。
過去画像の角座標を新画像へ無条件に転用せず、提出画像で確認する。
新接続のモデル生成はPNGを受け取った後に行うため、この時点で距離が出なくても失敗ではない。

## 5. PNG受領後に案内する後半（まだ実行しない）

- 新PNGから床モデルの全未選択候補とhashを導出する。
- 新sessionに対応したprepared_floorファイルを指定の新受信フォルダへ置く。
- Lを1回押し、`active`と画面下パネルのmodel値を確認する。
- コーンが同じ位置のままなら概算155～158cmと比較する。配置が変わったら旧実測を使わない。
- 20秒ほどのログ・画面と、Q終了後のlive_summaryを保存する。

元経路の `colour_contour_reaches_roi_edge` / 上部WITHHELDと、
画面下の比較値の有無は別々に確認する。
全モデル中の数値の最小～最大は誤差幅や信頼区間ではない。
床面・カメラ姿勢・接触点・base_link原点の物理検証は残る。

## 手順の検査

現行の受信・送信argument parserで上記コマンドの引数を読み取れることを
解析PCで確認した。GPU・ネットワーク・カメラは起動していない。
修正済みGUIの関連397件成功結果は同フォルダの `verification_r01/` を再利用する。
