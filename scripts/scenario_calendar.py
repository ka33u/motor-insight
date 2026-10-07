"""Synthetic plan dates; these do not certify capacity or delivery feasibility."""
from datetime import timedelta


def work_order_plan(assembly_day,due):
    start=assembly_day-timedelta(days=3)
    end=due-timedelta(days=1)
    # Unstarted demo orders share a fallback assembly day. Preserve their
    # promised deadline and use a three-day planning window if dates invert.
    if start>end:start=end-timedelta(days=3)
    return start,end
