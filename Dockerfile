FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR /opt/tai-helper

COPY pyproject.toml README.md ./
COPY tai_helper ./tai_helper
COPY static ./static
COPY data ./data

RUN pip install --no-cache-dir uv \
    && uv pip install --system -e .

EXPOSE 7860

CMD ["uvicorn", "tai_helper.api:app", "--host", "0.0.0.0", "--port", "7860"]
