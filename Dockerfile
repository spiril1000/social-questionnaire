# social-questionnaire: one image for every questionnaire site. Which site a container is comes
# from its PRESET env var; its questions/settings and responses live in the /config and /data volumes.
FROM python:3.12-alpine

LABEL org.opencontainers.image.title="social-questionnaire" \
      org.opencontainers.image.description="Joke questionnaire sites (rate your hookup, ghosting exit interview, post-date survey) with a mobile admin" \
      org.opencontainers.image.source="https://github.com/spiril1000/social-questionnaire" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONFIG_DIR=/config \
    DATA_DIR=/data \
    PRODUCTION=true \
    PUID=1000 \
    PGID=1000

# cairo renders the home-screen icon PNGs for the installable admin (cairosvg);
# su-exec lets the entrypoint drop from root to PUID:PGID
RUN apk add --no-cache cairo su-exec

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ .
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && mkdir -p /config /data

VOLUME ["/config", "/data"]
EXPOSE 8000

HEALTHCHECK --interval=1m --timeout=10s --start-period=15s --retries=3 \
    CMD wget -q -O /dev/null http://localhost:8000/healthz || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
# One worker process, so the in-memory rate limit is shared; threads handle concurrent requests
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--access-logfile", "-", "app:app"]
