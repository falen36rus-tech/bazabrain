FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
RUN DJANGO_SECRET_KEY=build-only-unused python manage.py collectstatic --noinput && \
    useradd --create-home --uid 10001 appuser && \
    mkdir -p /app/private_media && \
    chown -R appuser:appuser /app

USER appuser
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
