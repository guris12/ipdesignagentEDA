FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src/ src/
COPY app.py .
COPY generate_report_viewer.py .
COPY start.sh .
COPY data/ data/
COPY content/ content/

RUN pip install --no-cache-dir .

EXPOSE 8501 8001

CMD ["bash", "start.sh"]
