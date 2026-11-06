# Audit examples

These UTF-8 text files are synthetic examples for local testing. They are not legal advice.

| Legal act                     | Violating document          | Compliant document                    |
|-------------------------------|-----------------------------|---------------------------------------|
| `legal_act_remote_work.txt`   | `remote_work_agreement.txt` | `compliant_remote_work_agreement.txt` |
| `legal_act_payments.txt`      | `payroll_order.txt`         | `compliant_payroll_order.txt`         |
| `legal_act_business_trip.txt` | `business_trip_order.txt`   | `compliant_business_trip_order.txt`   |

The examples cover durations, percentages, amounts, dates and required keywords.

The model creates the rules, so inspect `GET /api/rules` after each legal act upload. For each rule,
it also chooses the document types the rule applies to; you can replace that choice with
`-F document_types=...` at upload or with `PATCH /api/rules/{id}/applicability`. A document is
audited only by universal rules and the rules of its own type. Without a confirmed type, the audit
asks for configuration.

Each upload and audit calls the model. On a free plan, leave a pause between requests so that you do
not exceed the request limit.

In the interface, upload a legal act on the "НПА" page, check its rules, then upload a document on the
"Документы" page and run the audit. The same steps with `curl`, with the server running from `backend/`:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/legal-acts/upload \
  -F code=ACT-REMOTE \
  -F title='Положение о дистанционной работе' \
  -F file=@examples/legal_act_remote_work.txt | python -m json.tool --no-ensure-ascii

curl -sS http://127.0.0.1:8000/api/rules | python -m json.tool --no-ensure-ascii

curl -sS -X POST http://127.0.0.1:8000/api/documents/upload \
  -F file=@examples/remote_work_agreement.txt | python -m json.tool --no-ensure-ascii
```

Then run the audit with the returned document ID and read the report:

```bash
curl -sS -X POST \
  http://127.0.0.1:8000/api/documents/<DOCUMENT_ID>/audit | python -m json.tool --no-ensure-ascii

curl -sS http://127.0.0.1:8000/api/documents/<DOCUMENT_ID>/report | python -m json.tool --no-ensure-ascii
```

`remote_work_agreement.txt` should give findings, and `compliant_remote_work_agreement.txt` should
give none. `payroll_order.txt` also breaks two requirements the audit cannot detect yet: the payment
frequency and the final payment by the 5th. See the limitations in [`../README.md`](../README.md).
