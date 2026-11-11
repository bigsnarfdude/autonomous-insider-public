# Pure executor for the contagion split harness. NO network, NO scorer, NO key ever enters here.
# The host orchestrator makes every model call, captures baseline via `docker exec stat`, and runs
# the disturbance-vector scorer host-side. This container only runs agent shell commands.
#
# Deviation from the solo lock-probe image, on purpose:
#   - sudo is NOT installed. The solo harness dropped root->agent with `sudo -n -u agent`; here the
#     orchestrator drops with `docker exec -u agentN`, so sudo is unnecessary and its absence makes
#     the "agent cannot escalate" invariant hold by construction, not by a passwordless-sudo config.
#   - four distinct unprivileged users, each with a mode-700 home, so the ONLY surface an agent
#     shares with a peer is the room. (§4b clean room.)
# Container init (PID 1, `sleep infinity`) is root, but run with --cap-drop ALL --security-opt
# no-new-privileges at `docker run`, and no setuid path exists, so an agentN shell has no route up.
FROM debian:12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      coreutils findutils sed gzip procps python3-minimal ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# four agents; -M so we create homes explicitly with locked-down perms
RUN for u in agent1 agent2 agent3 agent4; do \
      useradd -M -s /bin/bash "$u" && mkdir -p "/home/$u" && chown "$u:$u" "/home/$u" && chmod 700 "/home/$u"; \
    done
# no login shell state leaks between turns/trials
RUN printf 'export HISTFILE=/dev/null\n' > /etc/profile.d/nohist.sh
WORKDIR /
ENTRYPOINT ["sleep", "infinity"]
