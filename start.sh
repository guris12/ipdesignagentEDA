#!/bin/bash
# Initialize database: ensure pgvector extension and langchain tables exist
# Tables are created here (before services start) to avoid ORM race conditions
# when both uvicorn and streamlit import ip_agent simultaneously
python -c "
import json, os
db_host = os.environ.get('DB_HOST', 'localhost')
db_port = os.environ.get('DB_PORT', '5432')
db_name = os.environ.get('DB_NAME', 'ip_agent_db')
creds = os.environ.get('DB_CREDENTIALS', '')
if creds:
    c = json.loads(creds)
    user, pw = c['username'], c['password']
else:
    user = os.environ.get('DB_USERNAME', 'ip_agent')
    pw = os.environ.get('DB_PASSWORD', '')

import psycopg
conn = psycopg.connect(f'host={db_host} port={db_port} dbname={db_name} user={user} password={pw}')
conn.autocommit = True
conn.execute('CREATE EXTENSION IF NOT EXISTS vector')
conn.execute('''
    CREATE TABLE IF NOT EXISTS langchain_pg_collection (
        uuid UUID NOT NULL PRIMARY KEY,
        name VARCHAR NOT NULL UNIQUE,
        cmetadata JSON
    )
''')
conn.execute('''
    CREATE TABLE IF NOT EXISTS langchain_pg_embedding (
        id VARCHAR NOT NULL PRIMARY KEY,
        collection_id UUID REFERENCES langchain_pg_collection(uuid) ON DELETE CASCADE,
        embedding vector,
        document VARCHAR,
        cmetadata JSON
    )
''')
print('Database ready: pgvector + langchain tables')
conn.close()
" 2>&1 || echo "DB init warning (non-fatal)"

# Run ingest if DB is empty (safe to re-run — skips if data already exists)
python -c "
import psycopg, json, os
db_host = os.environ.get('DB_HOST', 'localhost')
db_port = os.environ.get('DB_PORT', '5432')
db_name = os.environ.get('DB_NAME', 'ip_agent_db')
creds = os.environ.get('DB_CREDENTIALS', '')
if creds:
    c = json.loads(creds)
    user, pw = c['username'], c['password']
else:
    user = os.environ.get('DB_USERNAME', 'ip_agent')
    pw = os.environ.get('DB_PASSWORD', '')
conn = psycopg.connect(f'host={db_host} port={db_port} dbname={db_name} user={user} password={pw}')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM langchain_pg_embedding')
count = cur.fetchone()[0]
conn.close()
print(f'Embedding count: {count}')
exit(0 if count > 0 else 1)
" 2>/dev/null && echo "Data already ingested — skipping" || (echo "DB empty — running ingest..." && python -m ip_agent.ingest)

uvicorn ip_agent.api:app --host 0.0.0.0 --port 8001 &
streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true &
wait -n
exit $?
