# Phase 4: Text chunking and database integration

PDF and UTF-8 TXT uploads are extracted by `app.services.document_processor`.
`app.services.text_chunker.split_text` creates ordered chunks of at most 1,000
characters with a 150-character target overlap. It prefers whitespace boundaries
when that keeps the chunk reasonably full. Empty input returns no chunks.

`start_char` and `end_char` are zero-based, half-open offsets into the extracted
text saved in `documents.extracted_text`: `content` is exactly
`extracted_text[start_char:end_char]`. The chunker removes surrounding whitespace
from chunk content and advances the offsets to match; it does not normalize or
rewrite characters in the source text.

The upload stores the original file and document row, extracts the text, and
inserts all chunks in the same database transaction as the extracted text and
`PROCESSED` status. A document is marked `PROCESSING_FAILED` when extraction
returns no readable text or chunking yields no usable content. Database errors
roll back the row and chunks and remove the just-uploaded file. Document deletion
removes chunks through the foreign-key cascade, with explicit ORM cleanup as well.

## Migration workflow (Windows CMD)

Run these commands from the repository root. The migration for this phase is
`backend\migrations\versions\c41a9e72b6d3_create_document_chunks_table.py`,
following `04acbd515d78`. The command below documents how to generate a migration
when starting from the pre-Phase-4 model state; it must not be rerun now, because
the migration is already present and would create an unnecessary second revision.

```cmd
cd /d D:\MY_PROJECTS\EnterpriseKnowledgeBaseAI
cd backend
..\.venv\Scripts\python.exe -m flask --app run db migrate -m "create document chunks"
type migrations\versions\c41a9e72b6d3_create_document_chunks_table.py
..\.venv\Scripts\python.exe -m flask --app run db upgrade
```

Inspect the generated revision before applying it and confirm the `document_chunks`
table has the cascading FK, unique `(document_id, chunk_index)` constraint,
nonnegative index/start checks, valid end offset check, and document index.
The checked-in revision has those definitions. To verify the schema, use psql
against the database configured for the backend (it prompts for the password):

```cmd
psql -h localhost -p 5432 -U postgres -d enterprise_knowledge_base -c "SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name = 'document_chunks' ORDER BY ordinal_position;"
psql -h localhost -p 5432 -U postgres -d enterprise_knowledge_base -c "SELECT conname, contype, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'document_chunks'::regclass ORDER BY conname;"
psql -h localhost -p 5432 -U postgres -d enterprise_knowledge_base -c "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'document_chunks' ORDER BY indexname;"
```

Adjust the database name or user in those commands if the backend configuration
uses different values. Never point test verification at the development database;
the pytest suite uses the separate `<DB_NAME>_test` database.

## Tests

From the repository root:

```cmd
..\.venv\Scripts\python.exe -m pytest backend\tests -q
```
