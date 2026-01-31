# Base image: Python 3.11 (Slim version for smaller size)
FROM python:3.11-slim

# Install system dependencies
# ffmpeg: For sanitization and yt-dlp post-processing
# git: Sometimes needed for python deps
# atomicparsley: For embedding metadata if needed (optional)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    atomicparsley \
    && rm -rf /var/lib/apt/lists/*

# Set working directory inside the container
WORKDIR /app

# Create directories for mounting
# /app/downloads: Temporary dirty storage
# /app/safe_output: Clean storage
# /app/config: For cookies or config files
RUN mkdir -p /app/downloads /app/safe_output /app/config

# Install Python dependencies
# textual: For the beautiful UI
# yt-dlp: The core downloader
# magic: For file type detection in sanitizer
# tqdm: For progress bars
# pillow: For image processing in sanitizer
RUN pip install --no-cache-dir \
    yt-dlp \
    textual \
    python-magic \
    tqdm \
    pillow

# Environment variables
ENV PYTHONUNBUFFERED=1

# The entrypoint will be our TUI app
CMD ["python", "station.py"]
