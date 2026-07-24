# Configuration contract

Updated: 2026-07-24

All entries below are **CODE_FACT** from `config.py`; names are documented without values from any operator environment.

| Field/group | Source and default | Required/validation |
| --- | --- | --- |
| Config file | Explicit CLI config path, environment-selected config path, then known project-relative candidates. | `load_config` raises `FileNotFoundError` when no config is found. |
| `qlvb_base_url`, `login_url` | JSON/legacy aliases; empty default. `login_url` falls back to base URL. | Optional at dataclass construction; live workflows require usable runtime URLs. |
| `incoming_registry_url` | JSON or aliases for incoming registry; empty default. | Separate from legacy pending URL; optional. |
| `incoming_pending_url`, `incoming_processed_url`, `outgoing_issued_url` | JSON/legacy aliases; empty defaults. | Optional; historical/general downloader configuration. |
| Browser group | Defaults: headed, timeout, manual-login enabled, project-relative persistent profile. | Unknown keys are filtered before `BrowserConfig` construction. |
| Download group | Defaults include bounded items/pages, retry values, report/export behavior, and minimum size. | Unknown keys are filtered before `DownloadConfig` construction. |
| `save_root` | JSON or alias; default `Data`. | `load_config` creates the resolved root and browser-profile directories. |
| `selectors` | Deep merge of JSON selectors over safety defaults. | Default selector list entries are retained after merge. |
| Authentication and planner fields | JSON/environment sources supported by code. | Never place their values in memory, commands, logs, or fixtures. |

## CDP-specific configuration

- **CODE_FACT**: the CDP endpoint default is defined in `cdp_workflow.py` as a loopback endpoint.
- **CODE_FACT**: `run_cdp_three_category_smoke` accepts optional `output_dir` and `endpoint` parameters; the CLI currently exposes the output directory flag, not an endpoint override flag.
- **TEST_VERIFIED**: `test_config_maps_incoming_registry_without_reusing_legacy_pending_url` verifies the incoming-registry mapping boundary.
