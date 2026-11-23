import os                                   # 環境変数(os.environ)やファイルパスを読み込むための標準ライブラリ
import socket                               # host名(socket.gethostname())やネットワーク関連の情報を扱う機能
import psycopg2                             # PostgreSQLの接続用のライブラリ
from flask import Flask                     # flaskのパッケージからFlaskのクラスだけを持ってくる

# app = Flask(...)で直接機能を呼ぶことができる(ない場合：flask.Flaskって呼び方をする)
# ModuleNotFoundError: No mudule named '___' は今実行しているPython環境に存在しない
app = Flask(__name__)

def get_conn():                                             # def:関数として宣言　get_conn:DB接続を作る関数
    return psycopg2.connect(
            host="db",                      
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
        )

# ① /にリクエスト②　Flask/Gunicornからindexが呼び出される③　indexからget_connが呼び出される④　Returnで値を返す

@app.route("/")                                                             # [/]にアクセスがあったときに呼び出される印
def index():                                                                # アクセス時の処理をindexという名前で定義
    conn = get_conn()                                                       # ここで前に定義したget_conn()を呼び出し
    with conn:
        with conn.cursor() as cur:                                          # PostgreSQLにSQL文を送るカーソルを作る
            cur.execute(
                    "CREATE TABLE IF NOT EXISTS hits "                      # hitsのテーブルがなければ作成
                    "(id SERIAL PRIMARY KEY, at TIMESTAMP DEFAULT now())"   # id SERIAL PRIMARY KEY:連番の主キーを振る
            )                                                               # at TIMESTAMP DEFAULT now() でアクセスした日時がわかるようにしている
            cur.execute("INSERT INTO hits DEFAULT VALUES")                  # hitsテーブルに新しい行を１行追加、id atが自動で入るためDEFAULT VALUESと記載
            cur.execute("SELECT count(*) FROM hits")                        # hitsテーブルにある全レコード数を数えてcount(*)
            n = cur.fetchone()[0]                                           # 結果の１行目から先頭の数値３を取り出して変数ｎにいれている
            # ↑ ここで cur が自動でクローズされる
    # ↑ ここで with conn ブロック終了（エラーがなければ自動で COMMIT される）トランザクション管理
    conn.close()
    return f"Hello from Flask (hits: {n}) host:{socket.gethostname()}\n"


