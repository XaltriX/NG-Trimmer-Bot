FROM python:3.9-slim

# Install system dependencies (including ffmpeg)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set up working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY bot.py .
COPY .env.example .
COPY README.md .

# Create necessary directories
RUN mkdir -p downloads processed thumbnails

# Create a default thumbnail
RUN echo "This is a placeholder thumbnail" > thumbnails/trim_thumb.jpg

# Set environment variables (these will be overridden by docker-compose)
ENV API_ID=your_api_id
ENV API_HASH=your_api_hash
ENV BOT_TOKEN=your_bot_token
ENV BOT_UN=NgTrimmerBot
ENV SUPPORT_LINK=https://t.me/+45z7VdHFcHxiNmI8

# Run the bot
CMD ["python", "bot.py"]
