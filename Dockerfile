# drift-roadbook in a container — for a VPS or any Docker host.
# Narrator inside the container: an API key (ANTHROPIC_API_KEY, optional ANTHROPIC_BASE_URL) or none
# (your companion narrates). The claude CLI subscription mode needs Claude Code on the host instead.
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE LICENSE-CONTENT ./
COPY src ./src
RUN pip install --no-cache-dir ".[api]" && useradd --create-home roadbook && mkdir /data && chown roadbook /data
USER roadbook
ENV ROADBOOK_DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8790
# ROADBOOK_TOKEN is required: the server refuses to listen publicly without it
CMD ["drift-roadbook", "serve", "--host", "0.0.0.0", "--port", "8790"]
