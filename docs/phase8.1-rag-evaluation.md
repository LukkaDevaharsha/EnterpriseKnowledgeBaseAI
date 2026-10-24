# Phase 8.1: RAG evaluation baseline

The first versioned benchmark is `backend/evaluation/rag_cases.json`. It
contains answerable leave-policy questions, unanswerable questions, expected
answer facts, and stable supporting-chunk locators. A locator uses the
document's exact `original_filename` metadata and a required content substring
rather than database-generated numeric IDs. This lets the benchmark filename
`leave_policy.txt` match the stored display title `Leave policy` only when the
retrieved document's original filename metadata confirms the relationship. The
dataset can be reused after test database IDs change. The included leave source
is:

> Employees may take annual leave and sick leave under the company leave policy.

## Retrieval metrics

The evaluator runs the existing authenticated-user-scoped `search_chunks`
service. It reports, at the requested top-k:

- **Recall@k:** expected supporting chunk locators found divided by expected
  locators, micro-aggregated over answerable cases.
- **Mean precision@k:** retrieved expected supporting locators divided by k,
  averaged over answerable cases.
- **Mean precision@returned:** unique expected supporting chunks divided by
  the number of chunks actually returned, averaged over answerable cases that
  returned at least one chunk. This supplemental measure does not replace or
  alter the fixed-denominator precision@k metric.
- Per-case support matches, retrieved chunk IDs, scores, and the number of
  returned chunks above the existing `RAG_MIN_SIMILARITY` threshold.

Unanswerable cases have no expected supporting locators, so they are reported
separately and excluded from precision and recall. Their retrieved-above-
threshold count is diagnostic; retrieval similarity alone does not determine
whether a question is answerable. The current threshold is reported as-is and
is not changed by this baseline.

## Answer and citation checks

With `--evaluate-answers`, the script sends questions to the configured local
Ollama model and evaluates raw model text alongside the API's returned
citations. Fallback citations returned by the API do not count as citations in
the raw answer. Checks distinguish missing citations, invalid source IDs,
invalid citation records whose chunk/document metadata does not match the
retrieved source, expected facts absent from the answer, facts unsupported by
retrieved evidence, facts whose same-sentence citations do not support them, and
failure to abstain on unanswerable questions. The checks use normalized phrase matching;
they are deterministic and inexpensive, but are not a semantic entailment
judge. In particular, they cannot reliably detect an extra hallucinated claim
when the same answer also contains a supported expected fact. The results are
a baseline for expanding the benchmark, not a model quality certification.

Automated tests use synthetic ranked results and mocked Ollama calls; they do
not require network access, a live model, or a database corpus beyond the
project's existing test setup.

## Run the evaluation

From the backend directory, first ensure the target user's corpus contains the
benchmark's supporting document (`leave_policy.txt`, with the expected text)
and that its chunks have embeddings for the configured model. Use that user's
numeric database ID:

```cmd
cd /d D:\MY_PROJECTS\EnterpriseKnowledgeBaseAI\backend
..\.venv\Scripts\python.exe evaluate_rag.py --user-id 1 --top-k 5
```

The command prints JSON retrieval metrics. `--top-k` accepts 1 through the
configured `RAG_MAX_TOP_K` (maximum 20). To additionally evaluate live local
Ollama answers and citations, use:

```cmd
..\.venv\Scripts\python.exe evaluate_rag.py --user-id 1 --top-k 5 --evaluate-answers
```

The answer option requires the configured Ollama service/model; the retrieval
baseline does not. Both modes require the configured database and locally
available embedding model. Neither command changes database contents or tunes
configuration.

Run the offline automated suite from the backend directory:

```cmd
..\.venv\Scripts\python.exe -m pytest tests -q
```
