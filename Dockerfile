FROM python:3.12-alpine
WORKDIR /app
COPY app.py .
ENV PYTHONUNBUFFERED=1
EXPOSE 8791
HEALTHCHECK --interval=60s --timeout=5s CMD wget -qO- http://127.0.0.1:8791/health || exit 1
CMD ["python", "app.py"]
