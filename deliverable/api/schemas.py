from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# ---- input: one VLE click event ----
class VLEEvent(BaseModel):
    date: int  # day relative to course start (negative = before start)
    sum_click: int  # number of clicks in this session
    activity_type: str  # e.g. "quiz", "forumng", "resource"


# ---- input: one assessment submission ----
class AssessmentSubmission(BaseModel):
    date_submitted: int  # day student submitted
    score: float  # 0-100
    assessment_type: str  # "TMA", "CMA", or "Exam"
    date: Optional[float] = None  # due date (None if unknown)


# ---- input: static student demographics ----
class Demographics(BaseModel):
    code_module: str
    gender_bin: int = Field(ge=0, le=1)
    disability_bin: int = Field(ge=0, le=1)
    age_numeric: int = Field(ge=0, le=2)
    edu_numeric: int = Field(ge=0, le=4)
    imd_numeric: float = Field(ge=0, le=100)
    num_of_prev_attempts: int = Field(ge=0)
    studied_credits: int = Field(gt=0)
    module_total_assessments: int = Field(gt=0)
    course_length: int = Field(gt=0)


# ---- main request body ----
class PredictRequest(BaseModel):
    day_of_course: int = Field(ge=0)
    demographics: Demographics
    # Preserve the published [] defaults in OpenAPI while allocating fresh lists.
    vle_log: list[VLEEvent] = Field(
        default_factory=list, json_schema_extra={"default": []}
    )
    assess_log: list[AssessmentSubmission] = Field(
        default_factory=list, json_schema_extra={"default": []}
    )
    threshold: Optional[float] = None  # overrides model default if provided

    @field_validator("threshold")
    @classmethod
    def threshold_range(cls, v):
        if v is not None and not (0.0 < v < 1.0):
            raise ValueError("threshold must be between 0 and 1")
        return v


class ScenarioClick(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: int = Field(ge=0)
    clicks: int = Field(ge=1)


class ScenarioInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quiz_clicks: int = Field(default=0, ge=0)
    forum_clicks: int = Field(default=0, ge=0)
    resource_clicks: int = Field(default=0, ge=0)
    activity_days: int = Field(default=1, ge=1)
    latest_tma_score: Optional[float] = Field(default=None, ge=0, le=100)
    tma_delay_days: Optional[int] = Field(default=None, ge=0)
    latest_cma_score: Optional[float] = Field(default=None, ge=0, le=100)
    cma_delay_days: Optional[int] = Field(default=None, ge=0)
    new_submission_type: Optional[str] = None
    new_submission_score: Optional[float] = Field(default=None, ge=0, le=100)
    new_submission_delay_days: Optional[int] = Field(default=None, ge=0)

    @field_validator("new_submission_type")
    @classmethod
    def submission_type(cls, value):
        if value is not None and value not in ("TMA", "CMA"):
            raise ValueError("new_submission_type must be TMA or CMA")
        return value


class ScenarioActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quiz_clicks: list[ScenarioClick] = Field(default_factory=list)
    forum_clicks: list[ScenarioClick] = Field(default_factory=list)
    resource_clicks: list[ScenarioClick] = Field(default_factory=list)


class ScenarioEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    based_on_day: int = Field(ge=0)
    inputs: ScenarioInputs
    activity: ScenarioActivity


# ---- batch request: list of students ----
class BatchItem(BaseModel):
    student_id: str | int
    request: PredictRequest


class BatchRequest(BaseModel):
    students: list[BatchItem]
    threshold: Optional[float] = None  # applies to all if not overridden per student


# ---- output: model confidence info ----
class ModelConfidence(BaseModel):
    day_of_course: int
    closest_snapshot: int
    expected_f1: float
    expected_auc: float


# ---- output: data completeness info ----
class DataCompleteness(BaseModel):
    has_vle_data: bool
    has_assessment_data: bool
    features_available: int
    features_total: int
    completeness_pct: float


# ---- main response ----
class PredictResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    risk_probability: float
    risk_level: RiskLevel
    at_risk: int
    recommended_action: str
    explanation: list[str]
    threshold_used: float
    model_confidence: ModelConfidence
    data_completeness: DataCompleteness


# ---- batch response: one row per student ----
class BatchStudentResult(BaseModel):
    student_id: str | int
    risk_probability: float
    risk_level: RiskLevel
    at_risk: int
    explanation: list[str]
    completeness_pct: float


class BatchResponse(BaseModel):
    total_students: int
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    threshold_used: float
    results: list[BatchStudentResult]  # sorted by risk_probability desc


# ---- health check response ----
class HealthResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    status: str  # "ok" or "error"
    model_loaded: bool
    feature_count: int
    snapshots: list[int]
    default_threshold: float
