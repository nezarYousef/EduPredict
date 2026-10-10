import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException

from admin_data import (
    list_clocks,
    list_latest_risk_students,
    run_demo_predictions,
    update_clock,
)
from api_support import service_error, verify_admin_key
from service_auth import require_student_actor, require_service_admin
from db import get_connection
from predictor import EduPredictor
from scenario_data import apply_scenario
from schemas import (
    BatchRequest,
    BatchResponse,
    HealthResponse,
    PredictRequest,
    PredictResponse,
    ScenarioEvidence,
)
from student_data import (
    build_student_prediction_request,
    next_assessment_due_date,
    save_prediction,
)


predictor: EduPredictor | None = None
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global predictor
    predictor = EduPredictor()
    print(
        f"Model loaded - {len(predictor.feature_cols)} features "
        f"| threshold={predictor.default_threshold}"
    )
    yield


app = FastAPI(
    title="EduPredict API",
    description="Real-time student at-risk prediction",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health():
    if predictor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    return HealthResponse(
        status="ok",
        model_loaded=True,
        feature_count=len(predictor.feature_cols),
        snapshots=predictor.snapshots,
        default_threshold=predictor.default_threshold,
    )


@app.get("/ready", tags=["system"])
def ready():
    if predictor is None:
        raise HTTPException(
            status_code=503, detail="Prediction service is temporarily unavailable."
        )
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    except Exception as error:
        logger.error(
            "EduPredict readiness database check failed: %s (sqlstate=%s)",
            type(error).__name__,
            getattr(error, "sqlstate", None),
        )
        raise HTTPException(
            status_code=503,
            detail="Prediction data service is temporarily unavailable.",
        ) from None
    return {"status": "ready"}


@app.post("/predict", response_model=PredictResponse, tags=["prediction"], dependencies=[Depends(require_service_admin)])
def predict(req: PredictRequest):
    if predictor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        return predictor.predict(req)
    except Exception as e:
        raise service_error("predict", e) from None


@app.post("/predict/batch", response_model=BatchResponse, tags=["prediction"], dependencies=[Depends(require_service_admin)])
def predict_batch(req: BatchRequest):
    if predictor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    if not req.students:
        raise HTTPException(status_code=422, detail="students list is empty")

    if len(req.students) > 5000:
        raise HTTPException(
            status_code=422,
            detail="batch size exceeds limit of 5000 - split into smaller batches",
        )

    try:
        return predictor.predict_batch(req)
    except Exception as e:
        raise service_error("predict batch", e) from None


@app.get(
    "/students/{id_student}/prediction",
    response_model=PredictResponse,
    tags=["students"],
    dependencies=[Depends(require_student_actor)],
)
def predict_student_from_database(
    id_student: int,
    code_module: Optional[str] = None,
    code_presentation: Optional[str] = None,
    threshold: Optional[float] = None,
):
    return _student_prediction(id_student, code_module, code_presentation, threshold, persist=False)


@app.post(
    "/students/{id_student}/prediction",
    response_model=PredictResponse,
    tags=["students"],
    dependencies=[Depends(require_student_actor)],
)
def generate_student_prediction(
    id_student: int,
    code_module: Optional[str] = None,
    code_presentation: Optional[str] = None,
    threshold: Optional[float] = None,
):
    return _student_prediction(id_student, code_module, code_presentation, threshold, persist=True)


def _student_prediction(id_student, code_module, code_presentation, threshold, *, persist):
    if predictor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        enrollment_id, req = build_student_prediction_request(
            id_student=id_student,
            code_module=code_module,
            code_presentation=code_presentation,
            threshold=threshold,
        )
    except LookupError:
        raise HTTPException(
            status_code=404, detail="No enrollment found for this student"
        ) from None
    except Exception as e:
        raise service_error("student data load", e, database=True) from None

    try:
        response = predictor.predict(req)
    except Exception as e:
        raise service_error("student prediction", e) from None

    if persist:
        try:
            save_prediction(enrollment_id, response)
        except Exception as e:
            raise service_error("prediction save", e, database=True) from None
    return response


@app.post(
    "/students/{id_student}/scenario-prediction",
    response_model=PredictResponse,
    tags=["students"],
    dependencies=[Depends(require_student_actor)],
)
def predict_student_scenario(
    id_student: int,
    scenario: ScenarioEvidence,
    code_module: Optional[str] = None,
    code_presentation: Optional[str] = None,
):
    if predictor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    try:
        enrollment_id, base = build_student_prediction_request(
            id_student=id_student,
            code_module=code_module,
            code_presentation=code_presentation,
        )
        hypothetical = apply_scenario(
            base, scenario, enrollment_id, next_assessment_due_date
        )
    except LookupError:
        raise HTTPException(
            status_code=404, detail="No enrollment found for this student"
        ) from None
    except ValueError:
        raise HTTPException(
            status_code=422, detail="Scenario evidence is invalid or stale."
        ) from None
    except Exception as error:
        raise service_error("scenario data load", error, database=True) from None
    try:
        # Never write this result to the real predictions table.
        return predictor.predict(hypothetical)
    except Exception as error:
        raise service_error("scenario prediction", error) from None


@app.get("/admin/clock", tags=["admin"], dependencies=[Depends(verify_admin_key)])
def admin_list_clocks():
    try:
        return {"clocks": list_clocks()}
    except Exception as e:
        raise service_error("list clocks", e, database=True) from None


@app.post("/admin/clock/tick", tags=["admin"])
def admin_tick_clock(
    code_module: str,
    code_presentation: str,
    days: int = 1,
    x_admin_key: Optional[str] = Header(default=None),
):
    verify_admin_key(x_admin_key)
    try:
        return update_clock(
            code_module=code_module,
            code_presentation=code_presentation,
            tick_days=days,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Clock not found") from None
    except Exception as e:
        raise service_error("tick clock", e, database=True) from None


@app.post("/admin/clock/reset", tags=["admin"])
def admin_reset_clock(
    code_module: str,
    code_presentation: str,
    day: int = 60,
    x_admin_key: Optional[str] = Header(default=None),
):
    verify_admin_key(x_admin_key)
    try:
        return update_clock(
            code_module=code_module,
            code_presentation=code_presentation,
            current_day=day,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Clock not found") from None
    except Exception as e:
        raise service_error("reset clock", e, database=True) from None


@app.post(
    "/admin/predictions/run-demo",
    tags=["admin"],
    dependencies=[Depends(verify_admin_key)],
)
def admin_run_demo_predictions(limit: int = 150):
    if predictor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        return run_demo_predictions(predictor, limit=limit)
    except Exception as e:
        raise service_error("run demo predictions", e, database=True) from None


@app.get("/admin/students/at-risk", tags=["admin"])
def admin_list_at_risk_students(
    risk_level: Optional[str] = None,
    at_risk: Optional[bool] = None,
    limit: int = 50,
    x_admin_key: Optional[str] = Header(default=None),
):
    verify_admin_key(x_admin_key)
    try:
        return {
            "students": list_latest_risk_students(
                risk_level=risk_level,
                at_risk=at_risk,
                limit=limit,
            )
        }
    except Exception as e:
        raise service_error("list at-risk students", e, database=True) from None
