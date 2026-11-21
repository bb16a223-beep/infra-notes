import os 
import psycopg2
from flask import Flask


app = Flask(__name__)


def get_conn():
    return psycopg2.connect(
            host="db",
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
        )


@app.route("/")
def index():
    conn = get_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                    "CREATE TABLE IF NOT EXISTS hits "
                    "(id SERIAL PRIMARY KEY, at TIMESTAMP DEFAULT now())"
            )
            cur.execute("INSERT INTO hits DEFAULT VALUES")
            cur.execute("SELECT count(*) FROM hits")
            n = cur.fetchone()[0]
    conn.close()
    return f"Hello from Flask (hits: {n})\n"

