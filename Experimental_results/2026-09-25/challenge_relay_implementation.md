# Phase 5 challenge relay分離実装

## 結論

v9実カメラPC間dry-runで確認された、カメラGUIのcallback停滞により古いchallenge tokenを送信する問題に対し、challenge受信と最終command送信を独立プロセスへ分離した。

実装・単体回帰・ワンコマンド起動のdry-runは完了した。実PC間でadapter faultが0件になることは未確認であるため、次はv10設定を使ったdry-run試験を行う。合格まではhardware出力へ進めない。

## v9試験から分かったこと

- v9のtoken単回使用と有限cadenceの非再発火は成立した。
- 録画区間のadapter faultは21件だった。
- カメラ側で新しいと判断したtokenでも、カメラGUIがchallenge callbackを処理するまでに遅れがあり、受信側では期限切れになった。
- 遮蔽開始が走行終了後だったため、この試験ではUNKNOWNは発生しなかった。これは通信faultとは別の実験操作上の問題である。

詳細は`phase5_v9_camera_unknown_dryrun_r01_diagnosis.md`を参照する。

## 実装構成

```text
bird_eye.py
  危険度・有限cadenceを計算
       |
       | /collision/ffb_intent
       v
collision_ffb_relay.py（カメラGUIと別プロセス）
  intent時刻 <= 0.10 s
  challenge callback時刻 <= 0.06 s
  token未使用
       |
       | /collision/ffb_command + receiver token
       v
collision_ffb_node（ハンコンPC）
  challenge期限 <= 0.10 s
  watchdog 0.10 s
  出力上限は従来値を維持
```

## 追加・変更ファイル

- `src/collision_ffb_relay.py`
  - 最新challengeをdepth 1で受信する専用relay。
  - intentとchallengeの両方が新しい場合だけcommandを送る。
  - tokenはpublish前に消費済みとし、例外時にも再利用しない。
  - 古いintent、古いchallenge、未来時刻、別source、異常magnitudeをfail-closedで拒否する。
- `src/run_field_experiment.py`
  - v10設定ではpreflight後にrelayを自動起動する。
  - relayが起動直後に終了した場合はカメラを起動しない。
  - カメラ終了時はrelayへSIGINTを送り、終了しない場合だけterminateする。
- `src/bird_eye.py`
  - relay有効時は最終commandではなく`/collision/ffb_intent`を送る。
  - 録画metadataへintent/relay/final topicを記録する。
- `src/preflight_field_experiment.py`
  - relayの有効値、topic分離、intent期限、challenge modeを検査する。
- `src/bird_eye_config_ttc_v10_ffb_relay_20260925.json`
  - v9の認識・TTC・FFB強度・cadenceは維持し、relayだけを追加した候補設定。

## 安全条件

- ハンコン側adapterのchallenge期限、watchdog、強度上限は変更していない。
- relayはtokenがない、古い、使用済みのいずれでもcommandを出さない。
- relay自身はハンコンへアクセスしない。
- 実PC間dry-runに合格するまではhardware試験へ進めない。

## 検証結果

| 検証 | 結果 |
|---|---:|
| relay専用単体試験 6件 | PASS |
| 起動処理単体試験 11件 | PASS |
| preflight設定単体試験 19件 | PASS |
| v10 JSON構文 | PASS |
| v10ワンコマンドdry-run | PASS |
| Python構文確認（変更ファイル） | PASS |
| FFB workspaceをsourceした全体unittest 197件 | PASS |

ROS workspaceをsourceしない状態では`oit_interfaces`依存の1モジュールを収集できないが、FFB workspaceをsourceした実験相当条件では全197件がPASSした。

## 次の判定点

v10・adapter `dry_run`で、次をすべて満たすことを確認する。

1. `/collision/ffb_intent`と`/collision/ffb_command`が両方記録される。
2. `unknown_receiver_token`と`expired_receiver_token`が0件。
3. active intentに対応するactive command/statusが存在する。
4. WARNINGの三連とUNKNOWNの単発が同じ警報中に再発火しない。
5. 試験終了時にinactive、`fault: false`となる。

遮蔽は接近中かつ青箱が検出されている間に開始し、箱を完全に隠した状態を約1秒維持する。
