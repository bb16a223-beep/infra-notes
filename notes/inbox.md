- 2026-11-23 16:05 nginx.conf: upstream内のserver行は、転送先1台を表す
- 2026-11-23 16:05 upstreamのzoneは、ワーカー間で転送先の状態を共有する
- 2026-11-23 16:05 SGのdescriptionを変えると、リソースがreplaceになる
- 2026-11-23 16:13 compose: ports "8000:80" は ホスト8000 → コンテナ80。SGで開けるのはホスト側の8000
- 2026-11-23 16:17 ブラウザ → Nginx → Gunicorn → Flask(app.py) → PostgreSQL
- 2026-11-23 16:21 Nginx=受付(振り分け) / Gunicorn=Pythonアプリを動かす / Flask=URLごとの処理を書く部品
- 2026-11-23 16:34 POSTGRES_*は.envに書く→composeがコンテナの環境変数にする→app.pyがos.environで読む。.envはGit管理外
- 2026-11-23 19:21 リクエストごとの接続・切断（get_conn() → conn.close()）:
アクセスが集中すると接続の確立・切断のオーバーヘッドが増えるため、規模が大きくなったらコネクションプール（psycopg_pool など）を検討するようになります。
- 2026-11-23 19:21 毎回テーブル作成（CREATE TABLE IF NOT EXISTS）をしている点:
ちょっとした検証や起動直後の確認では手軽ですが、本番や本格的なアプリでは初回セットアップやマイグレーションでテーブルを作っておき、リクエストごとに CREATE TABLE を走らせない構成にするのが一般的です。
- 2026-11-23 19:23 2. もし DEFAULT がない列があったらどうなる？
たとえば、初期値（DEFAULT）がなく NOT NULL（空欄不可）になっている列があるテーブルに対して INSERT INTO ... DEFAULT VALUES を実行すると、入れるべき値がなくてエラーになります。

今回の hits テーブルは id と at の2つだけで、どちらも自動設定されるため、DEFAULT VALUES だけでスッキリ1行追加できます。
- 2026-11-23 19:26 count(*) と count(列名) の違い
ここが理解しやすいポイントです。

count(*)： 「行の数」を数えます。行の中に NULL（空の値）があっても、行が存在していれば 1 件として数えます。

count(列名)： 「指定した列の値が NULL ではない件数」を数えます。その列が NULL の行はカウントされません。
- 2026-11-24 00:32 terraform: route_tableのvpc_id=VPC、route内のgateway_id=IGW。取り違えるとInvalidVpcID.NotFound(エラー文のIDの接頭辞で気づける)
- 2026-11-24 00:32 到達確認: ブラウザがhttps://で開くとhttp.serverは400。http://を明示する。ログに自分のIPが出ればSG・経路はOK
- 2026-11-24 00:33 Serving HTTP on 0.0.0.0 port 8000 (http://0.0.0.0:8000/) ...   ← 起動したという表示
219.104.138.85 - - [23/Nov/2026 15:30:03] "GET / HTTP/1.1" 200 -  ← アクセスログ
- 2026-11-24 00:33 python3 -m http.server 8000

- 2026-11-24 00:34 python3 -m http.server 8000=カレントフォルダを公開する簡易サーバ。アクセスログは画面に出る(保存されない)。Ctrl+Cで停止
