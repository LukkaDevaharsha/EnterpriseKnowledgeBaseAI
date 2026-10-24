# Phase 5: Chunk embeddings

## Selected model and storage

The default local model is `sentence-transformers/all-MiniLM-L6-v2`. It returns
384-dimensional vectors, has about 22.7 million parameters, and its published
weights are about 90.9 MB. It is a CPU-capable model; first inference is slower
while PyTorch initializes, and RAM use includes PyTorch plus model/runtime
buffers. Sentence Transformers documents Python 3.10+ and has Python 3.13
package classifiers. See the [model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2),
[Sentence Transformers usage](https://www.sbert.net/docs/sentence_transformer/usage/usage.html),
and [installation requirements](https://sbert.net/docs/installation.html).

The configured production PostgreSQL database has pgvector 0.8.6 enabled, but
the Python pgvector adapter is not installed and the separate test database does
not have the extension enabled. This phase therefore stores vectors as native
PostgreSQL `double precision[]`, not as serialized strings. A check constraint
requires exactly 384 elements; the embedding service validates finite numeric
values and unit-normalizes every vector before persistence. The typed-array
column is portable across the project's test database setup and can be migrated
to pgvector when its Python adapter and extension are deployed consistently.
No vector index is added in this phase; indexing is relevant when Phase 6 adds
similarity queries.

`document_chunks.embedding_status` tracks `PENDING`, `PROCESSING`, `PROCESSED`,
and `FAILED`. The content SHA-256 and model identifier identify stale embeddings.
Inference occurs after document text/chunks are committed, in a separate
document-sized transaction. An inference or vector-persistence failure keeps
the document and chunks, marks affected chunks `FAILED`, and does not produce
an embedding success state. Valid embeddings are not regenerated on ordinary
retries. A configured model change is blocked if vectors from another model
exist. After deliberately changing `EMBEDDING_MODEL_NAME`, run the explicit
maintenance command to re-embed all chunks; failed batches retain their old
vectors and can be retried by running the command again.

## Install and configure (Windows CMD)

From the repository root, install the backend requirements into the existing
virtual environment. This includes the Sentence Transformers runtime (PyTorch
and Transformers dependencies); no pgvector Python dependency is needed for the
array storage strategy.

```cmd
cd /d D:\MY_PROJECTS\EnterpriseKnowledgeBaseAI
..\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
set HF_HOME=D:\MY_PROJECTS\EnterpriseKnowledgeBaseAI\model-cache
set EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
set EMBEDDING_DIMENSION=384
..\.venv\Scripts\python.exe -c "from sentence_transformers import SentenceTransformer; model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); print(model.get_embedding_dimension())"
```

The final command downloads model files once to the Hugging Face cache (under
`HF_HOME` for that CMD session), then confirms the expected dimension. Keep
network access available for the initial model download. Subsequent service
requests reuse a process-local model instance and the local cache. Do not change
the model identifier for an existing corpus without running the re-embedding
command.

Optional `.env` values (use placeholders in tracked examples; keep real settings
local):

```text
EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DIMENSION=384
```

## Migration and verification

The existing chunk migration remains intact. The new revision is
`d5b2c4e819a7`, adding nullable vector data and retry metadata to existing chunk
rows. Existing rows start as `PENDING`.

```cmd
cd /d D:\MY_PROJECTS\EnterpriseKnowledgeBaseAI\backend
type migrations\versions\d5b2c4e819a7_add_chunk_embeddings.py
..\.venv\Scripts\python.exe -m flask --app run db heads
..\.venv\Scripts\python.exe -m flask --app run db upgrade
..\.venv\Scripts\python.exe -m flask --app run reembed-chunks
..\.venv\Scripts\python.exe -m pytest tests -q
```

`reembed-chunks` is safe to rerun: chunks with a successful matching model and
content hash are skipped; pending, failed, stale, and different-model embeddings
are regenerated. It explicitly allows switching the stored dataset to the
currently configured model. Run `db upgrade` against the intended database only;
the pytest fixtures use the separate `<DB_NAME>_test` database.
