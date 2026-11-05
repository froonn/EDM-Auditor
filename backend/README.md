# EDM-Auditor backend

A REST API that audits electronic documents against legal acts. It extracts checkable rules from a
legal act with a language model, selects the rules that apply to a document, checks the document
with code, and asks the model to confirm and explain the results.

Audit output is a technical automated check. It does not replace review by a qualified legal
professional.

## How it works

1. **Legal act upload.** A TXT act is split into chunks. The model returns rules for each chunk with
   an exact quote of the norm, a check type, a severity and the document types the rule applies to.
   The rules are validated and published together: a failed chunk publishes nothing.
2. **Document upload.** The parser extracts the text of a TXT, DOCX or text-layer PDF file. The model
   chooses the document type from the catalog. A choice below the confidence threshold needs a
   person's confirmation.
3. **Rule selection.** The resolver selects the rules for the document. Preview the result with
   `POST /api/documents/{id}/audit/preview`. Each report stores the selection it used.
4. **Audit.** Code checks the keyword, regex, numeric, date and duration rules. The model extracts
   entities and explains every finding. It also confirms or rejects each duration and numeric
   finding from the norm and the surrounding text.

No substitute exists for the models. If a required model call fails, the audit stops, no report is
saved and the document status becomes `error`. The model cannot change the severity or the source
range of a finding, and the server builds the legal references from the rule itself.

## Setup

Python 3.11 or newer is required. Run all commands from `backend/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
cp .env.example .env    # then set EDM_MODEL_PRESET and the API key
alembic upgrade head
uvicorn edm_auditor.api.app:create_app --factory --reload
```

OpenAPI documentation is available at <http://127.0.0.1:8000/docs>. The API has no authentication
and must stay in a trusted development environment.

To try the whole flow, follow [`examples/README.md`](examples/README.md). For debugging and
`curl` requests, see [`docs/DEBUG.md`](../docs/DEBUG.md).

## Configuration

The API loads `.env` automatically. Variables already set in the shell take precedence, so a different
`GEMINI_API_KEY` in your shell profile hides the one in `.env`. In that case run
`set -a; source .env; set +a` before starting the server. Never commit `.env` or real API keys.

| Variable               | Default                              | Purpose                                         |
|------------------------|--------------------------------------|-------------------------------------------------|
| `EDM_MODEL_PRESET`     | none, required                       | Model preset from `config/models.toml`          |
| `GEMINI_API_KEY`       | none                                 | Key for the `google-ai-studio` preset           |
| `OPENROUTER_API_KEY`   | none                                 | Key for the `openrouter` preset                 |
| `EDM_MODEL_CONFIG`     | `config/models.toml`                 | Path to the model configuration                 |
| `EDM_DATABASE_URL`     | `sqlite:///data/edm_auditor.sqlite3` | Database used by the API                        |
| `EDM_UPLOAD_DIR`       | `data/uploads`                       | Directory for uploaded documents                |
| `EDM_MAX_UPLOAD_BYTES` | `20971520`                           | Upload size limit                               |
| `EDM_SOURCE_LANGUAGE`  | `auto`                               | Legal act language: `auto`, `ru` or `en`        |
| `RAG_INDEX_PATH`       | `data/rag-index.sqlite3`             | RAG index file                                  |
| `EDM_DATABASE_PATH`    | `data/edm_auditor.sqlite3`           | Database file used by the RAG command line tool |
| `EDM_LOG_FILE`         | `data/debug.log`                     | Detailed request log                            |

Models, limits and presets are described in
[`docs/model-configuration.md`](../docs/model-configuration.md).

## Database

The API uses SQLite through SQLAlchemy 2 and Alembic. The database and uploaded files are not stored
in Git. The server refuses to start on an outdated schema and names the command to run.

```bash
cp data/edm_auditor.sqlite3 data/edm_auditor.backup.sqlite3
alembic upgrade head
```

`alembic.ini` sets the database path directly and ignores `EDM_DATABASE_URL`: the commands above always
change `data/edm_auditor.sqlite3`. To migrate another file, create an `alembic.config.Config` and set
`sqlalchemy.url` on it, as `tests/database/test_migrations.py` does.

## API

Paginated lists accept `limit` (up to 100) and `offset`, and return the total in the `X-Total-Count`
header.

### Documents and audit

| Method and path                            | Purpose                                        |
|--------------------------------------------|------------------------------------------------|
| `GET /health`                              | Service check                                  |
| `POST /api/documents/upload`               | Upload a file (`file`, optional `title`)       |
| `GET /api/documents`                       | List documents with `latest_report`, paginated |
| `GET /api/documents/{id}`                  | Document with its `text`                       |
| `DELETE /api/documents/{id}`               | Delete a document, its reports and its file    |
| `POST /api/documents/{id}/classify`        | Determine the document type again              |
| `PATCH /api/documents/{id}/classification` | Confirm the document types manually            |
| `POST /api/documents/{id}/audit/preview`   | Show the rules an audit would use              |
| `POST /api/documents/{id}/audit`           | Run an audit                                   |
| `GET /api/documents/{id}/report`           | Latest report, or the one set by `report_id`   |
| `GET /api/reports`                         | List reports, paginated. Filter: `document_id` |
| `GET /api/reports/{id}`                    | One report                                     |
| `GET /api/reports/{id}/export`             | Download the report as a file, see below       |

### Rules

| Method and path                       | Purpose                                                                                           |
|---------------------------------------|---------------------------------------------------------------------------------------------------|
| `GET /api/rules`                      | List rules, paginated. Filters: `is_active`, `document_type`, `check_type`, `applicability_scope` |
| `POST /api/rules`                     | Create a rule                                                                                     |
| `PATCH /api/rules/{id}`               | Change `name`, `description`, `severity`, `check_type`, `parameters` or `is_active`               |
| `PATCH /api/rules/{id}/applicability` | Set the scope and document types manually                                                         |
| `DELETE /api/rules/{id}`              | Delete a rule; its findings stay in reports                                                       |

Check types and their parameters:

| `check_type` | `parameters`                                                                                |
|--------------|---------------------------------------------------------------------------------------------|
| `keyword`    | `keywords`, optional `mode` (`forbidden`, `required`), `match` (`literal`, `stem`, `regex`) |
| `regex`      | `pattern`                                                                                   |
| `numeric`    | `entity` (`number`, `duration`, `money`, `percent`) with `min` and/or `max`                 |
| `date`       | `before` and/or `after` as ISO dates                                                        |
| `duration`   | `min_days` and/or `max_days`                                                                |

A rule whose document types are all deactivated cannot be enabled: change its applicability or reactivate a
type first. A manually created rule may also have a `recommendation` parameter. Semantic rules are not executed
in this version, so the model cannot create them and the API refuses them.

### Legal acts

| Method and path                        | Purpose                                                   |
|----------------------------------------|-----------------------------------------------------------|
| `GET /api/legal-acts`                  | List acts without their text, paginated. Filter: `search` |
| `POST /api/legal-acts`                 | Create an act from JSON; rules are not extracted          |
| `POST /api/legal-acts/upload`          | Upload a TXT act and extract its rules                    |
| `GET /api/legal-acts/{id}`             | Act with its text                                         |
| `GET /api/legal-acts/{id}/diagnostics` | Extraction result of each chunk                           |
| `POST /api/legal-acts/{id}/reprocess`  | Extract the rules again                                   |
| `PATCH /api/legal-acts/{id}`           | Change an act                                             |
| `DELETE /api/legal-acts/{id}`          | Delete an act with its rules; findings stay in reports    |

Changing the text of a processed act sets its status to `needs_reprocessing`. The act keeps its rules
until `reprocess` replaces them. `reprocess` loses manual changes to the generated rules of the act,
including `is_active` and applicability. Findings in earlier reports keep their stored rule details.

Changes to acts and to fields used for search rebuild the RAG index, which calls the embedding model.

### Document types

| Method and path                                    | Purpose                                           |
|----------------------------------------------------|---------------------------------------------------|
| `GET /api/document-types`                          | List the catalog (`include_inactive` is optional) |
| `POST /api/document-types`                         | Add a type                                        |
| `PATCH /api/document-types/{code}`                 | Change the name or description                    |
| `DELETE /api/document-types/{code}`                | Deactivate a type that is not in use              |
| `GET /api/document-type-suggestions`               | List new types suggested by the model             |
| `POST /api/document-type-suggestions/{id}/accept`  | Add a suggested type to the catalog               |
| `POST /api/document-type-suggestions/{id}/dismiss` | Dismiss a suggestion                              |

The model only suggests new types. A person decides whether to add them.

### Rule selection

The body of an audit or a preview request is optional. Without one, the `automatic` mode is used.

| `selection_mode` | Rules used                                                                        |
|------------------|-----------------------------------------------------------------------------------|
| `automatic`      | Universal rules and rules of the confirmed types; `legal_act_ids` narrows them    |
| `manual`         | Only `included_rule_ids` and the rules of `legal_act_ids`                         |
| `combined`       | The automatic set plus the manual choice                                          |
| `all`            | All active rules; requires `"confirm_all": true`, and false findings are possible |

`excluded_rule_ids` always wins, and inactive rules never run. Rules with the `manual_only` scope run
only through `included_rule_ids`. Without a confirmed type, the `automatic` mode responds with `409`
`audit_configuration_required`: confirm a type or choose the rules manually. RAG results are only shown
as recommendations and never select a rule.

### Report

Each item of `findings` contains:

- `start_char`, `end_char` and `quote`: the position in the `text` of the document;
- `finding_key`: the key of the matching item in `neural_analyses`, which holds the explanation,
  recommendation and legal basis;
- `rule_code`, `rule_name`, `legal_act_code`, `legal_act_title` and `norm_quote`: copies stored in the
  report, available after the rule or act is deleted. They can be empty in reports created before
  these fields existed, if the rule or act had already been deleted.

`summary.rejected_candidates` lists the findings the model rejected, with its reason.
`summary.diagnostics` lists rules that could not be evaluated. `selection` stores the rule selection.

### Report export

`GET /api/reports/{id}/export?format=html&timezone=Europe/Minsk` returns the report as one HTML file
with its styles: the document text with numbered highlights, the findings with norms and
recommendations, and the applied rules without findings. It opens offline and can be printed or saved
as PDF from the browser. `timezone` is an IANA zone for the dates, `UTC` by default; the interface sends
the zone of the browser. The file name comes in `Content-Disposition` (`filename*` in UTF-8).

Only `html` is supported now. PDF and an annotated DOCX are planned for the diploma project and are
added as renderers in `src/edm_auditor/report_export/`. The texts of the file are in
`report_export/labels.py`.

### Errors

Every error has the same form: `{"error": {"code": "...", "message": "..."}}`.

| Status | Codes                                                                                                                                                                                                                                                                                                                                            |
|--------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 400    | `empty_document`, `invalid_document`, `document_access_error`, `document_parse_error`                                                                                                                                                                                                                                                            |
| 404    | `document_not_found`, `report_not_found`, `rule_not_found`, `legal_act_not_found`, `document_type_not_found`, `document_type_suggestion_not_found`, `not_found`                                                                                                                                                                                  |
| 409    | `audit_configuration_required`, `no_applicable_rules`, `rule_conflict`, `rule_document_types_inactive`, `legal_act_conflict`, `document_type_conflict`, `document_type_in_use`, `document_type_suggestion_closed`                                                                                                                                |
| 413    | `document_too_large`, `document_too_large_for_audit`                                                                                                                                                                                                                                                                                             |
| 415    | `unsupported_document_format`, `unsupported_legal_act_format`                                                                                                                                                                                                                                                                                    |
| 422    | `validation_error`, `invalid_severity`, `invalid_check_type`, `unsupported_check_type`, `invalid_rule_parameters`, `invalid_applicability_scope`, `unknown_document_type`, `reserved_document_type`, `unknown_rule`, `unknown_legal_act`, `all_mode_not_confirmed`, `audit_configuration_error`, `unsupported_export_format`, `invalid_timezone` |
| 429    | `model_rate_limited`: repeat the request in a minute                                                                                                                                                                                                                                                                                             |
| 503    | `model_provider_error`, `classification_model_error`, `rule_extraction_error`, `rag_index_error`                                                                                                                                                                                                                                                 |
| 504    | `model_timeout`: repeat the request                                                                                                                                                                                                                                                                                                              |
| 500    | `internal_error`, `rule_persistence_error`, `invalid_report_summary`, `invalid_rule_parameters` for damaged stored data                                                                                                                                                                                                                          |

`rag_index_error` means the change was saved, but the search index was not rebuilt.

## Tests

```bash
pytest -q
```

The suite needs no network, credentials or real legal documents. Test doubles for the models are in
`tests/fakes.py`, and `tests/fixtures/recorded_gemini_audit.json` holds recorded Gemini responses for
the regression test.

## Source layout

| Path                                 | Contents                                                 |
|--------------------------------------|----------------------------------------------------------|
| `src/edm_auditor/api/`               | FastAPI application, schemas, errors, upload storage     |
| `src/edm_auditor/document_parser/`   | Text extraction from TXT, DOCX and PDF                   |
| `src/edm_auditor/classification/`    | Document type catalog and classification                 |
| `src/edm_auditor/applicability/`     | Rule scope and rule selection                            |
| `src/edm_auditor/audit_engine/`      | Rule checks, model interpretation, report storage        |
| `src/edm_auditor/rag/`               | Chunking, vector index, search and its command line tool |
| `src/edm_auditor/report_export/`     | Report export to a file (HTML)                           |
| `src/edm_auditor/database/`          | SQLAlchemy models and the document repository            |
| `src/edm_auditor/model_providers.py` | Model clients, prompts and response schemas              |
| `src/edm_auditor/rule_validation.py` | Validation of generated and manual rules                 |
| `migrations/`                        | Alembic migrations                                       |
| `config/models.toml`                 | Model profiles, presets and limits                       |
| `examples/`                          | Synthetic legal acts and documents                       |

## Document parser

The parser supports UTF-8 `.txt`, `.docx` and text-layer `.pdf` files. Scanned PDFs need OCR, which is
not implemented. It can be used without the API:

```python
from edm_auditor.document_parser import parse_document

document = parse_document("contract.pdf")
print(document.text)
for paragraph in document.paragraphs:
    print(paragraph.index, paragraph.start_char, paragraph.end_char, paragraph.page_number)
```

Parser exceptions are `UnsupportedDocumentFormat`, `DocumentNotFound`, `InvalidDocument`,
`TextLayerRequired` and `DocumentTooLarge`. The API turns them into the `400`, `413` and `415` errors
above. Legal acts must be TXT files.

## RAG index

The API rebuilds the index after changes to legal acts and rules. If the embedding model fails, the
rebuild fails and the previous index stays active. The index can also be used directly with the
embedding model of the selected preset:

```bash
python -m edm_auditor.rag build
python -m edm_auditor.rag count
python -m edm_auditor.rag search "annual leave" -k 5 --threshold 0.1
```

After changing the embedding model or its dimension, rebuild the index: an incompatible index is
rejected.

## Limitations

- Only small legal acts work reliably. One failed chunk stops the publication of the whole act, and a
  large act quickly exceeds the request limit of a free model plan.
- Requirements without a comparable value are not checked: "once a month" is not detected against a
  norm of "at least twice a month". This needs the semantic audit planned for the diploma project.
- The model's verdicts and severity stability were checked only on the examples in `examples/`.
- Legal act codes are unique only at the API level, with no database constraint.
- Report export is not implemented yet.

See [`docs/TODO.md`](../docs/TODO.md) for the plan and [`docs/DEVLOG.md`](../docs/DEVLOG.md) for the
current state.

The examples are synthetic and are not legal advice. Check the source, version and jurisdiction of
real legal acts before loading them.
