FROM python:3.11-slim

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .

ENV MEDIA_HOST=http://localhost:8000 \
    DATABASE_URL=mysql+pymysql://root:root@host.docker.internal:3306/kabel

EXPOSE 8000

CMD ["sh", "-c", "kabel --host=0.0.0.0 --port=8000 --media-host=$MEDIA_HOST"]
