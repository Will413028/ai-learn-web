FROM python:3.14-slim
ENV PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN pip install --no-cache-dir uv==0.7.2 && useradd --uid 10001 --create-home app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
RUN mkdir /data && chown app:app /data
USER app
ENV ASSET_DIRECTORY=/data
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100", "--timeout-keep-alive", "65"]
