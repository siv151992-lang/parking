# ---- build the React frontend
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Python API + ANPR workers (serves the built frontend too)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Use HTTPS mirrors: many corporate / ISP networks block plain HTTP (port 80)
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
ARG WITH_AI=false
COPY backend/requirements.txt backend/requirements-ai.txt ./
# WITH_AI=true adds the real ANPR engine (YOLO + PaddleOCR). PyTorch comes from the
# CPU-only index: the default PyPI build pulls several GB of CUDA libraries.
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$WITH_AI" = "true" ]; then \
         pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu \
         && pip install --no-cache-dir -r requirements-ai.txt \
         && pip install --no-cache-dir --force-reinstall --no-deps opencv-contrib-python==4.10.0.84 ; \
       fi
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
RUN useradd -r -u 1000 -m -d /home/parking parking && mkdir -p media && chown -R parking /app
USER parking
ENV HOME=/home/parking YOLO_CONFIG_DIR=/home/parking/.config/Ultralytics
# Download the YOLO and PaddleOCR models now, so the first start needs no internet.
RUN if [ "$WITH_AI" = "true" ]; then python -m app.anpr.engine --preload; fi
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
