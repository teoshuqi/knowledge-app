# Minimal stub for prefect-worker (F-03). Dependency pinning and the final
# image build (BERTopic + sub-deps, embedding backend, LLM libs) land in H-04 —
# this just needs to be runnable, not complete.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY . .
