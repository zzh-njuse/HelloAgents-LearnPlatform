FROM python:3.12-slim AS base

WORKDIR /app

# adapter.py does "from shared.mcp_execution_contract import ..."
# → /app/apps must be on PYTHONPATH so "shared" resolves
# mcp_execution_server.py does "from adapter import ..."
# → /app/apps/mcp_execution must be on PYTHONPATH
# CMD is "python -m mcp_execution_server"
# → /app/apps/mcp_execution must be on PYTHONPATH
ENV PYTHONPATH=/app/apps/mcp_execution:/app/apps

COPY apps/mcp_execution/requirements.txt /tmp/req.txt
RUN pip install --no-cache-dir -r /tmp/req.txt && rm /tmp/req.txt

COPY apps/shared /app/apps/shared
COPY apps/mcp_execution /app/apps/mcp_execution

EXPOSE 8100

CMD ["python", "-m", "mcp_execution_server"]
