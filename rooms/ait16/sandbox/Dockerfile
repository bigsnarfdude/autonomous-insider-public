# AIT-16 workstation: a Python repo, no network (--network none from the core), one unprivileged user.
# The hidden rubric is never copied in; it runs on a second, fresh container after the trial.
FROM python:3.12-slim
RUN useradd -m -s /bin/bash dev
WORKDIR /home/dev
ENTRYPOINT ["sleep", "infinity"]
