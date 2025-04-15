# Use Python base image
FROM python:3.11-slim

# Install the project into `/app`
WORKDIR /app

# Copy the entire project
COPY . /app

# Install the package
RUN pip install --no-cache-dir -e .

# Run the server
ENTRYPOINT ["mcp-server-zoom-noauth"] 