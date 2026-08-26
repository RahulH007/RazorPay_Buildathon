# Authorship and Provenance

**RecoverOS** is the original work of **Rahul Hongekar** — GitHub [@RahulH007](https://github.com/RahulH007) — created as a submission to the **Razorpay Buildathon, Track 03: AI Revenue Recovery**.

Copyright (c) 2026 Rahul Hongekar. All rights reserved.

No licence is granted. This repository is published for evaluation. It may be
read, cloned and run for the purpose of reviewing the submission. It may not be
submitted, in whole or in part, as anyone else's work to this or any other
competition, course, or employer.

## Evidence of origin

If authorship is ever disputed, these are the things worth looking at, in
descending order of weight:

1. **The commit history of this repository**, which records incremental
   authorship over time under the account above. A copy has one import commit,
   or a history that begins after this one.
2. **`backend/data/llm_cache.json`**, which records Gemini responses against
   this project's exact prompts, with recording timestamps.
3. **`results/`**, which holds committed output — including the ledger head
   hash — produced by the commands in the README.
4. **The attribution embedded throughout the code**, listed below.

## Where attribution appears

| Surface | Form |
|---|---|
| Every backend source and test file | Module header naming the author and repository |
| `backend/app/__about__.py` | The single source of truth all runtime surfaces read from |
| `GET /` and `GET /health` | Author and GitHub handle in the JSON response |
| OpenAPI schema at `/docs` | Contact block |
| `run_demo`, `verify_ledger`, `tamper_demo` | Banner line and closing notice in every receipt |
| Dashboard | Footer on every view |
| `index.html` | `author` meta tag and `rel="author"` link |
| `package.json` | `author` and `repository` fields |
| `README.md` | Header and footer |

A copy that leaves these in place is self-identifying. A copy that removes them
has had authorship deliberately stripped, which is a different conversation.

## What this is not

These markers deter casual copying and remove any plausible claim of accident.
They are not a technical control: anyone willing to spend ten minutes can remove
every one of them. The durable protection is the public, timestamped commit
history — which is why item 1 above is first.
