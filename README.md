# Go2・Starling2 測定結果

[公開サイトを開く](https://sakamotorui0321.github.io/measurement-results/)

Go2とStarling2の測定結果、公開ビューアー、データ変換スクリプトをこのリポジトリで管理します。

## ディレクトリ構成

```text
measurement-results/
  index.html                         全測定の入口
  go2/
    index.html                       Go2の測定一覧
    measurements/日付_時刻_測定名/   RGB・点群・個別ビューアー
  starling2/
    index.html                       Starling2の測定一覧
    measurements/日付_時刻_測定名/   画像・点群・花候補・個別ビューアー
  scripts/
    import_measurement.py            測定を追加する共通コマンド
    catalog.py                       両機体と全体の一覧を更新
    build_site.py                    花候補ビューアーと一覧を更新
    import_realsense.py               RealSense録画の変換
    go2/                             Go2録画の変換・配布用ビルダー
  src/viewer.html                     Starling2花候補ビューアーの原本
  migration.json                     統合元のコミットとコピー時のSHA-256
```

生のROS bagやRealSense録画は、PCの実験データ内の対象プロジェクト・実験フォルダの `raw/` に保存します。公開用データは上記の機体別フォルダに生成します。

## 次の測定を追加する

リポジトリのルートで、正常停止した録画と新しい測定IDを指定します。同じIDの上書きは拒否します。

### Go2

`go2-remote` の「録画開始」と「bag記録開始」で収録し、両方停止後、確定した録画をPCへコピーします。

```sh
python3 scripts/import_measurement.py go2 "/path/to/実験/raw/録画ID" 2026-11-05_103000_畝A --title "畝A・午前の走行" --bag "/path/to/実験/raw/rosbags/bag-ID"
```

Python標準ライブラリだけで動きます。RealSense RGBと同期姿勢付き外付けLiDARの点群を表示し、bag指定時はROSトピック別の受信件数も表示します。同期姿勢のないスキャンは除外し、姿勢付き点群がない録画はエラーになります。

取付概測値は前20 cm・上11 cm、回転0です。推定座標へ変換した点群を2 cmボクセルでまとめます。RGB保存時刻と点群受信時刻を使うため、厳密な露光同期や精密測量を保証するものではありません。

### Starling2

```sh
python3 scripts/import_measurement.py starling2 "/path/to/実験/raw/voxl/recordings/realsense/録画ID" 2026-11-05_103000_畝A --title "畝A・探索飛行"
```

Python、OpenCV、NumPyが必要です。`frames.jsonl`, `status.json`, `color.yuyv`, `depth.z16` を読み込み、既定でカラー15フレームごとの対応画像を作ります。全カラー画像を使用する場合は `--step 1` を指定します。

花候補の解析後は、`window.FLOWER_DATA` 形式の `data.js` と表示名1行の `title.txt` を新しい `starling2/measurements/測定ID/` に置き、`python3 scripts/build_site.py` を実行します。

### 完成済みビューアーを追加する

`index.html` と参照データを含むフォルダ全体を、対象機体の `measurements/測定ID/` に置きます。`title.txt` を追加し、`python3 scripts/catalog.py` を実行します。

### 確認と公開

共通の取り込みコマンドは一覧も更新します。`python3 -m http.server 8000` を実行し、localhostの8000番で表示を確認します。公開対象の測定フォルダと更新された一覧ページをコミットしmainへpushすると、同じサイトに追加されます。生ログ、認証情報、非公開データは公開対象に含めないでください。

## 統合前の測定と履歴

- Go2の静岡実験（2026-10-16、3・4・6回目）を `go2/measurements/2026-10-16_shizuoka/` に収録しています。
- Starling2の約4 m探索飛行（2026-10-22）を `starling2/measurements/2026-10-22_ridge4m/` に収録しています。従来の解析条件は [Starling2の記録](starling2/README.md) を参照してください。
- コピー時に各ファイルのサイズとSHA-256を照合しました。旧2リポジトリは2026-11-05に削除しました。旧サイトのURL・転送も終了しています。今後の結果追加先はこのリポジトリです。
- Three.jsのライセンスは各Go2ビューアーの `vendor/THREE-LICENSE.txt` にあります。
