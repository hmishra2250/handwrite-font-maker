FROM python:3.12-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends fontforge potrace \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY src /app/src
COPY scripts /app/scripts
RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "handwrite_font_maker.web.server"]
