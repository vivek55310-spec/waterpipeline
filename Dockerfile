# Only needed if you deploy to a host that wants a container (Fly.io, Cloud Run,
# a company server with Docker). Render and an office PC do not need this file.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8000
EXPOSE 8000
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 240
