from contextlib import asynccontextmanager
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException

from admin_data import (
    list_clocks,
    list_latest_risk_students,
    run_demo_predictions,
    update_clock,
)
from predictor import EduPredictor
from schemas import (
    BatchRequest,
    BatchResponse,
    HealthResponse,
    PredictRequest,
    PredictResponse,
)
from student_data import build_student_prediction_request, save_prediction


predictor: EduPredictor | None = None


def verify_admin_key(x_admin_key: Optional[str] = Header(default=None)) -> None:
    expected = os.getenv("ADMIN_API_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY is not configured")
    if x_admin_key != expected:
        raise HTTPException(status_code=401, detail="Invalid admin key")


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


@app.post("/predict", response_model=PredictResponse, tags=["prediction"])
def predict(req: PredictRequest):
    if predictor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        return predictor.predict(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/predict/batch", response_model=BatchResponse, tags=["prediction"])
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
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/students/{id_student}/prediction",
    response_model=PredictResponse,
    tags=["students"],
)
def predict_student_from_database(
    id_student: int,
    code_module: Optional[str] = None,
    code_presentation: Optional[str] = None,
    threshold: Optional[float] = None,
):
    if predictor is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        enrollment_id, req = build_student_prediction_request(
            id_student=id_student,
            code_module=code_module,
            code_presentation=code_presentation,
            threshold=threshold,
        )
        response = predictor.predict(req)
        save_prediction(enrollment_id, response)
        return response
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/clock", tags=["admin"], dependencies=[Depends(verify_admin_key)])
def admin_list_clocks():
    try:
        return {"clocks": list_clocks()}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
