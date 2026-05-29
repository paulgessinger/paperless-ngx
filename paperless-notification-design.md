# Paperless-ngx Notification Design Notes

## Context

Investigating how to build per-user push notifications on top of paperless-ngx using
the built-in webhook workflow action and a user-hosted local relay.

---

## Reducing JSON Payload (`?fields=`)

The document list API already supports field filtering via `?fields=id,title,created`
(and any other `DocumentSerializer` field). Introduced in **v2.8.0** (PR #6439, April 2024).

Also available:
- `?truncate_content=true` — truncates `content` to 550 chars
- `?id__in=1,2,3` — filter by specific IDs (combinable with `?fields=`)

```
GET /api/documents/?id__in=42&fields=id,title,correspondent,tags,created
```

---

## Webhook Workflow Action

Configured in the UI/API under **Workflows → Actions → Webhook**
(`WorkflowActionWebhook`, `src/documents/models.py:1230`).

### Configuration fields

| Field | Description |
|---|---|
| `url` | HTTP/HTTPS only. **No SSRF/private-IP filtering** — `http://relay.lan:9000/` works. |
| `use_params` | Toggle between key-value `params` dict and freeform `body` string |
| `as_json` | JSON (`true`) vs form-encoding (`false`) |
| `headers` | Static key-value dict — supports `Authorization`, shared secrets, etc. Headers are **not** placeholder-templated. |
| `include_document` | Attaches original file as multipart `file` field — leave `false` for a relay |

Execution: **async Celery task**, POST via httpx, 3 retries w/ exponential backoff.
Does not block document ingestion (unlike the post-consume script).

### Trigger types

| Type | Notes |
|---|---|
| `CONSUMPTION` (1) | Before OCR/parsing — limited metadata available |
| `DOCUMENT_ADDED` (2) | After saved to DB ✅ recommended |
| `DOCUMENT_UPDATED` (3) | On any update |
| `SCHEDULED` (4) | Time-based |

Use **Document Added** — full metadata and placeholders available, fires once per ingest.

### Available placeholders (`src/documents/templating/workflows.py`)

All triggers:
`{correspondent}`, `{document_type}`, `{owner_username}`, `{original_filename}`,
`{filename}`, `{added}`, `{added_year}`, `{added_month}`, `{added_day}`, `{added_time}`

Added/Updated only:
`{doc_title}`, `{doc_url}` (requires `PAPERLESS_URL` set), `{created}`, `{created_year}`,
`{created_month}`, `{created_day}`, `{created_time}`

⚠️ **No `{document_id}` placeholder exists.** The PK is only accessible via `{doc_url}`
(e.g. `http://paperless.lan/documents/42/`). Parse or regex it at the receiver,
or add `doc_pk` upstream (small, well-scoped contribution).

---

## Confidentiality

Fields ranked by sensitivity:

| Sensitivity | Fields |
|---|---|
| **High** | `{correspondent}` ("Oncology Clinic"), `{document_type}`, tags (via post-consume), filenames, file paths, document content |
| **Medium** | `{owner_username}`, timestamps |
| **Low** | Document ID (opaque integer) — safe to send through a relay |

**Recommendation:** send only the document ID (via `{doc_url}`) through the relay.
Fetch all other details per-user over a trusted channel.

---

## Permissions Model

`DocumentViewSet` uses `ObjectOwnedOrGrantedPermissionsFilter`
(`src/documents/views.py:540`, `src/documents/filters.py:794`) — scopes every list/detail
response to owned-or-granted documents for the requesting user.

**This is the right enforcement point.** The webhook fires server-side with no notion
of per-user visibility. Do not resolve permissions in the relay.

---

## Recommended Architecture

```
paperless-ngx
  └─ Workflow (trigger: Document Added)
       └─ Webhook action
            ├─ url: http://relay.lan:9000/notify
            ├─ params: {"url": "{doc_url}"}   ← ID embedded in URL
            ├─ as_json: true
            └─ headers: {"Authorization": "Bearer <static-secret>"}

relay (user-hosted, LAN)
  └─ receives {url}, extracts document ID
  └─ for each logged-in user U:
       └─ GET /api/documents/?id__in={id}&fields=id,title,correspondent,created
          (using U's own token/session)
          ├─ non-empty → deliver notification to U (with fetched fields)
          └─ empty/404 → suppress (U has no access)
```

### Key design rules

1. **Send only the ID through the relay** — avoids leaking metadata to untrusted
   infrastructure. `{doc_url}` embeds the PK.
2. **Resolve permissions at delivery time**, not at event time — query per-user using
   each user's own credentials. Never use an admin token to gate visibility.
3. **Do not snapshot permissions into the notification** — owner/ACL may change
   after the webhook fires. Query fresh at delivery.
4. **Authenticate the relay** with a static shared secret in the `headers` field.
   For stronger integrity, consider HMAC of the payload at the relay layer.
5. **Leave `include_document=false`** — never route file content through the relay.

---

## Post-consume Script vs. Webhook Action

| | Webhook action | Post-consume script |
|---|---|---|
| Execution | Async Celery, retries | Blocks ingestion |
| Config | UI/API, per-workflow | Env var + mounted script |
| Doc ID | Only via `{doc_url}` | `$DOCUMENT_ID` directly |
| Filtering | Workflow trigger conditions | Every document |
| Recommended | ✅ Yes | Only if sync/scripting needed |

---

## Post-consume Script: Available Data (reference)

**Pre-consume** (`src/documents/consumer.py:238`): `$DOCUMENT_SOURCE_PATH`,
`$DOCUMENT_WORKING_PATH`, `$TASK_ID`. Non-zero exit aborts ingestion.

**Post-consume** (`src/documents/consumer.py:281`): `$DOCUMENT_ID`, `$DOCUMENT_CREATED`,
`$DOCUMENT_MODIFIED`, `$DOCUMENT_ADDED`, `$DOCUMENT_FILE_NAME`,
`$DOCUMENT_SOURCE_PATH`, `$DOCUMENT_ARCHIVE_PATH`, `$DOCUMENT_THUMBNAIL_PATH`,
`$DOCUMENT_DOWNLOAD_URL`, `$DOCUMENT_THUMBNAIL_URL`, `$DOCUMENT_OWNER`,
`$DOCUMENT_CORRESPONDENT`, `$DOCUMENT_TAGS`, `$DOCUMENT_ORIGINAL_FILENAME`,
`$TASK_ID`. Non-zero exit is logged but **does not roll back** the document.
