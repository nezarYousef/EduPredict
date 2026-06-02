# EduPredict Clean Deliverable

This folder is the cleaned version of the EduPredict project for demo/evaluation.

## Structure

- `api/`: FastAPI application and prediction logic.
- `api/edu_model/`: trained temporal LightGBM model artifact used by the API.
- `data/`: test/train/temporal datasets used for evaluation and examples.
- `scripts/`: utility scripts for local evaluation.
- `tests/`: API smoke tests.
- `notebooks/`: final feature engineering and temporal training notebooks.
- `docs/`: threshold analysis output.

## Run API

From this folder:

```bash
cd api
uvicorn main:app --host 0.0.0.0 --port 8000
```

Development mode:

```bash
cd api
uvicorn main:app --reload --port 8000
```

## Recommended Threshold

Default API threshold is `0.41`, selected because it gives the best F1 balance on the temporal test split.

Summary on temporal test split:

| Threshold | Accuracy | F1 | Recall | Precision |
|---:|---:|---:|---:|---:|
| 0.27 | 0.7713 | 0.8125 | 0.9430 | 0.7137 |
| 0.41 | 0.8207 | 0.8353 | 0.8651 | 0.8075 |
| 0.50 | 0.8256 | 0.8284 | 0.8010 | 0.8578 |

For early warning systems, F1 and Recall are more important than Accuracy alone.

## Evaluate Model

```bash
python scripts/evaluate_thresholds.py
```

## Run Tests

```bash
pytest tests
```

## Notes

The API expects real-time style inputs:

- `demographics`: static student/course information.
- `vle_log`: VLE events up to the selected day.
- `assess_log`: assessment submissions up to the selected day.

If logs are empty, many engineered features become missing. The model may interpret missing activity/submission history as a high-risk signal, especially after the beginning of the course.
