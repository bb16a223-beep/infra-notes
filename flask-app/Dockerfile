# 上から読まれるので書き順が大切
FROM python:3.12-slim						# 素のPythonが入ったベースイメージをとってくる
WORKDIR /app							# コンテナ内の作業フォルダを決める
COPY requirements.txt .						# localからrequirement.txtをコンテナへコピー
RUN pip install -r requirements.txt				# PyPIからflask / gunicornなどをインストール
COPY app.py .							# localからapp.pyをコンテナにコピー
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]	# 起動時に gunicorn が app.py を読み込む
