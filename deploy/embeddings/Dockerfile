# Public Python runtime pinned to the manifest digest verified during this change.
FROM python:3.12-slim-bookworm@sha256:6dd8b6dab6b3adc7812bab69eca5dbdc1a5cc690ad28306d234ffb4ef8ac9753
COPY scripts/fetch_embeddings.py /opt/embedding-bootstrap/fetch_embeddings.py
CMD ["python3", "-B", "/opt/embedding-bootstrap/fetch_embeddings.py", "--directory", "/models", "--no-env-file", "--runtime-cache", "/runtime"]
