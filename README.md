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

**点群・花候補・元RGB画像と動画4本をまとめて作る**には、Ubuntuで実験フォルダを1つ指定します。

```sh
cd ~/measurement-viewers/measurement-results
python3 scripts/import_measurement.py starling2 "/path/to/実験データ/starling2/YYYY-MM-DD_HHMMSS_実験名"
```

完了後、測定一覧の「3D点群・花候補・動画4本」を開きます。点群の赤い候補をクリックすると、対応する元RGB画像と検出枠が表示されます。画面上部から RGB、Depth、RGB・Depth左右比較、花検出枠付きRGBのMP4を再生できます。各15 fpsで、単体動画は各ストリームの全フレーム、左右比較はRGBに時刻が最も近い深度を使用します。

標準の実験フォルダでは、動画4本を同じ研究室の「進捗/動画/実機/Starling2/日付_実験名/」にも保存します。それ以外の場所では実験の exports/ を使用します。保存先の親は STARLING2_VIDEO_ROOT で変更できます。解析途中のCSV・姿勢・点群・各段階の検証記録は実験の analysis/ 内の日時付きフォルダに残ります。再実行時は登録済みの同じ録画の結果を利用します。

- 入力は確定済みの raw/voxl/recordings/realsense/ 内の録画（RGB・深度・時刻索引・clock.jsonl・同じ記録に結び付く calibration.json）と raw/pi/ 内の姿勢・時刻同期を含むROS bagです。raw/pc/FLIGHT_RESULT.json があれば記録IDを照合します。複数候補があり一意に特定できない場合は停止します。旧録画では、同一機体の確認記録と入力・校正ハッシュが一致する実験内の保存済み工場校正も利用できます。
- このPCは設定済みです。ほかのUbuntuでは ROS 2 Jazzy、ビルド済みpx4_msgsを含むワークスペース、OpenCVのH.264対応、NumPy・SciPy・YOLO環境が必要です。変換は scripts/starling2_experiment.py から実行され、検出・深度投影・姿勢抽出・花のグループ化の実装も scripts/starling2/ に同梱しました（agricultural_support_ws の 91a928a を基にしています）。検出区間の水平移動が10 cm未満で進行方向を決められない場合は東を横軸とします。ROSメッセージの読み出しにはワークスペースの install 環境を使います。WSは STARLING2_WS（既定 ~/agricultural_support_ws）、YOLOのPythonは STARLING2_YOLO_PYTHON（既定 ~/.venvs/go2-processor/bin/python）、重みは STARLING2_WEIGHTS（既定 ~/.local/share/measurement-results/tomato_flower_yolov8n.pt）で設定できます。
- 機体へのカメラ取付は従来の概測（水平・機首向き、前方3 cm・上方3 cm）を既定とし、実験側の config/mount.json を優先します。同じ向きと光学座標系を前提とし、取付条件が異なる場合は確認が必要です。花の位置は内部推定で、花群は同じ物理花であることを保証しません。

**RGB・深度だけを確認する場合**は、従来通り個別録画とIDを指定できます。

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
