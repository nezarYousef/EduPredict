import pandas as pd
import joblib
from pathlib import Path
from sklearn.metrics import accuracy_score, f1_score, recall_score, precision_score, roc_auc_score, confusion_matrix
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "api" / "edu_model" / "temporal_lgbm_model_final.pkl"
DATA_PATH = ROOT / "data" / "temporal_dataset_v2.csv"
THRESHOLDS = [0.27, 0.41, 0.50]

artifact = joblib.load(MODEL_PATH)
model = artifact["model"]
feature_cols = artifact["feature_cols"]

df = pd.read_csv(DATA_PATH)
labels = df.groupby("id_student")["at_risk"].first()
all_students = df["id_student"].unique()
_, test_students = train_test_split(
    all_students,
    test_size=0.2,
    stratify=labels[all_students],
    random_state=42,
)

test_df = df[df["id_student"].isin(test_students)].copy()
X_test = test_df[feature_cols].copy()
y_test = test_df["at_risk"].astype(int)
X_test["code_module"] = X_test["code_module"].astype("category")
y_prob = model.predict_proba(X_test)[:, 1]

print(f"Test rows: {len(test_df):,}")
print(f"ROC AUC: {roc_auc_score(y_test, y_prob):.4f}\n")

rows = []
for threshold in THRESHOLDS:
    y_pred = (y_prob >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_test, y_pred).ravel()
    rows.append({
        "threshold": threshold,
        "accuracy": accuracy_score(y_test, y_pred),
        "f1": f1_score(y_test, y_pred),
        "recall": recall_score(y_test, y_pred),
        "precision": precision_score(y_test, y_pred),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    })

print(pd.DataFrame(rows).to_string(index=False))
