FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends docker-cli && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY markdown_quiz/ /app/markdown_quiz/
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "markdown_quiz.api", "--managed", "--host", "0.0.0.0", "--port", "8765"]
