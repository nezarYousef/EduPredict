"""Apply a saved what-if scenario to raw evidence before normal feature engineering."""

from typing import Callable, Optional

from schemas import AssessmentSubmission, PredictRequest, ScenarioEvidence, VLEEvent


def _distributed_clicks(amount: int, days: int, current_day: int) -> list[tuple[int, int]]:
    quotient, remainder = divmod(amount, days)
    return [
        (current_day - index, quotient + (index < remainder))
        for index in range(days)
        if quotient + (index < remainder)
    ]


def apply_scenario(
    base: PredictRequest,
    scenario: ScenarioEvidence,
    enrollment_id: int,
    next_due_date: Callable[[int, str], Optional[int]],
) -> PredictRequest:
    """Return hypothetical logs; the original request and database rows stay untouched."""
    day = base.day_of_course
    inputs = scenario.inputs
    if scenario.based_on_day != day or inputs.activity_days > day + 1:
        raise ValueError("Scenario is based on a different course day")

    vle_log = list(base.vle_log)
    for field, activity_type in (
        ("quiz_clicks", "quiz"),
        ("forum_clicks", "forumng"),
        ("resource_clicks", "resource"),
    ):
        amount = getattr(inputs, field)
        if amount > (day + 1) * 50:
            raise ValueError("Scenario activity exceeds the course limit")
        events = getattr(scenario.activity, field)
        if [(event.date, event.clicks) for event in events] != _distributed_clicks(
            amount, inputs.activity_days, day
        ):
            raise ValueError("Scenario activity does not match saved inputs")
        vle_log.extend(
            VLEEvent(date=event.date, sum_click=event.clicks, activity_type=activity_type)
            for event in events
        )

    assess_log = list(base.assess_log)
    for assessment_type, score_field, delay_field in (
        ("TMA", "latest_tma_score", "tma_delay_days"),
        ("CMA", "latest_cma_score", "cma_delay_days"),
    ):
        score = getattr(inputs, score_field)
        delay = getattr(inputs, delay_field)
        if score is None and delay is None:
            continue
        positions = [
            index for index, item in enumerate(assess_log)
            if item.assessment_type == assessment_type
        ]
        if not positions:
            raise ValueError("Scenario references a missing submitted assessment")
        index = positions[-1]
        original = assess_log[index]
        submitted = original.date_submitted
        if delay is not None:
            if original.date is None or original.date + delay > day:
                raise ValueError("Scenario submission date is invalid")
            submitted = int(original.date) + delay
        assess_log[index] = AssessmentSubmission(
            date_submitted=submitted,
            score=original.score if score is None else score,
            assessment_type=assessment_type,
            date=original.date,
        )

    if inputs.new_submission_score is not None:
        assessment_type = inputs.new_submission_type or "TMA"
        due = next_due_date(enrollment_id, assessment_type)
        if due is None:
            raise ValueError("Scenario references a missing unsubmitted assessment")
        submitted = due + (inputs.new_submission_delay_days or 0)
        if submitted > day:
            raise ValueError("Scenario new submission is after the current day")
        assess_log.append(
            AssessmentSubmission(
                date_submitted=submitted,
                score=inputs.new_submission_score,
                assessment_type=assessment_type,
                date=due,
            )
        )

    assess_log.sort(key=lambda item: item.date_submitted)
    return base.model_copy(update={"vle_log": vle_log, "assess_log": assess_log})
