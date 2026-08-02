FROM python:3.12-slim-bookworm

ARG REELINDEX_VERSION=1.4.5
LABEL org.opencontainers.image.title="ReelIndex" \
      org.opencontainers.image.description="Read-only movie inventory for Windows, Docker, and Unraid" \
      org.opencontainers.image.source="https://github.com/bclark303/ReelIndex" \
      org.opencontainers.image.version="${REELINDEX_VERSION}" \
      org.opencontainers.image.licenses="NOASSERTION" \
      net.unraid.docker.icon="https://raw.githubusercontent.com/bclark303/ReelIndex/main/packaging/unraid/reelindex-icon.png"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    REELINDEX_DATA_DIR=/data \
    REELINDEX_EDITION="Docker / Unraid" \
    REELINDEX_LOG_LEVEL=INFO \
    REELINDEX_DEMO_MODE=false \
    REELINDEX_FFPROBE_PATH=ffprobe \
    REELINDEX_MEDIAINFO_PATH=mediainfo \
    PUID=99 \
    PGID=100 \
    UMASK=002 \
    TZ=Etc/UTC

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       bash ca-certificates curl ffmpeg gosu mediainfo nginx tini tzdata \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY backend/app ./app
COPY web /usr/share/nginx/html
COPY packaging/docker/nginx.conf /etc/nginx/nginx.conf
COPY packaging/docker/start-reelindex.sh /usr/local/bin/start-reelindex
RUN chmod 0755 /usr/local/bin/start-reelindex \
    && mkdir -p /data /tmp/nginx/client_temp /tmp/nginx/proxy_temp \
       /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp

EXPOSE 8080
VOLUME ["/data"]
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/start-reelindex"]
