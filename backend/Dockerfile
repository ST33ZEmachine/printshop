# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY backend/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy backend application code
COPY backend/ .

# Copy agent code from project root
COPY agent.py .

# Copy extraction pipeline (needed for webhook processing)
COPY extractionPipeline/ extractionPipeline/

# Download Linux toolbox binary (the local one is macOS ARM64)
RUN curl -sL "https://storage.googleapis.com/genai-toolbox/v0.21.0/linux/amd64/toolbox" -o /app/toolbox && \
    chmod +x /app/toolbox

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Expose port
EXPOSE 8080

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

