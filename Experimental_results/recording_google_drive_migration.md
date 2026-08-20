# 録画アーカイブのGoogle Drive移行手順

## 1. 保存方針

- Gitには録画本体を追加せず、`recording_archive_manifest.csv`だけを追跡する。
- `matsunuc`上の`.tar.xz`を原本とし、Google Driveへ同一バイト列の第2コピーを置く。
- アーカイブは展開せず、既存ファイル名のままアップロードする。
- アップロード済みアーカイブを同名で上書きしない。再録画は別dataset IDと別ファイル名にする。
- Google Driveの共有範囲は「制限付き」とし、一般公開リンクを作らない。

## 2. 今日行う作業

Google Driveに次のフォルダを作る。

```text
RICHO-theta-recordings/
└── raw/
    └── 2026-08-18/
```

保存容量が少なくとも既存アーカイブ合計の2倍程度残っていることを確認する。大学アカウントを
使う場合は、卒業・所属変更後のデータ保持条件も確認する。

## 3. matsunuc起動後の移行

最初にリポジトリを最新状態にし、アーカイブの実在パスを確認する。その後、各ファイルを
台帳へ登録する。例:

```bash
cd ~/theta_ws/RICHO-theta
python3 src/register_recording_archive.py \
  --dataset-id p0b-static-20260818 \
  --archive /home/hsr/Downloads/recoding/recoding_08181700.tar.xz \
  --captured-date 2026-08-18 \
  --experiment-stage P0-B
```

この処理は次を行う。

1. `.tar.xz`全体を読み、圧縮ストリームとtar構造を確認する。
2. ファイルサイズとSHA-256を再計算する。
3. `recording_archive_manifest.csv`の同じdataset IDを更新する。

表示されたSHA-256が既報値と異なる場合はアップロードせず、ファイルの取り違えや破損を
確認する。

## 4. Google Driveへのアップロード

`RICHO-theta-recordings/raw/2026-08-18/`へ、検査済みの`.tar.xz`をブラウザから
アップロードする。アップロード完了後、ファイルの共有設定が「制限付き」であることを
確認する。

Drive内の保存パスを台帳へ登録する場合は、同じコマンドへ`--drive-path`を追加する。

```bash
python3 src/register_recording_archive.py \
  --dataset-id p0b-static-20260818 \
  --archive /home/hsr/Downloads/recoding/recoding_08181700.tar.xz \
  --drive-path 'RICHO-theta-recordings/raw/2026-08-18/recoding_08181700.tar.xz'
```

GitにはGoogle DriveのファイルIDや共有URLを記録せず、Drive内の論理パスだけを記録する。
アクセス権はGoogle Drive側で管理する。

## 5. ダウンロード検証

初回移行では、Google Driveから別名または別ディレクトリへダウンロードし、SHA-256が
台帳と一致することを確認する。一致した時刻を`download_verified_at_utc`へ記録する。
ブラウザで再生できることは整合性確認の代わりにならない。

確認が終わるまで`matsunuc`上の原本を削除しない。確認後もGoogle Driveの1コピーだけに
せず、少なくとも`matsunuc`とDriveの2コピーを維持する。
