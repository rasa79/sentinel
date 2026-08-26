FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/ /app/services/

EXPOSE 8000

# Default to the orders service; compose overrides this per service (Task 1.2).
CMD ["python", "-m", "services.orders"]
