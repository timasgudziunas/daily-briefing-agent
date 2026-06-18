"""Strict, data-grounded grading (Phase 2).

In the PM run, load this morning's predictions plus any long-horizon ones now
due, and mark each right / wrong / partial with a why — anchored to real
prices/data (from market.py / FRED), never the model's own vibes. A model
grading its own homework must not be lenient.

TODO (Phase 2): implement `grade_predictions(due_predictions, outcomes)`.
"""
