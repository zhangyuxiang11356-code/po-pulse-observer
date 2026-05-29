ARG BASE_IMAGE=python:3.12-slim-bookworm
FROM ${BASE_IMAGE}

WORKDIR /app

# Latest releases available at https://github.com/aptible/supercronic/releases
ARG TARGETARCH
ENV SUPERCRONIC_VERSION=v0.2.39

# Pin Node.js to an LTS line that works better with rss-agent-viewer/better-sqlite3.
ARG NODE_MAJOR=20

RUN set -ex && \
    if command -v supercronic >/dev/null 2>&1; then \
        echo "supercronic already present, skipping install"; \
        supercronic -version; \
    else \
        apt-get update && \
        apt-get install -y --no-install-recommends curl ca-certificates && \
        case ${TARGETARCH} in \
        amd64) \
        export SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64; \
        export SUPERCRONIC_SHA1SUM=c98bbf82c5f648aaac8708c182cc83046fe48423; \
        export SUPERCRONIC=supercronic-linux-amd64; \
        ;; \
        arm64) \
        export SUPERCRONIC_URL=https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-arm64; \
        export SUPERCRONIC_SHA1SUM=5ef4ccc3d43f12d0f6c3763758bc37cc4e5af76e; \
        export SUPERCRONIC=supercronic-linux-arm64; \
        ;; \
        *) \
        echo "Unsupported architecture: ${TARGETARCH}"; \
        exit 1; \
        ;; \
        esac && \
        echo "Downloading supercronic for ${TARGETARCH} from ${SUPERCRONIC_URL}" && \
        for i in 1 2 3; do \
            echo "Download attempt $i/3"; \
            if curl -fsSL --connect-timeout 30 --max-time 60 -o "$SUPERCRONIC" "$SUPERCRONIC_URL"; then \
                echo "Download successful"; \
                break; \
            else \
                echo "Download attempt $i failed"; \
                if [ $i -eq 3 ]; then \
                    echo "All download attempts failed"; \
                    exit 1; \
                fi; \
                sleep 2; \
            fi; \
        done && \
        echo "${SUPERCRONIC_SHA1SUM}  ${SUPERCRONIC}" | sha1sum -c - && \
        chmod +x "$SUPERCRONIC" && \
        mv "$SUPERCRONIC" "/usr/local/bin/${SUPERCRONIC}" && \
        ln -sf "/usr/local/bin/${SUPERCRONIC}" /usr/local/bin/supercronic && \
        supercronic -version && \
        apt-get remove -y curl && \
        apt-get clean && \
        rm -rf /var/lib/apt/lists/*; \
    fi

RUN set -ex && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs build-essential python3 make g++ && \
    npm install -g rss-agent-viewer && \
    node --version && \
    npm --version && \
    rss-viewer --help >/dev/null && \
    apt-get purge -y --auto-remove gnupg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install --with-deps chromium

COPY docker/manage.py .
COPY trendradar/ ./trendradar/

COPY docker/entrypoint.sh /entrypoint.sh.tmp
RUN sed -i 's/\r$//' /entrypoint.sh.tmp && \
    mv /entrypoint.sh.tmp /entrypoint.sh && \
    chmod +x /entrypoint.sh && \
    chmod +x manage.py && \
    mkdir -p /app/config /app/output

ENV PYTHONUNBUFFERED=1 \
    CONFIG_PATH=/app/config/config.yaml \
    FREQUENCY_WORDS_PATH=/app/config/frequency_words.txt

ENTRYPOINT ["/entrypoint.sh"]
