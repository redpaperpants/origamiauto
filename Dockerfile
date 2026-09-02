# Use the official Playwright Python image containing all browser dependencies
FROM mcr.microsoft.com/playwright/python:v1.62.0-jammy

WORKDIR /app

# Copy requirements and install packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application code
COPY . .

# Run the script using Python unbuffered mode for real-time logs
CMD ["python", "-u", "auto_caption.py"]
