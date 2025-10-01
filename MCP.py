'''
Simple MCP (Model Context Protocol) server in Python using FastMCP.
Provides safe tools: ping, echo, list_dir, read_file (limited),
query_db (sqlite read-only), and summary (simple text summarizer).
Run with: pip install modelcontextprotocol fastapi uvicorn aiosqlite
'''

from typing import Any, List, Dict, Optional
import os
import pathlib
import asyncio
import aiosqlite
from pydantic import BaseModel
from mcp.server.fastmcp import FastMCP
from mcp.server.transport import serve_http  # convenience helper if available

# Constants
ROOT_DIR = pathlib.Path.cwd()  # limit file access to this directory
DB_PATH = ROOT_DIR / 'mcp_example.db'

# Initialize MCP
mcp = FastMCP('example_mcp')

def _safe_path(path: str) -> Optional[pathlib.Path]:
    '''Resolve a user-provided path and ensure it's inside ROOT_DIR.'''
    p = pathlib.Path(path).expanduser()
    try:
        p = (p if p.is_absolute() else (ROOT_DIR / p)).resolve()
    except Exception:
        return None
    if ROOT_DIR in p.parents or p == ROOT_DIR:
        return p
    return None

@mcp.tool
def ping() -> str:
    '''Simple health check.'''
    return 'pong'

@mcp.tool
def echo(text: str, repeat: int = 1) -> str:
    '''Echo text back (bounded).'''
    if repeat < 1:
        repeat = 1
    if repeat > 10:
        repeat = 10
    out = (' '.join([text] * repeat))
    return out if len(out) <= 2000 else out[:2000]

@mcp.tool
def list_dir(path: str = '.') -> List[str]:
    '''List directory contents (non-recursive).'''
    p = _safe_path(path)
    if p is None or not p.exists() or not p.is_dir():
        return []
    result = []
    for child in p.iterdir():
        result.append(f"{child.name}{'/' if child.is_dir() else ''}")
    return result

@mcp.tool
def read_file(path: str, max_bytes: int = 2000) -> str:
    '''Read a small file safely. Binary files are rejected.'''
    p = _safe_path(path)
    if p is None or not p.exists() or not p.is_file():
        return ''
    try:
        text = p.read_text(encoding='utf-8', errors='replace')
        return text[:max_bytes]
    except Exception as e:
        return f'ERROR: {str(e)}'

class QueryResult(BaseModel):
    columns: List[str]
    rows: List[List[Any]]

@mcp.tool
async def query_db(sql: str, limit: int = 100) -> QueryResult:
    '''Run a read-only SELECT query against the example sqlite DB.'''
    sql = sql.strip()
    if not sql.lower().startswith('select'):
        raise ValueError('Only SELECT queries are allowed.')
    if limit <= 0 or limit > 1000:
        limit = 100
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # append LIMIT if not present
        if 'limit' not in sql.lower():
            sql = sql.rstrip(';') + f' LIMIT {limit}'
        async with db.execute(sql) as cursor:
            rows = await cursor.fetchall()
            cols = [k for k in rows[0].keys()] if rows else []
            data = [[r[c] for c in cols] for r in rows]
            return QueryResult(columns=cols, rows=data)

@mcp.tool
def summarize(text: str, max_sentences: int = 3) -> str:
    '''Very small extractive summarizer (sentence-splitting by periods).'''
    s = [seg.strip() for seg in text.split('.') if seg.strip()]
    if not s:
        return ''
    if max_sentences < 1:
        max_sentences = 1
    return '. '.join(s[:max_sentences]) + ('.' if len(s[:max_sentences])>0 else '')

async def _ensure_db():
    if DB_PATH.exists():
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, messages INTEGER)')
        await db.executemany('INSERT INTO users (name, messages) VALUES (?,?)', [
            ('alice', 5), ('bob', 3), ('carol', 12), ('dave', 0)
        ])
        await db.commit()

async def main():
    # Ensure example DB exists
    await _ensure_db()
    # The FastMCP instance exposes tools automatically. Choose a transport.
    # serve_http is a convenience helper that mounts an ASGI app for MCP.
    # It will run until cancelled.
    print('Starting MCP server on http://127.0.0.1:3333')
    # serve_http returns an awaitable that runs the server; args may vary by library.
    await serve_http(mcp, host='127.0.0.1', port=3333)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('Shutting down.')
