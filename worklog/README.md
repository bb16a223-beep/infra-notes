# 作業記録ワークフロー

その日の作業を GitHub Actions のようなワークフローで集めてまとめ、リポジトリ直下の `README.md` に追記してコミットするツール。
Python 標準ライブラリだけで動くので、追加インストールは要らない。

```
ブラウザ ──> Nginx :80 /worklog/ ──(proxy_pass)──> app.py :8090 ──> pipeline.py ──> runs/*.json
                                                                       ▲
                                    worklog-daily.timer（毎時）────────┘
```

## ワークフロー

定義は [workflow.toml](workflow.toml)。GitHub Actions の workflow ファイルに相当する。

```
コマンド履歴を集める ─┐
apt 履歴を集める     ─┤
エラーログを集める   ─┼─▶ 下書きを作る ─▶ 承認 ─▶ README に追記 ─▶ コミット
Nginx 設定を記録する ─┤      (自動)      (手動)       (自動)          (自動)
環境を記録する       ─┘
```

- 1 回の実行を Run と呼び、`runs/00001.json` のように保存する（コマンド履歴を含むので git には入れない）
- 「承認」ステップで止まり、画面で承認するまで README には何も書かない
- コマンド・apt・エラー・Nginx 設定の変更がどれもない日は「作業なし」で終わる

## 画面

`http://localhost/worklog/`

| 画面 | 役割 |
| --- | --- |
| 実行一覧 | Run の一覧。状態（成功・失敗・承認待ち・作業なし）とステップごとの結果が並ぶ |
| 実行の詳細 | ステップを線でつないだグラフ。ブロックをクリックするとそのステップのログが見える。失敗したら「失敗したステップを再実行」 |
| 進捗 | 承認待ちの Run を ①収集 → ②選ぶ → ③書く → ④確認 → ⑤追記・コミット の順に進める。入力は途中で保存される |

## 自動実行

`worklog-daily.timer` が毎時 5 分に `pipeline.py schedule` を動かす。
`workflow.toml` の `schedule`（既定 23:00）を過ぎていて、まだ自動実行していない日があれば Run を作る。
PC や WSL が止まっていた日も、最大 7 日さかのぼって作る。

手動で動かす場合:

```bash
python3 ~/infra-notes/worklog/pipeline.py run
```

```bash
python3 ~/infra-notes/worklog/pipeline.py run --date 2026-11-10
```

## セットアップ

### 1. コマンド履歴に日時を残す

`~/.bashrc` の末尾に次の 1 行を足す。

```bash
[ -f "$HOME/infra-notes/worklog/bash-history.sh" ] && . "$HOME/infra-notes/worklog/bash-history.sh"
```

### 2. 画面のサービスと自動実行のタイマーを有効にする

```bash
systemctl --user enable --now ~/infra-notes/worklog/worklog.service
```

```bash
systemctl --user link ~/infra-notes/worklog/worklog-daily.service
```

```bash
systemctl --user enable --now ~/infra-notes/worklog/worklog-daily.timer
```

### 3. Nginx から転送する

[nginx-worklog.conf](nginx-worklog.conf) の `location /worklog/ { ... }` を `/etc/nginx/sites-available/default` の `server { ... }` の中に追記して、`sudo nginx -t` → `sudo systemctl reload nginx`。

## よく使うコマンド

```bash
# 画面のサービスの状態とログ
systemctl --user status worklog.service
journalctl --user -u worklog.service -f

# 次の自動実行の時刻と、自動実行のログ
systemctl --user list-timers worklog-daily.timer
journalctl --user -u worklog-daily.service

# pipeline.py や index.html を変えたあと
systemctl --user restart worklog.service
```

## 補足

- `127.0.0.1` 以外からのアクセスは Nginx 側で拒否している。
- 他サイトから勝手に承認・コミットされないよう、POST には `X-Worklog: 1` ヘッダーと JSON を必須にしている。
- 環境変数で変えられるもの: `WORKLOG_PORT`、`WORKLOG_HOST`、`WORKLOG_REPO`、`WORKLOG_RUNS`、`WORKLOG_HISTFILE`、`WORKLOG_NGINX_CONF`。
