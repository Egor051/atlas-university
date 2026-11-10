# Official Python 3.13.18 image, verified on 2026-11-06; pin the multi-platform index.
FROM python:3.13-slim@sha256:09a17cad02668ae61ece136b4fd36ac3849e14f670ebedb637ea3e15580525bc
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/atlas
COPY requirements.txt requirements-runtime.lock ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements-runtime.lock && groupadd --system atlas && useradd --system --gid atlas --home /srv/atlas atlas
COPY app ./app
COPY static ./static
RUN mkdir -p /srv/atlas/data && chown -R atlas:atlas /srv/atlas
USER atlas
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 CMD python -c "import os,urllib.request; r=urllib.request.Request('http://127.0.0.1:8000/api/ready',headers={'Host':os.environ.get('ALLOWED_HOSTS','localhost').split(',')[0]}); urllib.request.urlopen(r,timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "172.30.60.10", "--limit-concurrency", "100", "--timeout-keep-alive", "5"]
