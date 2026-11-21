FROM python:3.12-alpine
WORKDIR /app
COPY app.py .
# Runs as an unprivileged user; only /data (cache + prefs) is written. The host folder mounted
# there must be owned by uid 1000.
RUN adduser -D -u 1000 app && mkdir -p /data && chown app:app /data
USER app
ENV PYTHONUNBUFFERED=1
EXPOSE 8791
HEALTHCHECK --interval=60s --timeout=5s CMD wget -qO- http://127.0.0.1:8791/health || exit 1
CMD ["python", "app.py"]
