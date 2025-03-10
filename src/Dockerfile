FROM python:3.9-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies - fix numpy/pandas compatibility issue
RUN pip install --no-cache-dir numpy==1.24.3
RUN pip install --no-cache-dir -r requirements.txt gunicorn==21.2.0

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/uploads /app/session_data /app/data

# Set environment variables
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8080

# Command to run the application
# Check what the main file is actually named and adjust here
# This assumes your Flask app is in a file named app.py, main.py, or server.py
# with the Flask app instance named 'app'
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 120 --access-logfile=- --error-logfile=- app:app