FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable
COPY config ./config
COPY templates ./templates
COPY benchmark ./benchmark
ENV PATH="/app/.venv/bin:$PATH"
VOLUME ["/app/data", "/app/docs", "/app/reports"]
ENTRYPOINT ["scholaradar"]
CMD ["--help"]
