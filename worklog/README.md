# 作業記録まとめツール

その日の作業内容を集めて、ブラウザ上で下書きを作り、リポジトリ直下の `README.md` に追記してコミットするツール。
Python 標準ライブラリだけで動くので、追加インストールは要らない。

```
ブラウザ ──> Nginx :80 /worklog/ ──(proxy_pass)──> app.py :8090
```

## 集めるもの

| 項目 | 取得元 |
| --- | --- |
| 実行したコマンド | `~/.bash_history`（日時付きのものはその日の分だけ） |
| apt でのインストール・削除 | `/var/log/apt/history.log*` |
| Nginx 設定 | `/etc/nginx/sites-available/default`（コメントと空行を除く） |
| エラーログ | `/var/log/nginx/error.log*`、`journalctl -u tomcat10` |
| 環境 | `/etc/os-release`、`dpkg-query`（nginx・tomcat・openjdk） |

画面で「やったこと」「ハマった点」「考えたこと・メモ」を書き足し、下書きを確認してから「README に追記」→「コミット」を押す。

## セットアップ

### 1. コマンド履歴に日時を残す

`~/.bashrc` の末尾に次の 1 行を足す。

```bash
[ -f "$HOME/infra-notes/worklog/bash-history.sh" ] && . "$HOME/infra-notes/worklog/bash-history.sh"
```

新しく開いたターミナルから有効になる。これより前の履歴には日時が無いので、画面の「日時のない履歴」から手で選ぶ。

### 2. ツールをサービスとして起動

```bash
systemctl --user enable --now ~/infra-notes/worklog/worklog.service
```

```bash
curl -I http://127.0.0.1:8090/
```

### 3. Nginx から転送する

`nginx-worklog.conf` の `location /worklog/ { ... }` を `/etc/nginx/sites-available/default` の `server { ... }` の中に追記する。

```bash
sudo nano /etc/nginx/sites-available/default
```

```bash
sudo nginx -t
```

```bash
sudo systemctl reload nginx
```

ブラウザで `http://localhost/worklog/` を開く。

## 補足

- `127.0.0.1` 以外からのアクセスは Nginx 側で拒否している。Windows のブラウザで 403 になる場合は、`/var/log/nginx/access.log` で接続元のアドレスを確認して `allow` に足す。
- 他サイトから勝手に追記・コミットされないよう、POST には `X-Worklog: 1` ヘッダーと JSON を必須にしている。
- ポートなどは環境変数で変えられる: `WORKLOG_PORT`、`WORKLOG_HOST`、`WORKLOG_REPO`、`WORKLOG_HISTFILE`、`WORKLOG_NGINX_CONF`。
