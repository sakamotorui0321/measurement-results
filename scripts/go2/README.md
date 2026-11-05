# Go2録画の変換・配布ツール

新しい測定の追加には[ルートREADME](../../README.md)の `scripts/import_measurement.py go2 ...` を使用します。

既に解析済みの点群・RGB索引がある場合は、従来のビルダーも使用できます。

```sh
python3 scripts/go2/build.py --data-dir "/path/to/解析済み/data" --output "go2/measurements/2026-11-05_103000_畝A" --mode hosted
python3 scripts/catalog.py
```

出力先に `title.txt` を置くと一覧の表示名を指定できます。入力データは `manifest.json` の `runs` と `rgb.json` で参照する点群・映像を同じフォルダにまとめます。点群はXYZと時刻の4つのfloat32（little endian）で1点16バイト、RGBはJPEGを連結したファイルと各フレームの時刻・バイト位置・長さです。ビルダーは参照パス・点数・画像の境界を検査します。

`--mode portable` ではダブルクリック用の配布版、`--mode web` ではローカルサーバー用、`--mode hosted` では8 MiB単位に分割した公開用データを作成します。出力先は新しいフォルダを指定してください。

`python3 -m unittest discover -s scripts/go2` で変換と配布のテストを実行できます。
