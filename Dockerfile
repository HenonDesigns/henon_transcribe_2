FROM python:3.12

WORKDIR /app

RUN pip install --no-cache-dir uwsgi

COPY requirements.txt /app
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 8000

CMD ["uwsgi", "--http", "0.0.0.0:8000", "--wsgi-file", "henon_transcribe_2/app.py", "--callable", "app", "--master", "--processes", "4", "--threads", "2"]