FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
WORKDIR /app
COPY *.py /app/
COPY static /app/static
EXPOSE 8080
CMD ["python", "server.py"]
