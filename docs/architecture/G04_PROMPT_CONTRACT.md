# G04 Prompt Contract

This document describes the public input/output contract expected by G04. It is not a production prompt and contains no API key, token, endpoint, or secret instruction.

## Input To A Future AI Provider

The future provider should receive only normalized document context prepared by Canonical:

- `document_id`
- document metadata that is safe for task extraction
- attachment ids
- extracted page text from G03
- page numbers
- optional unit/person mapping hints when available

The provider must not receive browser cookies, QLVB session material, Planner KPI credentials, or raw local file paths unless a later approved phase explicitly adds that capability.

## Output From AI

The provider must return a single JSON object matching `docs/architecture/G04_AI_OUTPUT_SCHEMA.json` and `AI_PROPOSAL_SCHEMA_VERSION = "1.0.0"`.

Every proposal must include:

- task title and description
- proposed unit, assignee, and supervisor ids when known, otherwise `null`
- due date in ISO `YYYY-MM-DD` format when known, otherwise `null`
- expected output and output type
- priority and complexity
- confidence from `0.0` to `1.0`
- citation list with attachment id, page range, excerpt, and optional character range
- short `reasoning_summary`
- warnings for missing or uncertain fields

## Output Rules

- Do not output free-form text outside JSON.
- Do not include chain-of-thought or long hidden reasoning.
- Do not set task status.
- Do not set `APPROVED`, `SYNC_PENDING`, `SYNCING`, or `SYNCED`.
- Do not invent ids for people or units when uncertain; use `null` and a warning.
- Do not include hashes; Canonical recomputes citation hashes.
- Do not include API tokens, cookies, or credentials.

## G04 Boundary

G04 accepts fake responses and validates the contract. It does not execute this prompt against any production model. Production provider selection and prompt execution belong to a later phase.
