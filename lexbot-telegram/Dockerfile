# Immagine unica per i due servizi (bot FastAPI e server MCP).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY mcp_server ./mcp_server
COPY data ./data

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Default: bot FastAPI. Per il server MCP:
#   python -m mcp_server.server --port $PORT
# "exec" fa di uvicorn il PID 1: riceve SIGTERM e si arresta in modo pulito.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
