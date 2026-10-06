"""Independent comparison to the original main revision (not fixture regeneration)."""

import ast
from collections import Counter
import hashlib
import random
import subprocess
import sys
import types
from pathlib import Path

root = Path(__file__).resolve().parents[2]
api = root / "deliverable/api"
sys.path[:0] = [str(api), str(root / "deliverable/tests")]
from pandas.testing import assert_frame_equal
from predictor import EduPredictor, MODEL_PATH
from schemas import PredictRequest, BatchRequest
from characterization_cases import representative_requests

BASE = "61375e66be256640d87e2a5e8eb3e67f231b7a52"


def original(name):
    return subprocess.check_output(
        ["git", "show", f"{BASE}:deliverable/api/{name}"], cwd=root
    ).decode("utf-8-sig")


class StripMetadata(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        node.returns = None
        return self.generic_visit(node)

    def visit_arg(self, node):
        node.annotation = None
        return node

    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return None
        return self.generic_visit(node)


def normalized_methods(source):
    tree = StripMetadata().visit(ast.parse(source))
    return {
        node.name: ast.dump(node, include_attributes=False)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }


before_methods = normalized_methods(original("predictor.py"))
after_methods = normalized_methods((api / "predictor.py").read_text(encoding="utf-8"))
assert before_methods == after_methods
print(
    f"PASS: all {len(before_methods)} predictor function ASTs identical, excluding annotations/docstrings"
)


def sql_literals(source):
    result = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = " ".join(node.value.split())
            if any(
                term in value
                for term in ("SELECT ", "INSERT INTO ", "UPDATE academic_clocks")
            ):
                result.append(value)
    return Counter(result)


before = sum(
    (sql_literals(original(name)) for name in ("student_data.py", "admin_data.py")),
    Counter(),
)
after = sum(
    (
        sql_literals((api / name).read_text())
        for name in ("student_data.py", "admin_data.py", "prediction_store.py")
    ),
    Counter(),
)
upsert = next(sql for sql in before if sql.startswith("INSERT INTO predictions"))
assert before[upsert] == 2 and after[upsert] == 1
before[upsert] -= 1
assert before == after
print(
    "PASS: all database SQL literals unchanged except deduplicated upsert (whitespace normalized)"
)

baseline_module = types.ModuleType("baseline_predictor")
baseline_module.__file__ = str(api / "predictor.py")
exec(
    compile(original("predictor.py"), "baseline_predictor.py", "exec"),
    baseline_module.__dict__,
)
baseline = baseline_module.EduPredictor()
current = EduPredictor()
cases = list(representative_requests().values())
rng = random.Random(20261006)
demo = cases[0].demographics.model_dump()
for _ in range(100):
    day = rng.choice([0, 1, 30, 60, 90, 150, 240])
    cases.append(
        PredictRequest.model_validate(
            {
                "day_of_course": day,
                "demographics": {
                    **demo,
                    "code_module": rng.choice(
                        ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"]
                    ),
                    "module_total_assessments": rng.randint(1, 12),
                    "course_length": rng.choice([120, 240, 365]),
                },
                "threshold": rng.choice([None, 0.01, 0.41, 0.7, 0.99]),
                "vle_log": [
                    {
                        "date": rng.choice([-1, 0, day // 2, day, day + 1]),
                        "sum_click": rng.randint(0, 500),
                        "activity_type": rng.choice(
                            ["quiz", "forumng", "resource", "other"]
                        ),
                    }
                    for _ in range(rng.randint(0, 15))
                ],
                "assess_log": [
                    {
                        "date_submitted": rng.choice([0, day // 2, day, day + 1]),
                        "score": rng.choice([0, 39, 40, 55, 90, 100]),
                        "date": rng.choice([None, 0, day - 4, day, day + 4]),
                        "assessment_type": rng.choice(["TMA", "CMA", "Exam"]),
                    }
                    for _ in range(rng.randint(0, 8))
                ],
            }
        )
    )
for request in cases:
    left = baseline._build_features(request)
    right = current._build_features(request)
    assert_frame_equal(left, right, check_exact=True, check_categorical=True)
    assert (
        float(baseline.model.predict_proba(left)[0][1]).hex()
        == float(current.model.predict_proba(right)[0][1]).hex()
    )
    assert (
        baseline.predict(request).model_dump() == current.predict(request).model_dump()
    )
batch = BatchRequest.model_validate(
    {
        "students": [
            {"student_id": index, "request": req.model_dump()}
            for index, req in enumerate(cases)
        ]
    }
)
assert (
    baseline.predict_batch(batch).model_dump()
    == current.predict_batch(batch).model_dump()
)
print(
    f"PASS: {len(cases)} original-vs-refactored requests, exact DataFrames, raw probabilities, full responses and batch"
)
print("Model SHA-256:", hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest())
