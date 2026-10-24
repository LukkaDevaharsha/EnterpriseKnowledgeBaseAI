import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

import psycopg

base_db_name = os.getenv("DB_NAME", "enterprise_knowledge_base")
test_db_name = base_db_name + "_test"

user = os.getenv("DB_USER", "postgres")
password = os.getenv("DB_PASSWORD", "")
host = os.getenv("DB_HOST", "localhost")
port = os.getenv("DB_PORT", "5432")

with psycopg.connect(
    user=user,
    password=password,
    host=host,
    port=port,
    dbname="postgres",
    autocommit=True,
) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_db_name,))
        exists = cur.fetchone() is not None
        if not exists:
            cur.execute(f'CREATE DATABASE "{test_db_name}"')
            print(f"Created test database: {test_db_name}")
        else:
            print(f"Test database already exists: {test_db_name}")
