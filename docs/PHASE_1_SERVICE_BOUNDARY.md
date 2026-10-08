# Phase 1 gateway contract

Baseline: `384c2f68ca5dee882a00d5cdcc2095e6459edab4`.

Private prediction routes require `EDUPREDICT_SERVICE_KEY` (distinct random secret, at least 32 characters), presented as `X-Service-Key`. The trusted EduFusion backend supplies `X-EduFusion-Role: student` and `X-EduFusion-Student-Id` derived from its authenticated database-backed user. A student may access only the matching path ID. Trusted `admin` actors may use the generic /predict and /predict/batch APIs. Browser-provided identity headers alone are never sufficient. Missing server configuration fails 503; missing/incorrect credentials fail 401; foreign/missing/invalid actor claims fail 403 before reading academic data.

GET /students/{id_student}/prediction computes without calling save_prediction. POST on the same URL explicitly computes and saves. Query parameters, response models, model artifact, features/order, thresholds and predictor numerical behavior are unchanged. Scenario POST calculates a projection without saving actual predictions. Existing admin clock/run-demo/at-risk APIs retain their separate ADMIN_API_KEY authentication.

Dependency: GraduationGroup101/EduFusion-AI branch codex/phase-0-1-security-foundation. Its gateway sends the service headers and uses POST for explicit regeneration. The old gateway cannot call these newly protected routes. Review provider PR first; release with the new gateway and matching keys only in a later authorized maintenance window. Merging can trigger hosting auto-deploys; do not merge until that behavior is controlled. Do not place service/provider/DB credentials in the browser, source or logs. No migration or production configuration is changed by this PR.

Validation: PYTHONPATH=deliverable/api python -m pytest -q deliverable/tests; python deliverable/tests/verify_refactor_equivalence.py. Numerical fixtures and model artifact are preserved; OpenAPI fixture changes only by adding the explicit POST route. Full original-vs-refactored equivalence checks remain mandatory.

Rollback: pause the integration and keep the authentication boundary. Revert a compatible adapter/UI only; never restore unauthenticated access or GET persistence. No data rewrite/credential reset/model retraining is required. Database reader/writer/migrator grants remain an UNVERIFIED operational release gate.
