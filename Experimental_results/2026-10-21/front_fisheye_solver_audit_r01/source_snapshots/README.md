# 凍結結果で使用したテストの原本

解析後、Kobuki等のSciPy未導入PCで通常preflightのunit testを壊さないよう、`tests/`の診断テスト2ファイルに「SciPyなしならSkipTest」のimport guardだけを追加した。数値計算モジュールは変更していない。

解析結果のsource hashが指す**guard追加前とバイト同一のテスト**をここへ保存し、元path/hashと保存pathを[manifest.json](manifest.json)で対応させた。既存結果・source hashの値を後から書き換えていない。現在の`tests/`は同じ8件を実行し、追加guardの非導入分岐も別途模擬検証する。

`verify_artifacts.py`は現在のファイルhashが異なる場合だけこの原本を解決先とし、数値モジュールや生データの相違を黙認しない。追加のcheckpoint、GPU環境、実機設定は変更していない。
