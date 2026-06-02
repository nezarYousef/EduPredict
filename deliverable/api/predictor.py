import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from schemas import (
    PredictRequest, PredictResponse, BatchRequest, BatchResponse,
    BatchStudentResult, ModelConfidence, DataCompleteness, RiskLevel
)

DEFAULT_THRESHOLD = 0.41
MODEL_PATH        = Path(__file__).resolve().parent / "edu_model" / "temporal_lgbm_model_final.pkl"


class EduPredictor:
    """
    Loads the model once at startup and exposes predict / predict_batch.
    All feature engineering lives here â€” main.py stays clean.
    """

    def __init__(self):
        artifact          = joblib.load(MODEL_PATH)
        self.model        = artifact["model"]
        self.feature_cols = artifact["feature_cols"]
        self.snapshots    = artifact["snapshots"]
        self.day_results  = artifact["day_results"]
        self.default_threshold = DEFAULT_THRESHOLD

    # ------------------------------------------------------------------
    # public interface
    # ------------------------------------------------------------------

    def predict(self, req: PredictRequest) -> PredictResponse:
        threshold = req.threshold if req.threshold is not None else self.default_threshold
        row       = self._build_features(req)
        prob      = float(self.model.predict_proba(row)[0][1])
        label     = int(prob >= threshold)

        return PredictResponse(
            risk_probability   = round(prob, 4),
            risk_level         = self._risk_level(prob, threshold),
            at_risk            = label,
            recommended_action = self._action(prob, threshold),
            explanation        = self._explain(req, prob),
            threshold_used     = threshold,
            model_confidence   = self._confidence(req.day_of_course),
            data_completeness  = self._completeness(req, row),
        )

    def predict_batch(self, req: BatchRequest) -> BatchResponse:
        threshold = req.threshold if req.threshold is not None else self.default_threshold
        results   = []

        for item in req.students:
            # per-student threshold override takes priority
            effective_t = item.request.threshold or threshold
            row         = self._build_features(item.request)
            prob        = float(self.model.predict_proba(row)[0][1])
            comp        = self._completeness(item.request, row)

            results.append(BatchStudentResult(
                student_id       = item.student_id,
                risk_probability = round(prob, 4),
                risk_level       = self._risk_level(prob, effective_t),
                at_risk          = int(prob >= effective_t),
                explanation      = self._explain(item.request, prob),
                completeness_pct = comp.completeness_pct,
            ))

        results.sort(key=lambda r: r.risk_probability, reverse=True)

        return BatchResponse(
            total_students    = len(results),
            high_risk_count   = sum(1 for r in results if r.risk_level == RiskLevel.HIGH),
            medium_risk_count = sum(1 for r in results if r.risk_level == RiskLevel.MEDIUM),
            low_risk_count    = sum(1 for r in results if r.risk_level == RiskLevel.LOW),
            threshold_used    = threshold,
            results           = results,
        )

    # ------------------------------------------------------------------
    # feature engineering â€” mirrors step3_realtime_predictor.py
    # ------------------------------------------------------------------

    def _build_features(self, req: PredictRequest) -> pd.DataFrame:
        demo    = req.demographics
        day     = req.day_of_course
        vle     = self._vle_features(day, req.vle_log)
        assess  = self._assess_features(day, req.assess_log,
                                        demo.module_total_assessments)

        row = {
            "code_module":               demo.code_module,
            "gender_bin":                demo.gender_bin,
            "disability_bin":            demo.disability_bin,
            "age_numeric":               demo.age_numeric,
            "edu_numeric":               demo.edu_numeric,
            "imd_numeric":               demo.imd_numeric,
            "num_of_prev_attempts":      demo.num_of_prev_attempts,
            "studied_credits":           demo.studied_credits,
            "module_total_assessments":  demo.module_total_assessments,
            "course_length":             demo.course_length,
            "days_into_course":          day,
            "snapshot_progress":         day / demo.course_length if demo.course_length > 0 else 0.0,
            **vle,
            **assess,
        }

        df = pd.DataFrame([row])
        df["code_module"] = df["code_module"].astype("category")

        # add any column the model expects but we didn't compute
        for col in self.feature_cols:
            if col not in df.columns:
                df[col] = np.nan

        return df[self.feature_cols]

    def _vle_features(self, day: int, events: list) -> dict:
        nan = {
            "total_clicks": np.nan, "active_days": np.nan,
            "avg_clicks_per_day": np.nan, "quiz_clicks": np.nan,
            "forumng_clicks": np.nan, "resource_clicks": np.nan,
            "clicked_before_start": np.nan, "days_since_last_click": np.nan,
            "click_trend": np.nan, "click_consistency": np.nan,
        }
        if not events:
            return nan

        sv = pd.DataFrame([e.model_dump() for e in events])
        sv = sv[sv["date"] <= day]
        if sv.empty:
            return nan

        tc = float(sv["sum_click"].sum())
        ad = float(sv["date"].nunique())

        def type_clicks(t):
            m = sv["activity_type"] == t
            return float(sv.loc[m, "sum_click"].sum()) if m.any() else 0.0

        days_since = float(day - sv["date"].max())
        mid        = day / 2

        early_clicks = float(sv[sv["date"] <= mid]["sum_click"].sum())
        late_clicks  = float(sv[sv["date"] > mid]["sum_click"].sum())

        return {
            "total_clicks":          tc,
            "active_days":           ad,
            "avg_clicks_per_day":    round(tc / ad, 2) if ad > 0 else np.nan,
            "quiz_clicks":           type_clicks("quiz"),
            "forumng_clicks":        type_clicks("forumng"),
            "resource_clicks":       type_clicks("resource"),
            "clicked_before_start":  1.0 if (sv["date"] < 0).any() else 0.0,
            "days_since_last_click": days_since,
            "click_trend":           late_clicks - early_clicks if day > 0 else np.nan,
            "click_consistency":     ad / day if day > 0 else np.nan,
        }

    def _assess_features(self, day: int, submissions: list, module_total: int) -> dict:
        nan = {
            "avg_score": np.nan, "num_submitted": np.nan, "num_failed": np.nan,
            "submission_rate": np.nan, "avg_tma_score": np.nan,
            "avg_cma_score": np.nan, "avg_days_late": np.nan,
            "score_trend": np.nan, "submission_consistency": np.nan,
        }
        if not submissions:
            return nan

        sa = pd.DataFrame([s.model_dump() for s in submissions])
        sa = sa[sa["date_submitted"] <= day]
        if sa.empty:
            return nan

        scores  = sa["score"].fillna(0)
        num_sub = len(sa)
        tma     = sa[sa["assessment_type"] == "TMA"]["score"].dropna()
        cma     = sa[sa["assessment_type"] == "CMA"]["score"].dropna()

        sa_dated = sa.dropna(subset=["date"])
        avg_late = float((sa_dated["date_submitted"] - sa_dated["date"]).mean()) \
                   if not sa_dated.empty else np.nan

        # score trend: last half vs first half
        if num_sub >= 2:
            half      = num_sub // 2
            sorted_sa = sa.sort_values("date_submitted")
            score_trend = float(
                sorted_sa.iloc[half:]["score"].fillna(0).mean() -
                sorted_sa.iloc[:half]["score"].fillna(0).mean()
            )
        else:
            score_trend = np.nan

        # submission consistency: on-time ratio
        if not sa_dated.empty:
            on_time = (sa_dated["date_submitted"] <= sa_dated["date"]).sum()
            sub_consistency = float(on_time / len(sa_dated))
        else:
            sub_consistency = np.nan

        return {
            "avg_score":              float(scores.mean()),
            "num_submitted":          float(num_sub),
            "num_failed":             float((scores < 40).sum()),
            "submission_rate":        min(num_sub / module_total, 1.0),
            "avg_tma_score":          float(tma.mean()) if not tma.empty else np.nan,
            "avg_cma_score":          float(cma.mean()) if not cma.empty else np.nan,
            "avg_days_late":          avg_late,
            "score_trend":            score_trend,
            "submission_consistency": sub_consistency,
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _risk_level(self, prob: float, threshold: float) -> RiskLevel:
        # fixed tiers regardless of threshold value
        # threshold only controls at_risk binary label
        if prob >= 0.70:
            return RiskLevel.HIGH
        if prob >= threshold:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _action(self, prob: float, threshold: float) -> str:
        level = self._risk_level(prob, threshold)
        actions = {
            RiskLevel.HIGH:   "Contact student immediately",
            RiskLevel.MEDIUM: "Monitor closely, send reminder",
            RiskLevel.LOW:    "No action needed",
        }
        return actions[level]

    def _explain(self, req: PredictRequest, prob: float) -> list[str]:
        reasons = []
        subs    = req.assess_log

        if subs:
            sa   = pd.DataFrame([s.model_dump() for s in subs])
            sa   = sa[sa["date_submitted"] <= req.day_of_course]
            if not sa.empty:
                avg  = sa["score"].fillna(0).mean()
                late = sa.dropna(subset=["date"])

                if avg < 40:
                    reasons.append(f"very low scores (avg {avg:.1f})")
                elif avg < 55:
                    reasons.append(f"below-average scores (avg {avg:.1f})")

                if not late.empty:
                    days_late = (late["date_submitted"] - late["date"]).mean()
                    if days_late > 3:
                        reasons.append(f"submitting late on average ({days_late:.1f} days)")

                # score trend
                if len(sa) >= 2:
                    half      = len(sa) // 2
                    sorted_sa = sa.sort_values("date_submitted")
                    early_avg = sorted_sa.iloc[:half]["score"].fillna(0).mean()
                    late_avg  = sorted_sa.iloc[half:]["score"].fillna(0).mean()
                    trend     = late_avg - early_avg
                    if trend < -10:
                        reasons.append(f"score declining ({trend:+.1f} points)")
                    elif trend > 10:
                        reasons.append(f"score improving ({trend:+.1f} points)")
        else:
            reasons.append("no assessment submissions yet")

        events = req.vle_log
        if events:
            sv = pd.DataFrame([e.model_dump() for e in events])
            sv = sv[sv["date"] <= req.day_of_course]
            if sv.empty:
                reasons.append("no VLE activity recorded yet")
            else:
                tc         = sv["sum_click"].sum()
                days_since = req.day_of_course - sv["date"].max()

                if tc < 50:
                    reasons.append(f"very low platform engagement ({int(tc)} clicks)")
                if days_since > 14:
                    reasons.append(f"no activity for {int(days_since)} days")

                # click trend
                if req.day_of_course > 0:
                    mid          = req.day_of_course / 2
                    early_clicks = sv[sv["date"] <= mid]["sum_click"].sum()
                    late_clicks  = sv[sv["date"] >  mid]["sum_click"].sum()
                    trend        = int(late_clicks - early_clicks)
                    if trend < -30:
                        reasons.append(f"engagement dropping ({trend:+d} clicks second half)")
                    elif trend > 30 and prob < 0.4:
                        reasons.append(f"engagement increasing ({trend:+d} clicks second half)")
        else:
            reasons.append("no VLE activity recorded yet")

        if not reasons:
            if prob < 0.41:
                reasons.append("good engagement and assessment performance")
            else:
                reasons.append("moderate risk based on combined signals")
        return reasons

    def _confidence(self, day: int) -> ModelConfidence:
        closest = min(self.snapshots, key=lambda d: abs(d - day))
        stats   = self.day_results.get(closest, {})
        return ModelConfidence(
            day_of_course    = day,
            closest_snapshot = closest,
            expected_f1      = round(stats.get("f1",  0.0), 4),
            expected_auc     = round(stats.get("auc", 0.0), 4),
        )

    def _completeness(self, req: PredictRequest, row: pd.DataFrame) -> DataCompleteness:
        has_vle    = bool(req.vle_log)
        has_scores = bool(req.assess_log)
        numeric    = [c for c in self.feature_cols
                      if row[c].dtype != "category"]
        available  = int(row[numeric].notna().sum().sum())

        return DataCompleteness(
            has_vle_data        = has_vle,
            has_assessment_data = has_scores,
            features_available  = available,
            features_total      = len(self.feature_cols),
            completeness_pct    = round(available / len(self.feature_cols) * 100, 1),
        )
