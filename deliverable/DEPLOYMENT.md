# EduPredict staging: read-only database rollout

This change is prepared from deployed revision b92197d1851e514c901176a94762836495698d8f.
It preserves the model artifact, feature logic, scores, service authentication and
response contracts. Database mutations now require an explicit
EDUPREDICT_ALLOW_DATABASE_WRITES=true opt-in. The default is false. Read-only database
grants remain the independent protection; this flag does not grant database privileges.

Denied by default, after the existing authentication checks:

- POST /students/{id}/prediction (prediction persistence).
- POST /admin/clock/tick and /admin/clock/reset (academic clock updates).
- POST /admin/predictions/run-demo (writes real predictions despite its name).

The persistence and clock helpers also enforce this boundary before connection/SQL.
GET student prediction and POST scenario prediction do not persist. Generic POST /predict
and /predict/batch are stateless inference, not database mutations. They keep their
service-admin authentication. Do not treat every POST as a database write.

## Build boundary

Use the reviewed explicit Dockerfile with Build Path /deliverable, Dockerfile Dockerfile,
Docker context ./deliverable, final stage, internal port 8000. The pinned Python 3.11
image installs the unchanged pinned dependencies and libgomp1, copies only API Python
files and the exact model artifact, and runs as UID/GID 10001 with access logging off.
Its health check establishes loaded-model liveness only. /ready separately verifies DB.

Before a build, set createEnvFile=false and ensure Build Args, Build Secrets, project
shared environment and environment shared environment are empty. Dokploy 0.30.8's
Dockerfile builder uses Build Args plus shared scopes; its Nixpacks builder passes
runtime environment through --env. Runtime application credentials belong only in
the application's private runtime environment. Do not supply either service/admin key
or DATABASE_URL to the build. The Dockerfile has no credential ARG/ENV and its context
excludes environment/key files. No NIXPACKS_PATH is used or needed in the new image.

NIXPACKS_PYTHON_VERSION and NIXPACKS_APT_PKGS become obsolete when switching builders;
review their removal separately. Preserve PORT=8000 and existing thread controls.
No source setting automatically changes Dokploy configuration or deployments.

## Database boundary

Proposed role: edufusion_edupredict_readonly, initially NOLOGIN, no memberships, no
superuser/role/database creation/replication/bypass-RLS privileges. Only CONNECT,
public schema USAGE, and SELECT on exactly 32 columns across these seven objects:

| Object | Columns |
| --- | --- |
| prediction_base_view | all 13 current view columns |
| enrollments | id, course_presentation_id |
| academic_clocks | course_presentation_id, current_day |
| student_vle_events | enrollment_id, id_site, date, sum_click |
| vle_sites | id_site, activity_type |
| student_assessments | id, enrollment_id, id_assessment, date_submitted, score |
| assessments | id_assessment, course_presentation_id, assessment_type, date |

The audited view uses its existing administrator owner's permissions and has no
security_invoker option. No direct students, course_presentations, predictions,
demo_enrollments, sequence or write grants are required for student/scenario inference.
Admin clock/at-risk read APIs are outside this initial role's scope. Do not grant broad
access just to make those endpoints pass. Reaudit if source/view definitions change.

The SQL proposal is a separate reviewed operation, never a Docker startup action or
migration. Provision the password privately via an interactive psql hidden prompt;
never send it through chat, browser automation, command arguments, history or logs.
Enable login only after approved grants and private credential setup. The operator
privately constructs DATABASE_URL using host postgres, port 5432, the protected database,
the dedicated role and sslmode=disable on the internal network. No URL belongs in source.

Current EduPredict has no DATABASE_URL and only dokploy-network, explaining /ready=503.
The future service must persist both dokploy-network and edufusion-staging-backend-db
in its Swarm service spec. PostgreSQL must remain off the public application network.
The existing internal attachable overlay and postgres alias must be verified before use.

## Rollout and coordinated credential rotation

Do not deploy or merge until these gates are satisfied:

1. Freeze EduPredict automatic/manual/webhook deployments and image cleanup for the
   maintenance window. Backend Auto Deploy stays off. Retain the exact current image
   under a dedicated tag/archive and verify loading only that tag preserves latest.
2. Human privately retains the complete EduPredict runtime environment in an encrypted
   vault and confirms recoverability. Capture only non-secret Dokploy source/build/network
   settings. An image ID alone is not a complete rollback strategy.
3. Approve and apply the dedicated read-only role transaction, privately provision its
   password, and perform metadata-only TCP/identity/privilege/LIMIT-0 checks from the
   intended service network. No migrations or academic data writes.
4. Build the reviewed source under a new candidate tag with zero runtime secrets in the
   build. Verify image ENV names lack ADMIN_API_KEY, EDUPREDICT_SERVICE_KEY and DATABASE_URL;
   verify logs lack SecretsUsedInArgOrEnv and undefined NIXPACKS_PATH warnings.
5. Privately update only approved runtime values and preserve false write mode. Apply
   private networking and the clean source/build in an EduPredict-only approved rollout.
   Verify /health=200 and /ready=200, read-only identity and exact column privileges.
6. Because old images contain key-named entries, privately assess exposure and coordinate
   new runtime-only service/admin credentials. Synchronize the service key in EduPredict
   and the Backend within the reviewed window. The accepted Backend admin route also
   reads ADMIN_API_KEY for run-demo: coordinate any existing Backend admin-key setting
   and legitimate private operator clients when rotating that key. Do not add new admin
   access or enable writes. Do not put new keys into the old Nixpacks build path.
   A short upstream-authentication interruption may occur without a dual-key protocol;
   do not assume an atomic cross-service environment update exists.
7. Validate authentication using synthetic requests that cannot persist data. Keep all
   clock/demo/persistence routes denied. Preserve the already accepted student/front-end
   flow; test fresh database-backed inference only with authorized synthetic test scope.

If rollout fails, stop further deployments and restore the checksum-verified old image
while preserving **current rotated keys** as runtime overrides. Restore the prior
environment/build/network baseline privately, overlaid with current approved credentials;
do not automatically restore revoked/baked keys. Retain the read-only DB role so the old
image cannot write academic records even though it predates the application guard.
Reverify image identity, model liveness, DB readiness, networks and authentication.
Never rebuild a moving branch as an image rollback or run schema migrations for recovery.

Do not prune old images/caches/archives automatically. Treat old image archives as
sensitive because they may contain old credential material; restrict them to root and
review retention/removal after successful acceptance and credential revocation.
