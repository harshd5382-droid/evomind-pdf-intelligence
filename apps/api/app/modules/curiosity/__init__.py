"""Curiosity engine — the agent identifies and pursues its own knowledge gaps.

Predictive Processing (Friston, Clark) frames cognition as continuous
prediction-error minimisation. The agent has a model of the world; it pays
attention to where the model is failing or thin.

For us, "failing or thin" means concretely:

  - **uncovered_concept**: a keyword present in many documents has zero or
    very few questions asked about it
  - **weak_hypothesis**: a hypothesis with little supporting evidence
    relative to its age
  - **low_confidence**: a question that was answered with confidence < 0.6
  - **open_contradiction**: a contradiction the agent never reconciled

Each gap has a curiosity score. The questioner uses these to bias what to
ask next — not all new questions are gap-driven, but a configurable share are.
"""
from app.modules.curiosity.engine import (
    compute_gaps,
    current_gaps,
    seed_gap_questions,
)

__all__ = ["compute_gaps", "current_gaps", "seed_gap_questions"]
