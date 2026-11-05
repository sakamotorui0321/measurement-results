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

## L2を元RGBで部分着色する静止実験

機体・標的・背景を固定する。取付やカメラを変更したら校正を取り直す。走行時のスキャン内補正・カメラ露光時の姿勢補間は未実装。静止を確認した録画に限り、保存された各L2スキャンの全有限XYZをL2座標のまま表示する。単一スキャン内の測距点を保持し、表示用のボクセル統合はしない。

1. 正常停止したGo2録画ディレクトリを実験フォルダの `raw/go2/<録画ID>/` にコピーし、原本と件数・サイズ・ハッシュを照合する。Go2録画画面で「外付けLiDAR」「着色用RGB＋数値深度」を選んだ記録を使用する。稼働するカメラ所有プロセス内で新版のexporterが必要。RGB-Dが0件・エラーの記録は着色できない。旧録画の取り込み手順は上記のとおり。
2. 校正は機体を静止させ、50～60 cm角のつや消し板をカメラの正面約1 m、L2の高さ付近に立てる。建物の壁から50 cm以上離し、RGBとL2の双方で外縁が見える位置を探す。板を画面の左・中央・右、近距離・遠距離へ移し、角度も20～30°振る。設置し直したら手を離して各10～15秒別録画する。距離は設置の目安。L2が当たらない面や大きく欠けた角は対応点に使わない。別配置を検証専用に確保し、奥の板の手前約20～30 cmに葉を置いた場面も収録する。
3. 静止シーンごとに、同一の物理的特徴についてL2の点番号と元RGB画素を記す。板に印刷した模様はL2幾何の特徴にはならない。L2 JSONLの行・points配列とrgbd.jsonlの行はすべて0始まり。NPZのcolorはBGR8、depthはRGB画素に整列したZ16。複数面にまたがる8対応以上を使用する。次の構造の `config/annotations.json` を作る。配列は同じ順番に測った値で埋める。

```json
{"fit":[{"recording":"../raw/go2/校正用録画ID","scan":0,"frame":0,"l2_indices":[],"rgb_pixels":[]}],"held_out":[{"recording":"../raw/go2/別配置の録画ID","scan":0,"frame":0,"l2_indices":[],"rgb_pixels":[]}]}
```

4. リポジトリのルートで `.venv/bin/python scripts/go2/calibrate_l2.py /path/to/config/annotations.json /path/to/analysis/校正日時` を実行する。candidate.jsonにメートル単位の剛体変換・別配置の画素誤差・観測された画素範囲が入る。出力PNGで板の縁と投影を照合し、共通視野外の位置も記録する。細い葉の幅に比べ誤差が大きい場合は対応を見直す。画面端や遠距離も含めて採否を判断する。自動生成結果の採用は手動。
5. 本番の静止実験には検証報告と観測条件を保管する。実験の `config/l2-color.json` に採用したcandidate.jsonと同じ `T_rgb_from_l2`、`camera_serial`、同ファイルへの相対パス `validation_reference`、`motion`（静止確認済みなら `stationary`）、`max_time_s`、`max_depth_m`、`tolerance_basis` を記入する。校正用録画は別の実験フォルダに保管し、取り込み対象のraw以下は本番録画1件にする。平板の距離別の深度残差、静止時の揺れ、別配置の残差と葉・背景の間隔を記録し、許容する深度差を決める。時刻はROSヘッダとRGBのSDKホスト時計、ハードウェア時計の場合は同一Go2でのフレーム受信UTCで近接対応する。RGBと深度のデバイス時計種別も照合する。許容する時刻差はフレーム間隔・受信遅延の測定に基づき定める。いずれも機体固有の既定値は未設定。
6. 以下を実行する。分析結果は実験のanalysis以下の新しい日時フォルダに保存する。inputs.jsonlに入力と解析コードのSHA-256、matches.jsonlに各スキャンの対応時刻・判定数、summary.jsonに画角内率の計算に使う件数と着色率を記録する。分母は保存スキャンの全有限L2点数と、同じ点のうちRGB画角内の点数。スキャン間の重複観測も1点ずつ数える。画角外を最初に区分し、画角内で時刻、深度欠損、深度差を判定する。中心と上下左右1画素のいずれかが欠損・不整合の場合も灰色。検証例は元RGB、投影（緑=着色、赤=深度未対応）、元Z16 PNG、投影点のRGB座標系ZとカメラZのNPZを保存する。occlusionという名前は手前に深度面がある候補で、葉かどうかは元画像で判定する。

```sh
cd ~/measurement-results
.venv/bin/python scripts/import_measurement.py go2 "/path/to/YYYY-MM-DD_HHMMSS_実験名"
python3 -m http.server 8765 --bind 127.0.0.1
```

ブラウザで http://127.0.0.1:8765/ → Go2 → 測定名を開く。「点の表示」で「高さで色分け」と「RealSenseで部分着色したL2点群」を選ぶと、視点・時刻・表示範囲を保ったまま比較できる。ローカルでの取り込みと公開は別操作。
