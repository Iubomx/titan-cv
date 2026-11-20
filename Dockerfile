# TITAN CV en contenedor: pensado para análisis y descubrimiento (sin navegador).
# El robot de postulación necesita Chrome con ventana para los pasos humanos (login, CAPTCHA): úsalo en tu equipo.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CVTITAN_HOME=/workspace
WORKDIR /app
COPY pyproject.toml README.md ./
COPY cvtitan ./cvtitan
COPY config ./config
COPY candidate/*.example.yaml ./candidate/
RUN pip install --no-cache-dir .

# Tus datos viven fuera de la imagen: monta una carpeta con candidate/ y data/ en /workspace.
VOLUME /workspace
WORKDIR /workspace
ENTRYPOINT ["cvtitan"]
CMD ["--help"]
