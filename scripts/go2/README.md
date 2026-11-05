# Go2変換・配布ツール

測定追加は[ルートの手順](../../README.md)を参照してください。

## データとプログラムの分離

GitにはプログラムとThree.js 0.170.0（MIT）のみを保存します。実験動画、点群、索引、配布ZIPは含めません。
既存の `蓄積点群ビューアー_20261023/dist/data` を入力として使えます。元ログの移動・変更は不要です。

```text
scripts/go2/
  web/                 HTML・CSS・JavaScript・同梱ライブラリ
  portable-loader.js   ローカルHTML用のデータ読み込み処理
  build.py             配布フォルダー／ZIPの生成
  serve.py             localhost用サーバー
  test_build.py        合成データによるビルド検証
```

## ダブルクリックで開ける配布版を作る

生成するPCではPython 3.8以降（標準ライブラリのみ）が必要です。受け取るPCではPython・ROS・サーバー・ネット接続は不要です。
リポジトリのルートから実行します。出力先は毎回新しい名前にしてください。既存のフォルダーやZIPは上書きしません。

```powershell
python scripts/go2/build.py --data-dir "D:\実験データ\蓄積点群ビューアー_20261023\dist\data" --output "artifacts\Go2-PointCloud-Portable" --zip
```

生成されたZIPを送ります。相手側で「すべて展開」し、`ビューアーを開く.html` をEdgeやChromeで開きます。
HTMLだけを取り出さず、フォルダー全体を保持してください。ZIP内部から直接開く使い方は非対応です。
モジュールはBlob URL、データは同梱の通常のscriptから読み込み、file://へのfetchを使いません。
実験データを含む成果物をGitへ追加しないでください。`artifacts/` はGit除外済みです。

## localhostで開く開発用ビルド

```powershell
python scripts/go2/build.py --data-dir "D:\実験データ\蓄積点群ビューアー_20261023\dist\data" --output "artifacts\Go2-PointCloud-Web" --mode web
python scripts/go2/serve.py --directory "artifacts\Go2-PointCloud-Web" --port 8766
```

http://127.0.0.1:8766/ を開きます。既存ビューアーが稼働中なら停止するか、別ポートを指定してください。

## 入力形式と解析上の限界

公開サイトの再生成は `build.py` の `--mode hosted` を使用します。入力・出力指定は上記と同じです。
大きなファイルを8MiB以下に分割し、ブラウザーでバイト列を復元します。データの間引きや再圧縮は行いません。
生成先をこのリポジトリの `go2/measurements/測定ID/` に配置し、`python3 scripts/catalog.py` で一覧を更新します。公開元には`.nojekyll` を置き、`main` のルートをGitHub Pagesの公開元に指定します。
公開用リポジトリは配信物専用です。認証情報や遠隔操作コードは配置しません。

`--data-dir` には以下を配置します。ビルダーは索引で参照されるファイルのみを読み込みます。

- `manifest.json`: `runs` 配列。各要素に `id`, `title`, `count`, `duration`（秒）, `bounds`（XYZの最小・最大）, `trajectory`（`[開始からの秒,x,y,z]`の配列）, `file`。
- 点群の `file` は `data/run3.bin` など。1点16バイト、little-endian float32の `x,y,z,first_seen_seconds`。位置単位m。
- `rgb.json`: 測定ID文字列をキーにした辞書。値は `file`（例 `data/rgb3.mjpeg`）, `frames`（`t`, `offset`, `bytes`）, `maxAge`（秒）。
- MJPEG: 連結JPEG。`offset`と`bytes`で各画像を読み出す。`t`は点群と共通の開始時刻からの秒。

UIの測定ボタンは3・4・6、初期選択は4です。他の測定IDへの一般化は未実装です。
RGB索引の `t` は `rgb.jsonl` の `saved_utc` から点群生成に用いた `pose_time_unix[0]` を引いた値です。
現在時刻以前の最新画像を使い、`maxAge=0.75`秒を超えたら記録なしとします。撮影時刻の厳密な同期は未校正です。
同梱する映像には元の検出枠を含みます。メタデータの `source`（元PCのパス）は配布物から除去します。

既存点群はROS bagの受信時刻を使い、機体の推定位置・姿勢と取付概測値で補正し、2cmボクセルの最初の点を保持しています。
センサー距離10m以内、高さ−1〜4mの概略地図です。精密なSLAM地図ではなく、見えていない葉の裏側を復元するものでもありません。
このディレクトリは閲覧と配布のプログラムです。ROS bagからの点群再解析処理は含みません。

## 検証と未確認事項

```powershell
python -m unittest discover -s viewers/pointcloud -p "test_*.py"
node --check scripts/go2/web/app.js
```

localhost版は3・4・6の表示、同期再生、シーク、単独表示切替をブラウザーで確認済み。
配布版はデータ復号・バイナリ一致・生成JavaScript構文・ZIP整合性を確認。
file://での起動確認はアプリ内ブラウザーのURLポリシーで拒否されたため未実施です。別PCでの起動も未確認です。
