"""MCP (Model Context Protocol) servers and the client the agents use to call them.

MCP is a standard way to expose tools to AI models: a server lists its tools (name, description, JSON
schema) and runs them; a client (our agent) calls them over HTTP. Our servers are mounted inside the same
FastAPI app under /mcp/* and only accept calls made from inside this process (see guard.py).

- portfolio.py  the advisor's data tools (the existing six), always through the access layer
- analytics.py  pure calculations on numbers passed in (no database, no client data stored)
- client.py     McpToolRunner: how the agent loop calls a server; LocalToolRunner for tests and the CLI
"""
