FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt requirements-production.txt ./
RUN pip install -r requirements-production.txt \
    && groupadd --gid 10001 kmg \
    && useradd --uid 10001 --gid kmg --no-create-home kmg

COPY --chown=kmg:kmg . .
RUN mkdir -p /app/media /app/private_vault /app/logs /app/staticfiles \
    && chown -R kmg:kmg /app/media /app/private_vault /app/logs /app/staticfiles
USER kmg
# Khóa tạm chỉ để build static; runtime bắt buộc nạp khóa riêng và MySQL từ môi trường.
RUN KMG_ENV_FILE='' KMG_BUILD_STATIC=1 DEBUG=False DB_ENGINE=sqlite ALLOWED_HOSTS=localhost \
    SECRET_KEY=build-only-static-secret-key-0000000000000000 \
    CERT_SIGNING_KEY=build-only-static-certificate-key-000000000000 \
    CHAT_MASTER_KEK=build-only-static-chat-master-key-000000000000 \
    python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--config", "deployment/gunicorn.conf.py"]
