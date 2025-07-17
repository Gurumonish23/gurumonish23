# -------------------------
# Stage 1: Base Python + Node.js + Docker CLI
# -------------------------
FROM python:3.11-slim

# Install OS-level dependencies for Docker CLI, Node.js, and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg2 \
    lsb-release \
    apt-transport-https \
    build-essential \
    && rm -rf /var/lib/apt/lists/*


# -------------------------
# Stage 2: Copy & Install Python dependencies
# -------------------------
WORKDIR /app

# Copy only requirements.txt first (if you have one)
# If you do not have a requirements.txt, create one listing all pip packages:
# fastapi, uvicorn, python-dotenv, langchain-openai, langchain-core, langchain-mcp-adapters, etc.
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# -------------------------
# Expose and Entrypoint
# -------------------------
# Expose whichever port your FastAPI serves on (e.g., 8000)
EXPOSE 8080

# By default, run Uvicorn. Adjust if your entrypoint differs.
#CMD ["uvicorn", "client:app", "--host", "0.0.0.0", "--port", "8080"]
CMD ["sh", "-c", "uvicorn client:app --host 0.0.0.0 --port ${PORT}"]
