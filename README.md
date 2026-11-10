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
