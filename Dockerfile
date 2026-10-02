# Hosted booth (Railway / Render / Fly / any Docker host)
FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Multi-device booth: PIN gate + LAN-style shared writes on one server
ENV FOOTBALL_EPA_SHARED=1
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Persist /app/data via a volume on the host (live log, DB, roster, drafts)
VOLUME ["/app/data"]

EXPOSE 8501

# Cloud hosts inject $PORT
CMD ["sh", "-c", "exec python -m streamlit run step4_dashboard.py --server.address 0.0.0.0 --server.port ${PORT:-8501}"]
