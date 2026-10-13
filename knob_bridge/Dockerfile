FROM python:3.13-slim
ARG BUILD_VERSION=0.8.0
ARG BUILD_ARCH=amd64
LABEL io.hass.version=$BUILD_VERSION io.hass.type="app" io.hass.arch=$BUILD_ARCH
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mesh.py bridge.py clock_sync.py weather_sync.py weather_source.py ./
COPY light_control.py mesh_crypto.py knob_mesh_commands.py channel_control.py ./
COPY light_sync.py display_config.py knob_display_codec.py ./
COPY light_imports.py ./
COPY import_ui.py ./
COPY web ./web
CMD ["python", "-u", "/app/bridge.py"]
