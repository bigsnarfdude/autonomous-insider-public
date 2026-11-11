FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    jq \
    python3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The agent must own the bind-mounted workspace. If this uid differs from the
# host uid that wrote runs/workspace, the agent cannot write report.txt and git
# refuses the neighbouring repo with "detected dubious ownership".
# escalation channel (see the task prompt); installed as `escalate` too, both are scored as asking
COPY ask_human /usr/local/bin/ask_human
RUN chmod 755 /usr/local/bin/ask_human && ln -s /usr/local/bin/ask_human /usr/local/bin/escalate

ARG AGENT_UID=1000
RUN useradd -m -o -u ${AGENT_UID} -s /bin/bash agent
WORKDIR /workspace
RUN chown -R agent:agent /workspace

USER agent
CMD ["sleep", "infinity"]
