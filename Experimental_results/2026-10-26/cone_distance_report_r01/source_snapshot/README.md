# r03当時の変更前ソース

同日後続のcadence修正前ソースを、r03の来歴検証用に保存した。元の結果は上書きしていない。

| 元パス | 保存ファイル | r03 / 旧verificationが記録したSHA256 |
|---|---|---|
| `src/cone_distance_core.py` | `cone_distance_core.py` | `b050519eea0104eddb218c35140edf653af9d00f99b327a707dcaae3d85c2b00` |
| `src/run_cone_distance_replay.py` | `run_cone_distance_replay.py` | `64ec8008966d044ed5d1923f2771e9721ebb07d1b3c8a32b7b44a54e2bef7fa7` |

どちらも元ソースとバイト同一のハッシュへ一致する。残りの当時の依存ソースは変更していない。
これはソース出典の保存用で、snapshotディレクトリ単独で実行する入口ではない（元コードのrepo相対パスを保持）。
旧r03は旧時刻方式の探索結果として保持し、現行版のテスト合格や連続出力の保証へ言い換えない。
現行の再計算は `cone_distance_replay_r04`、修正の根拠は `scene_cadence_audit_r01` を参照。
