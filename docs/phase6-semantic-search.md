# Phase 6: Semantic search

`POST /api/search` accepts `{ "query": "...", "limit": 5 }` and requires a
valid JWT for an active user. The query uses the configured 384-dimensional
`EMBEDDING_MODEL_NAME` through the existing cached `generate_embeddings` service.
Search only considers chunks whose status is `PROCESSED`, model identifier
matches the configured model, embedding exists, and content hash still matches
the saved chunk. The SQL query filters by `documents.uploaded_by` before fetching
any content, so results are limited to the caller's documents.

The current schema stores vectors as PostgreSQL `double precision[]`; it does
not use pgvector operators. The service validates finite vector values and
dimensions, then ranks using **cosine similarity** in the range [-1, 1]. Scores
are geometric similarity measures, not probabilities. Ties use document ID,
chunk index, and chunk ID for stable ordering. At most 20 results are returned,
with a default of 5. Query text is limited to 2,000 characters and returned
content is capped at 1,200 characters.

PostgreSQL applies ownership, model, status, and non-null vector filters before
rows are streamed into the application. Because the current array type has no
cosine-distance operator or useful vector index, Python computes similarity for
each eligible chunk owned by that user. Memory use is bounded to the requested
top results plus a streamed DB batch, but CPU work remains O(number of that
user's eligible chunks). For larger corpora, migrate vectors to pgvector, enable
its extension consistently in development and test databases, add an HNSW or
IVFFlat cosine index, and run ranking in SQL. This phase does not add that schema
change or index.

## CMD verification

No migration is required for Phase 6. From the repository root:

```cmd
cd /d D:\MY_PROJECTS\EnterpriseKnowledgeBaseAI
..\.venv\Scripts\python.exe -m pytest backend\tests -q
```

For an API request, first obtain an access token using the existing login API:

```cmd
curl -X POST http://127.0.0.1:5000/api/search -H "Authorization: Bearer YOUR_ACCESS_TOKEN" -H "Content-Type: application/json" -d "{\"query\":\"What is the leave policy?\",\"limit\":5}"
```

Do not place real tokens in source files or logs.
