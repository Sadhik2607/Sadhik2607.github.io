# MigrateForge runs a Python -> Node.js pipeline, so the image needs both.
FROM python:3.11-slim

# Install Node.js 18 (for the transform stage) alongside Python
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: run the ACME sample migration end-to-end.
ENTRYPOINT ["python", "main.py"]
CMD ["--client", "acme", "--input", "data/raw/acme.csv"]
