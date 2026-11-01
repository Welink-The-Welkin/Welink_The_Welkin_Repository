FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WANDERER_DEMO_MODE=offline \
    WANDERER_DATABASE_PATH=/app/data/sessions.db

# Supply deployment values at runtime; no TTS runtime or assets enter this image.
ENV WANDERER_TTS_ENABLED="" \
    WANDERER_TTS_API_URL="" \
    WANDERER_TTS_REFERENCE_AUDIO="" \
    WANDERER_TTS_PROMPT_TEXT="" \
    WANDERER_TTS_TIMEOUT=""

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY .env.example README.md ./

RUN mkdir -p /app/data

EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
