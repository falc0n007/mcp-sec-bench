FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY lab/sinkhole/sinkhole.py /app/sinkhole.py
USER nobody
CMD ["python", "sinkhole.py"]
