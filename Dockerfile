# Remote/HTTP deployment (Smithery, Render, Fly, Cloud Run, K8s, ...)
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV AKYLA_MCP_TRANSPORT=http \
    HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000

CMD ["akyla-mcp", "--transport", "http"]
