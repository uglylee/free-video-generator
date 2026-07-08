# Agnes Video Generator — container image
FROM python:3.12-slim

# ffmpeg: required by moviepy and the [Compositor] step for clip concat,
# audio muxing, and subtitle burn-in. CJK fonts are bundled under
# resource/fonts/, so no system font packages are needed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency layer — cached unless requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY . .

# server.py binds 0.0.0.0:8765 (Web UI + REST + WebSocket).
EXPOSE 8765

CMD ["python", "server.py"]
