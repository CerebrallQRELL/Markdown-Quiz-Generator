FROM python:3.13-slim
WORKDIR /app
# Docker CLI talks to the separately supplied engine; it never runs code locally.
RUN apt-get update && apt-get install -y --no-install-recommends docker-cli \
    && rm -rf /var/lib/apt/lists/*
COPY markdown_quiz/ /app/markdown_quiz/
COPY main.py /app/main.py
ENV VAULT_PATH=/vault DATA_PATH=/data PYTHONUNBUFFERED=1
VOLUME ["/data"]
ENTRYPOINT ["python", "-m", "markdown_quiz"]
