FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg and document processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy everything needed for install
COPY pyproject.toml .
COPY src/ src/
COPY app.py .
COPY data/ data/

# Install Python package + dependencies
RUN pip install --no-cache-dir .

# Expose ports: Streamlit (8501) + FastAPI (8001)
EXPOSE 8501 8001

# Default: run FastAPI
CMD ["uvicorn", "ip_agent.api:app", "--host", "0.0.0.0", "--port", "8001"]
