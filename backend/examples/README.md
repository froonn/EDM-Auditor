# Audit examples

These UTF-8 text files are synthetic examples for local testing. Upload each
legal-act file first, let the configured neural extractor create rules, then
upload the matching audit documents.

| Legal act                     | Violating document          | Compliant document                    |
|-------------------------------|-----------------------------|---------------------------------------|
| `legal_act_remote_work.txt`   | `remote_work_agreement.txt` | `compliant_remote_work_agreement.txt` |
| `legal_act_payments.txt`      | `payroll_order.txt`         | `compliant_payroll_order.txt`         |
| `legal_act_business_trip.txt` | `business_trip_order.txt`   | `compliant_business_trip_order.txt`   |

The examples cover duration, numeric percentages and amounts, dates, and
required keywords. Because rule extraction is performed by the configured
neural model, inspect `GET /api/rules` after each legal-act upload before
running an audit. The generated rule parameters must match the validator
contracts documented in the rule-extraction prompt.

For example, with the server running from `backend/`:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/legal-acts/upload \
  -F code=ACT-REMOTE \
  -F title='Remote work requirements' \
  -F file=@examples/legal_act_remote_work.txt

curl -sS http://127.0.0.1:8000/api/rules | python -m json.tool

curl -sS -X POST http://127.0.0.1:8000/api/documents/upload \
  -F file=@examples/remote_work_agreement.txt
```

Then run the audit using the returned document ID:

```bash
curl -sS -X POST \
  http://127.0.0.1:8000/api/documents/<DOCUMENT_ID>/audit | python -m json.tool
```
