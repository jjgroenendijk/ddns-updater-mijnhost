FROM python:3.12-alpine

LABEL maintainer="dev@jjgroenendijk.nl"
LABEL version="1.0.0"
LABEL description="Dynamic DNS client for mijn.host using Python and Docker."

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY script.py .
COPY dns_config.yml /app/dns_config.default.yml

RUN addgroup -S -g 1000 appgroup && \
    adduser -S -u 1000 -G appgroup -h /app appuser

USER appuser

CMD ["python", "-u", "/app/script.py"]
# The "-u" flag ensures that Python's stdout and stderr are unbuffered,
# which is good for Docker logging.
