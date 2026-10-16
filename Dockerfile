# MCP server (stdio). Zero dependencies — the standard Python image is enough.
#   docker build -t gpt-image-studio .
#   docker run -i --rm -e OPENAI_API_KEY=sk-... gpt-image-studio
FROM python:3.12-slim
WORKDIR /app
COPY . .
CMD ["python", "scripts/mcp_server.py"]
