FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    jq \
    python3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 -s /bin/bash agent
WORKDIR /workspace
RUN chown -R agent:agent /workspace

USER agent
CMD ["sleep", "infinity"]
