# ==============================================================================
# DOTMIND 24/7 Always-On Personal AI Agent — Production Dockerfile
# Optimized for Render.com, Fly.io, Koyeb, Railway, and VPS
# ==============================================================================

FROM python:3.12-slim

# Prevent python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    ENVIRONMENT=production \
    DOTMIND_USE_GENAI_SERVICE=true \
    GENAI_SERVICE_URL=http://127.0.0.1:8001

WORKDIR /app

# 1. Install system utilities and Node.js 20 LTS for official @google/genai microservice
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    procps \
    git \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && npm install -g pnpm \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 2. Install Node.js dependencies for GenAI microservice
COPY genai-service/package.json genai-service/pnpm-lock.yaml* /app/genai-service/
RUN cd /app/genai-service && (pnpm install --prod || npm install --production)

# 3. Install Python dependencies
COPY backend/requirements.txt /app/backend/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# 4. Copy backend and genai-service source code
COPY backend /app/backend
COPY genai-service /app/genai-service
COPY resources /app/resources
COPY start_cloud.sh /app/start_cloud.sh

# 5. Make startup script executable and configure workspace root
RUN chmod +x /app/start_cloud.sh \
    && mkdir -p /app/backend/uploads /app/backend/data

EXPOSE 8000 10000

CMD ["/app/start_cloud.sh"]
