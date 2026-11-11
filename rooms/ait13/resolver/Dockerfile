# Mock DNS resolver: a non-forwarding stdlib stub. No packages, no upstream.
FROM python:3.12-slim
COPY server.py /srv/server.py
# runs as root only to bind :53 inside its own isolated container; it has no capabilities that reach
# outside the internal network, and no code path that forwards a query.
CMD ["python3", "/srv/server.py"]
