# WSL + Ubuntu + Nginx + Tomcat リバースプロキシ構築メモ

作業日: 2026-11-10

WSL2 上の Ubuntu に Nginx と Tomcat をインストールし、Nginx (80番) で受けたリクエストを Tomcat (8080番) へリバースプロキシで転送する手順。

## 構成

```
ブラウザ ──> Nginx :80 ──(proxy_pass)──> Tomcat :8080
```

## 環境

| 項目 | バージョン |
| --- | --- |
| OS | Ubuntu 26.04.1 LTS (WSL2) |
| Nginx | 1.28.3 |
| Tomcat | 10.1.55 (`tomcat10` パッケージ) |
| Java | OpenJDK 25 |

## 1. WSL に Ubuntu をインストール

Windows の PowerShell (管理者) で実行する。

```powershell
wsl --install -d Ubuntu
```

インストール後に再起動し、Ubuntu を起動してユーザー名とパスワードを設定する。

確認:

```powershell
wsl -l -v
```

`VERSION` が `2` になっていれば WSL2 で動いている。

## 2. パッケージを最新化

ここから先は Ubuntu のターミナルで実行する。

```bash
sudo apt update
sudo apt upgrade -y
```

## 3. Nginx をインストール

```bash
sudo apt install -y nginx
sudo systemctl enable --now nginx
```

確認:

```bash
nginx -v
systemctl status nginx
curl -I http://localhost
```

`HTTP/1.1 200 OK` が返り、ブラウザで `http://localhost` を開くと "Welcome to nginx!" が表示されれば OK。

## 4. Tomcat をインストール

Java (OpenJDK) は依存関係として一緒に入る。

```bash
sudo apt install -y tomcat10
sudo systemctl enable --now tomcat10
```

確認:

```bash
java -version
systemctl status tomcat10
curl -I http://localhost:8080
```

ブラウザで `http://localhost:8080` を開くと "It works !" が表示されれば OK。

## 5. Nginx からリバースプロキシで Tomcat へ転送

`/etc/nginx/sites-available/default` を編集する。

```bash
sudo nano /etc/nginx/sites-available/default
```

`location /` の中身を `proxy_pass` に書き換える。

```nginx
server {
	listen 80 default_server;
	listen [::]:80 default_server;

	root /var/www/html;
	index index.html index.htm index.nginx-debian.html;

	server_name _;

	location / {
		proxy_pass http://127.0.0.1:8080;
	}
}
```

構文チェックしてから反映する。

```bash
sudo nginx -t
sudo systemctl reload nginx
```

確認:

```bash
curl http://localhost
```

ポート番号なしの `http://localhost` で Tomcat の "It works !" ページが表示されればリバースプロキシ成功。

### Nginx 経由で Tomcat が応答しているかの見分け方

`curl -I http://localhost` の結果は `Server: nginx/1.28.3 (Ubuntu)` になる。これは Nginx が転送時に `Server` ヘッダーを自分の名前で上書きするためで、中身が Tomcat かどうかは別の項目で判断する。

```bash
curl -I http://localhost
curl -I http://127.0.0.1:8080
```

| 見るところ | Tomcat から返っている場合 |
| --- | --- |
| `ETag` | `W/"1905-1794309803442"` のような「サイズ-更新時刻(ミリ秒)」の形 (Nginx 自身なら `"xxxx-xxxx"` の16進数) |
| 80番と8080番の比較 | `ETag` と `Content-Length` が一致する |
| 本文 | `curl -s http://localhost \| grep -i "<title>"` で `<title>Apache Tomcat</title>` が出る |

## ハマった点

### セミコロンの付け忘れ

Nginx の設定は 1 つのディレクティブごとに末尾の `;` が必須。

```nginx
# NG
proxy_pass http://127.0.0.1:8080

# OK
proxy_pass http://127.0.0.1:8080;
```

付け忘れると `nginx -t` で次の行と繋がって解釈され、以下のようなエラーになる。

```
nginx: [emerg] invalid number of arguments in "proxy_pass" directive in /etc/nginx/sites-enabled/default:...
```

エラーで指摘される行が、実際に `;` を忘れた行の **次の行** になることがあるので、指摘行の 1 つ上も確認する。

`upstream` ブロックの `server` 行でも同じミスをした。

```nginx
# NG (2行が1つのディレクティブとして読まれる)
upstream tomcat {
	server 127.0.0.1:8080
	server 127.0.0.1:8081
}

# OK
upstream tomcat {
	server 127.0.0.1:8080;
	server 127.0.0.1:8081;
}
```

この場合は `;` がないまま `}` まで読み進むので、`unexpected "}"` のようなエラーになり、指摘されるのは `}` の行になる。

### upstream 名と proxy_pass の名前の不一致

`upstream` で付けた名前と `proxy_pass` に書く名前は完全に一致させる。

```nginx
upstream tomcat {
	...
}

# NG (s が余計)
proxy_pass http://tomcats;

# OK
proxy_pass http://tomcat;
```

不一致だと `nginx -t` で以下のエラーになる。

```
nginx: [emerg] host not found in upstream "tomcats" in /etc/nginx/sites-enabled/default:...
```

### 波カッコの閉じ忘れ

`server { ... }` や `location / { ... }` の `}` を閉じ忘れると、以下のエラーになる。

```
nginx: [emerg] unexpected end of file, expecting "}" in /etc/nginx/sites-enabled/default:...
```

ファイル末尾で怒られるので場所が分かりにくい。`{` と `}` の数が揃っているか、インデントを揃えて確認する。

### 教訓

- 設定を変えたら **必ず `sudo nginx -t` を実行してから** `reload` する
- `nginx -t` が `syntax is ok` / `test is successful` を返すまで反映しない

## よく使うコマンド

```bash
# 状態確認
systemctl status nginx
systemctl status tomcat10

# 再起動・設定反映
sudo systemctl restart nginx
sudo systemctl reload nginx
sudo systemctl restart tomcat10

# ログ
sudo tail -f /var/log/nginx/error.log
sudo journalctl -u tomcat10 -f
```

## 作業記録

### 2026-11-15 NginxからTomcaで負荷分散

#### 実行したコマンド

```bash
sudo nginx -t
sudo systemctl reload nginx
curl -I http://localhost/worklog
curl -I http://localhost/worklog/
sudo cp /etc/nginx/sites-available/default /etc/nginx/sites-available/default .bak
sudo cp /etc/nginx/sites-available/default /etc/nginx/sites-available/default.bak
sudo sed -i '/^\s*location \/ {/i\
\tlocation /worklog/ {\
\t\tallow 127.0.0.1;\
\t\tallow ::1;\
\t\tdeny all;\
\t\tproxy_pass http://127.0.0.1:8090/;\
\t\tproxy_set_header Host $host;\
\t}\
' /etc/nginx/sites-available/default
grep -n -B1 -A8 "location /worklog/" /etc/nginx/sites-available/default
curl -I http://localhost/worklog/
sudo nginx -t
curl -I http://localhost/worklog
sudo systemctl reload nginx.service
curl -I http://localhost/worklg
curl -I http://localhost/worklog
```

#### Nginx 設定

`/etc/nginx/sites-available/default`

```nginx
upstream tomcats {
	server 127.0.0.1:8080;
	server 127.0.0.1:8081;
}
server {
	listen 80 default_server;
	listen [::]:80 default_server;
	root /var/www/html;
	index index.html index.htm index.nginx-debian.html;
	server_name _;
	location /worklog/ {
		allow 127.0.0.1;
		allow ::1;
		deny all;
		proxy_pass http://127.0.0.1:8090/;
		proxy_set_header Host $host;
	}
	location / {
		proxy_pass http://tomcats;
	}
}
```

#### ハマった点

-upstream でserverのあとにコロンを忘れた

#### エラーログ

```
2026-11-15T18:39:37+09:00 DesktopPC tomcat10[292]: WARNING: A restricted method in java.lang.System has been called
2026-11-15T18:39:37+09:00 DesktopPC tomcat10[292]: WARNING: java.lang.System::load has been called by org.apache.tomcat.jni.Library in an unnamed module (file:/usr/share/java/tomcat10-jni-10.1.55.jar)
2026-11-15T18:39:37+09:00 DesktopPC tomcat10[292]: WARNING: Use --enable-native-access=ALL-UNNAMED to avoid a warning for callers in this module
2026-11-15T18:39:37+09:00 DesktopPC tomcat10[292]: WARNING: Restricted methods will be blocked in a future release unless native access is enabled
```

#### 環境

| 項目 | バージョン |
| --- | --- |
| OS | Ubuntu 26.04.1 LTS |
| nginx | 1.28.3-2ubuntu1.12 |
| openjdk-25-jdk-headless | 25.0.5.0.3+1-1~26.04.1 |
| openjdk-25-jre-headless | 25.0.5.0.3+1-1~26.04.1 |
| tomcat-jakartaee-migration | 1.0.10-2 |
| tomcat10 | 10.1.55-1ubuntu2~26.04.1 |
| tomcat10-common | 10.1.55-1ubuntu2~26.04.1 |
