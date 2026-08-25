# Windowsバッテリーモニター 現状と次回開始手順

更新日: 2026-08-25

## 1. 結論

受領した`WirelessBatteryWidget_v1.0.1_Windows_x64_OneFile.zip`には実行ファイルだけが含まれ、
作者はソースコードを配布していない。このため、受領アプリへの機能追加や改造は行わず、
LogicoolマウスとBluetoothイヤホンを同一画面に表示するWindowsアプリを独立して新規実装する。

受領アプリは次の用途に限定する。

- Windows実機での動作確認
- 必要な機能と期待動作の整理
- 自作アプリとの表示値・接続復旧動作の比較
- 作者へ不具合や改善点を報告するための確認

受領EXEの逆コンパイル、コード・画像・アイコンの抽出や転用、バイナリ改造は行わない。
新規実装は、MicrosoftおよびBluetooth SIGの公式資料と、利用条件を確認できる公開情報を根拠にする。

## 2. 最終目標

Windows 10またはWindows 11上で常駐し、次の機器のバッテリー状態を一つの画面へ表示する。

- Logicool製ワイヤレスマウス
- Logicool以外のBluetoothイヤホン

通常はWindowsの通知領域に常駐し、クリック時に次を展開表示する。

- 機器名
- バッテリー残量
- 充電状態
- 接続状態
- 情報取得元
- 最終更新時刻
- 値が古いかどうか

未取得値や切断状態を`0%`として扱わない。`取得不可`、`切断中`、`--`、最終更新時刻などで
状態を明確に区別する。

## 3. 受領物

### 3.1 原本情報

| 項目 | 内容 |
|---|---|
| ファイル名 | `WirelessBatteryWidget_v1.0.1_Windows_x64_OneFile.zip` |
| 受領日 | 2026-08-25 |
| ZIPサイズ | 37,397,942 bytes |
| ZIP SHA-256 | `e5d5ead620b06a23798255c6e929160edfd14f4d2915cbe037b5770747514f13` |
| EXE SHA-256 | `18ab83311a92d6ca8d21d200a44b22b9a2224bf314ce5abe471badcebe1f5b85` |
| EXE形式 | Windows PE32+ GUI、x86-64 |
| バージョン | 1.0.1 |
| 署名 | Authenticode署名なし |
| ソースコード | 非同梱・非配布 |

ZIP内の全ファイルは、同梱された`SHA256SUMS.txt`と一致した。ただし、同梱ハッシュとの一致は
配布後の内部整合性を示すものであり、実行ファイルの安全性を完全に保証するものではない。

### 3.2 実行前の静的確認結果

- PyInstallerで単一EXE化されたPython 3.14アプリ
- 主な同梱コンポーネントはPySide6、Qt、websocket-client
- G HUBとの接続先として次のループバックURLが記載されている
  - `ws://127.0.0.1:9010`
  - `ws://localhost:9010`
- G HUBのデバイス一覧とバッテリー情報を取得する構成
- Bluetoothイヤホンの取得処理は含まれていない
- 外部Web API、テレメトリ、アカウント認証は実装していないと同梱文書に記載されている
- 自動起動を有効にした場合だけ、現在のユーザーの`HKCU Run`へ登録する構成
- 未処理例外は`%LOCALAPPDATA%\WirelessBatteryWidget\crash.log`へ保存する構成

Linux上での限定的な静的確認であり、Windows上でのDefenderスキャンと実行時確認は未実施である。

## 4. 確定した新規実装方針

### 4.1 開発単位

バッテリーモニターはRICOH THETA関連コードと目的・依存関係が異なるため、Windows PC上で
独立したGitリポジトリとして作成する。このリポジトリには引き継ぎ文書だけを残し、実装コードを
混在させない。

仮のリポジトリ名:

```text
wireless-battery-monitor
```

### 4.2 技術基盤

第一案を次の構成とする。

| 項目 | 採用方針 |
|---|---|
| 言語 | C# |
| ランタイム | .NET 10 LTSの最新パッチ |
| UI | WPF |
| 通知領域 | `System.Windows.Forms.NotifyIcon` |
| G HUB通信 | `System.Net.WebSockets.ClientWebSocket` |
| Bluetooth | `Windows.Devices.Bluetooth`および`Windows.Devices.Bluetooth.GenericAttributeProfile` |
| テスト | xUnitまたはMSTest。テンプレート作成時に一方へ固定する |

.NET 10は2026-08-25時点でサポート中のLTSである。WPFは小型の枠なしウィンドウを作りやすく、
`NotifyIcon`はWindows通知領域の標準的な.NET APIである。BluetoothはWindowsが提供するWinRTの
GATT Client APIを利用する。

Bluetooth APIの利用にMSIXパッケージまたは`bluetooth` capabilityが必要になるかは、最初の
Bluetoothプローブで実機確認する。未確認のままパッケージ方式を固定しない。

### 4.3 内部構造

機器固有処理をUIへ直接書かず、Providerとして分離する。

```text
LogitechGHubProvider ───────┐
                            │
BluetoothBatteryProvider ───┼─ DeviceBatteryState ─ StateStore ─ Tray/Flyout UI
                            │
将来の機種固有Provider ─────┘
```

共通状態は最低限、次の値を持つ。

```text
DeviceBatteryState
  Id
  DisplayName
  Percentage          nullable
  IsCharging          nullable
  IsConnected
  Source
  UpdatedAt
  IsStale
  ErrorCode            nullable
```

ProviderはUI型へ依存させない。通信不能、切断、未対応、権限不足、タイムアウトを例外だけで
終わらせず、共通状態または明示的な結果型へ変換する。

### 4.4 通信と安全上の境界

- G HUB接続先はループバックアドレスだけを許可する
- ポート9010をLANへ公開するためのポート転送やファイアウォール開放は行わない
- バッテリー監視に管理者権限を要求しない
- 認証情報、ユーザーファイル、デバイス情報を外部へ送信しない
- 自動更新はMVPへ含めない
- Windowsログイン時の自動起動は、ユーザーが明示的に有効にした場合だけ追加する
- G HUBは非公開APIであるため、プロトコル変更をアプリ全体から隔離する

## 5. 公開情報から確認できた技術的根拠

- MicrosoftのGATT Client APIは`Windows.Devices.Bluetooth`と
  `Windows.Devices.Bluetooth.GenericAttributeProfile`を使用する。
  <https://learn.microsoft.com/windows/apps/develop/devices-sensors/gatt-client>
- WinRTのBluetooth名前空間はデスクトップアプリからも利用できる。
  <https://learn.microsoft.com/uwp/api/>
- Windows Formsの`NotifyIcon`は、バックグラウンド常駐プロセスを通知領域へ表示するためのAPIである。
  <https://learn.microsoft.com/dotnet/desktop/winforms/controls/notifyicon-component-overview-windows-forms>
- .NET 10はLTSで、公式サポート期限は2028-11-14である。
  <https://dotnet.microsoft.com/platform/support/policy>
- Bluetooth SIGの割り当てではBattery Serviceが`0x180F`、Battery Level characteristicが
  `0x2A19`である。
  <https://www.bluetooth.com/specifications/assigned-numbers/>
- 公開実装LogiBATはG HUBの`ws://localhost:9010`、`/devices/list`、
  `/battery/{deviceId}/state`を文書化している。ただしリポジトリ全体の利用ライセンスを確認できない
  ため、コードはコピーせず、プロトコル理解の参考資料としてのみ扱う。
  <https://github.com/someweirdhuman/LogiBAT>

## 6. 帰宅後、Windows PCで最初に行うこと

### 6.1 受領ZIPの保存と確認

1. 作者から案内された元の場所からZIPをダウンロードする。
2. 展開前ZIPを変更しない原本として保存する。
3. PowerShellでZIPのハッシュを確認する。

```powershell
Get-FileHash -Algorithm SHA256 .\WirelessBatteryWidget_v1.0.1_Windows_x64_OneFile.zip
```

期待値:

```text
e5d5ead620b06a23798255c6e929160edfd14f4d2915cbe037b5770747514f13
```

値が異なる場合は実行せず、ダウンロード元とファイル名を再確認する。

4. ZIPまたは展開先をMicrosoft Defenderでスキャンする。
5. ZIPを通常フォルダーへ展開する。
6. EXEのハッシュを確認する。

```powershell
Get-FileHash -Algorithm SHA256 .\WirelessBatteryWidget.exe
```

期待値:

```text
18ab83311a92d6ca8d21d200a44b22b9a2224bf314ce5abe471badcebe1f5b85
```

### 6.2 実機情報を記録する

| 項目 | 記録値 |
|---|---|
| Windowsエディション・バージョン | 未記入 |
| OSビルド | 未記入 |
| Logicoolマウス型番 | 未記入 |
| マウス接続方式 | LIGHTSPEED / Bluetooth / 未確認 |
| G HUBバージョン | 未記入 |
| G HUB上で残量が見えるか | 未確認 |
| イヤホンメーカー・型番 | 未記入 |
| イヤホン接続方式 | BLE / Classic / 未確認 |
| Windows設定で残量が見えるか | 未確認 |
| 表示したい残量 | 合計 / 左 / 右 / ケース / 未決定 |

イヤホンはWindowsの「設定」→「Bluetoothとデバイス」で残量表示を確認し、表示画面の内容を
記録する。合計残量が見えても、左右やケースを個別取得できるとは限らない。

### 6.3 受領アプリの基準動作を確認する

初回確認では自動起動を有効にしない。

| テスト | 記録する内容 |
|---|---|
| G HUB起動後に受領アプリを起動 | 機器名、残量、表示までの時間 |
| G HUBを終了 | 表示、エラー、アプリが継続するか |
| G HUBを再起動 | 自動復旧の有無と所要時間 |
| マウスをスリープ | `0%`、切断、古い値のどれになるか |
| マウスを復帰 | 更新までの時間 |
| タスクトレイ操作 | 表示、非表示、設定、終了 |
| PC再起動 | 自動起動を無効にした状態で勝手に起動しないか |

クラッシュした場合は、次のログにWindowsユーザー名などが含まれていないか確認してから作者へ
共有する。

```text
%LOCALAPPDATA%\WirelessBatteryWidget\crash.log
```

## 7. 新規実装の開始順序

### フェーズ0: 実機事実の確定

- 上記のWindows情報、マウス型番、イヤホン型番を記録する
- 受領アプリの基準動作を確認する
- Windows設定でイヤホン残量が見えるか確認する
- G HUBのバージョンとループバック接続可否を確認する

### フェーズ1: 独立リポジトリと最小コア

- Windows上で新しいGitリポジトリを作成する
- .NET 10 WPFソリューションを作成する
- `DeviceBatteryState`とProviderインターフェースを実装する
- Fake Providerで未取得・切断・古い値をテストする
- この段階では実機通信や完成UIを同時に作らない

推奨構成:

```text
wireless-battery-monitor/
  src/
    WirelessBatteryMonitor.App/
    WirelessBatteryMonitor.Core/
    WirelessBatteryMonitor.Providers.GHub/
    WirelessBatteryMonitor.Providers.Bluetooth/
  tests/
    WirelessBatteryMonitor.Core.Tests/
    WirelessBatteryMonitor.Providers.GHub.Tests/
    WirelessBatteryMonitor.Providers.Bluetooth.Tests/
  docs/
```

### フェーズ2: G HUB Provider

- `ClientWebSocket`で`localhost:9010`へ接続する最小プローブを作る
- デバイス一覧と対象マウスのバッテリー応答をJSONログへ保存する
- 個人識別情報や不要なデバイスIDは公開ログから除去する
- 正常応答をテスト用fixtureに匿名化して保存する
- タイムアウト、G HUB停止、再起動、マウススリープをテストする
- 指数バックオフ付き再接続を実装する

### フェーズ3: 通知領域と詳細表示

- `NotifyIcon`を表示する
- クリック時だけWPFの詳細ウィンドウを表示する
- Fake Providerで複数機器、未取得、切断、古い値を確認する
- 複数ディスプレイ、DPI、タスクバー位置変更を確認する

### フェーズ4: Bluetooth Provider

- Windowsにペアリング済みのイヤホンを列挙する
- 標準Battery Service `0x180F`を検索する
- Battery Level `0x2A19`を読み取る
- 通知を購読できる場合は通知を優先する
- 標準サービスがない場合だけ、Windowsが公開するデバイスプロパティを確認する
- 機種固有プロトコルは、型番と必要性を確認して別フェーズで判断する

### フェーズ5: 常駐運用

- 30～60秒の更新間隔を基本とする
- デバイス切断中は再試行間隔を長くする
- 自動起動を任意設定として追加する
- 設定保存、ログローテーション、リリース手順を文書化する

## 8. 最初のMVP完了条件

- 対象Logicoolマウスの残量を取得できる
- 対象イヤホンが標準の残量を公開する場合、少なくとも合計残量を取得できる
- 両方を同じ通知領域／詳細画面へ表示できる
- G HUB、Bluetooth、各デバイスの切断でアプリが終了しない
- 未取得、切断、古い値を区別できる
- 高頻度ポーリングでデバイスのスリープを妨げない
- ビルド方法、必要ランタイム、確認済み機種をREADMEへ記録する

## 9. 現時点の未確定事項

- Windowsの正確なバージョンとOSビルド
- Logicoolマウスの型番と接続方式
- G HUBのバージョン
- イヤホンのメーカー、型番、Bluetooth方式
- イヤホンが標準Battery Serviceを公開するか
- Windowsがイヤホンの合計、左右、ケースのどこまで公開するか
- Bluetooth API利用時に採用する配布方式（通常EXEまたはMSIX）
- アプリを個人利用だけにするか、将来公開するか

これらはWindows実機で確認する。未確認値を推測でコードや設定へ固定しない。

## 10. 次回AIへ渡す開始指示

Windows PCでこの文書を開き、次の依頼から再開する。

> `windows_battery_monitor_current_status.md`を最初から最後まで読み、まずフェーズ0だけを進めてください。
> ZIPとEXEのハッシュ、Defenderスキャン結果、Windows・G HUB・マウス・イヤホンの情報を記録し、
> 受領アプリを無変更でテストしてください。新規プロジェクトは実機確認結果を報告するまで作成せず、
> 管理者権限、ファイアウォール開放、ポート転送、受領EXEの解析や改造は行わないでください。

