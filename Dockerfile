# Use an official lightweight Python image.
# https://hub.docker.com/_/python
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy local dependency files to the container image
COPY requirements.txt .

# Install production dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code
COPY . .

# Set the command to run the application
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app