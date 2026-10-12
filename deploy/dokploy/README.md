# Dokploy candidate — preparation only

Review branch: codex/dokploy-staging-preparation. Build from the repository root using Dockerfile. Runtime units are the adjacent *.compose.yaml files; use their corresponding *.env.example names with protected server-side values. Never publish providers/stores to host ports or create replacement empty state for an existing provider.

Independent immutable images are selected by the inactive .github/workflows/dokploy-release.yml.disabled template. Container validation builds/tests only. deploy/scripts/render_release.py renders a single service digest; apply_release.py defaults to dry-run and needs separate approval before execution. No workflow enables deployment or invokes migrations. Store images must match the inventoried source version before restore.

The authoritative cross-repository staging order, Astra mapping, network/volume inventory, tests and rollback are in EduFusion-AI/docs/dokploy/STAGING_RUNBOOK.md and PREPARATION_REPORT.md on the same review branch. All Linux builds and target-host runtime checks remain UNVERIFIED until performed. Do not infer readiness from Compose parsing or local Windows tests.
