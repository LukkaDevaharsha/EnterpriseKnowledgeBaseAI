# Phase 7: Grounded question answering with Ollama

`POST /api/ask` retrieves the authenticated user's own chunks through the
existing semantic-search service, then asks a locally running Ollama model to
answer from that evidence. There is no hosted LLM key and no model is downloaded
when Flask starts. Each answer citation is assembled from a retrieved database
record; the API accepts only source IDs included in the supplied context and
removes model references to unknown IDs.

Retrieval uses the existing cosine-similarity score (higher is closer, range
[-1, 1]). The default minimum is `0.25`; this is a configurable relevance
cutoff, not a confidence probability. If there are no results above the cutoff,
Ollama is not called and the API responds that the available documents do not
contain enough information. Retrieved excerpts are isolated as JSON data and
the system message says to ignore instructions inside them. This is defense in
depth and cannot guarantee that prompt injection is eliminated.

The application limits questions to 2,000 characters, defaults to 5 chunks,
allows at most 10, and caps retrieved context at 12,000 characters. The model
output is limited by Ollama generation settings and capped before returning.

## Install Ollama on Windows

Install using the official [Ollama for Windows download](https://ollama.com/download/windows)
or, from PowerShell, the official installer command:

```powershell
irm https://ollama.com/install.ps1 | iex
```

Open a new CMD window and check the CLI and locally available models:

```cmd
ollama --version
ollama list
```

Choose a model appropriate for available memory and speed. The default here is
`llama3.2:3b`; the Ollama library currently lists it at about 2.0 GB. Smaller
models can be configured for more limited hardware. The default is not assumed
to be installed automatically. Pull and start the configured model:

```cmd
ollama pull llama3.2:3b
ollama run llama3.2:3b
```

Ollama's Windows app normally serves its local API at `http://localhost:11434`.
If it is not running, start the Ollama application or run `ollama serve` in a
separate terminal. Verify the local service and model list:

```cmd
curl.exe http://localhost:11434/api/tags
```

See the [official Windows install page](https://ollama.com/download/windows)
and [Ollama model library](https://ollama.com/library/llama3.2) for current
installation and model options.

## Configuration and start-up

Copy these example values into the local `backend\.env` (do not commit secrets
or replace existing database/JWT settings). `backend\.env.example` lists the
Phase 7 names and defaults:

```text
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
OLLAMA_TIMEOUT_SECONDS=60
GENERAL_AI_MODEL=llama3.2:3b
COMPANY_KNOWLEDGE_MODEL=llama3.2:3b
STUDY_PDF_MODEL=llama3.2:3b
RAG_DEFAULT_TOP_K=5
RAG_MAX_TOP_K=10
RAG_MAX_CONTEXT_CHARS=12000
RAG_MIN_SIMILARITY=0.25
```

The three mode-specific model settings are optional. Each blank or unset value
uses `OLLAMA_MODEL`, which remains the default for existing deployments.

No Python package was added for HTTP requests: the Ollama client uses Python's
standard-library `urllib`. Start the Flask backend from CMD:

```cmd
cd /d D:\MY_PROJECTS\EnterpriseKnowledgeBaseAI\backend
..\.venv\Scripts\python.exe run.py
```

## Request and responses

Get a JWT from the existing login endpoint, then call `/api/ask`:

```cmd
curl.exe -X POST http://127.0.0.1:5000/api/ask -H "Authorization: Bearer YOUR_ACCESS_TOKEN" -H "Content-Type: application/json" --data-raw "{\"question\":\"What is the leave policy?\",\"top_k\":5}"
```

Example successful response:

```json
{
  "status": "success",
  "question": "What is the leave policy?",
  "answer": "The handbook describes annual leave for employees. [S1]",
  "insufficient_evidence": false,
  "citations": [
    {
      "source_id": "S1",
      "document_id": 12,
      "document_title": "Employee Handbook",
      "chunk_id": 45,
      "chunk_index": 2,
      "excerpt": "Employees are eligible for annual leave..."
    }
  ]
}
```

When evidence is absent or below threshold, the endpoint returns HTTP 200 with
an explicit insufficient-evidence answer and no citations:

```json
{
  "status": "success",
  "question": "What is the lunar mining policy?",
  "answer": "The available documents do not contain enough relevant information to answer this question.",
  "insufficient_evidence": true,
  "citations": []
}
```

## Troubleshooting

- **Connection refused / unavailable:** confirm the Ollama app or `ollama serve`
  is running and `OLLAMA_BASE_URL` is reachable from the Flask process.
- **Model unavailable (HTTP 404):** run `ollama list`, then `ollama pull` using
  the exact `OLLAMA_MODEL` value.
- **Timeout:** increase `OLLAMA_TIMEOUT_SECONDS`, reduce `RAG_MAX_TOP_K` or
  `RAG_MAX_CONTEXT_CHARS`, or choose a smaller model for the available hardware.
- **Insufficient evidence:** upload and process documents for the signed-in user;
  confirm their chunks have embeddings for the configured embedding model. If
  needed, adjust `RAG_MIN_SIMILARITY` carefully; scores are cosine similarities.
- **Invalid configuration:** top-k must satisfy `1 <= RAG_DEFAULT_TOP_K <=
  RAG_MAX_TOP_K <= 20`; the similarity threshold must be between -1 and 1.

Run tests from the backend directory with `..\.venv\Scripts\python.exe -m pytest tests -q`.
Tests mock retrieval and Ollama HTTP; they do not require Ollama or a chat model.
