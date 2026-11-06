"""Pure lifecycle projection and legacy-write reconciliation.

The caller must use a current order snapshot and include the returned fields in
its existing transaction. This module neither performs writes nor grants access.
"""

from copy import deepcopy

_STATUS_STAGE = {
    "pending": "placed", "confirmed": "accepted", "accepted": "accepted",
    "packed": "ready", "delivered": "delivered", "completed": "delivered",
    "cancelled": "cancelled", "rejected": "rejected", "removed": "removed",
}
_RANK = {"placed": 0, "accepted": 1, "preparing": 2, "ready": 3}
_ACTIONS = {"placed": "accept", "accepted": "start_preparing", "preparing": "mark_ready"}
_TRANSITIONS = {
    "accept": ("placed", "accepted", "confirmed"),
    "start_preparing": ("accepted", "preparing", "confirmed"),
    "mark_ready": ("preparing", "ready", "packed"),
}


def project(order):
    """Return lifecycle facts, without writing a projection to old orders."""
    lifecycle = order.get("lifecycle")
    if isinstance(lifecycle, dict):
        return deepcopy(lifecycle)
    return {"version": 2, "stage": _STATUS_STAGE.get(order.get("status"), "unknown"),
            "revision": 0, "provenance": "legacy_unknown"}


def native_lifecycle():
    return {"version": 2, "stage": "placed", "revision": 0, "provenance": "native"}


def legacy_patch(order, changes):
    """Reconcile one effective legacy order write against its current snapshot.

    The caller coalesces multiple writes to the same identity within a commit.
    Missing lifecycle is deliberately not migrated. Preserve unknown fields and
    intermediate progress when an old status is less specific.
    """
    if not isinstance(order.get("lifecycle"), dict):
        return dict(changes)
    lifecycle = deepcopy(order["lifecycle"])
    revision = lifecycle.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("Invalid lifecycle revision")
    lifecycle["revision"] = revision + 1
    if "status" in changes:
        mapped = _STATUS_STAGE.get(changes["status"])
        old = lifecycle.get("stage")
        if mapped and (mapped not in _RANK or old not in _RANK or _RANK[mapped] > _RANK[old]):
            lifecycle["stage"] = mapped
    return {**changes, "lifecycle": lifecycle}


def action_for(order):
    return _ACTIONS.get(project(order).get("stage"))


def transition(lifecycle, action):
    """Return the new snapshot and legacy status, or reject a skipped action."""
    spec = _TRANSITIONS.get(action)
    if not spec or lifecycle.get("stage") != spec[0]:
        raise ValueError("Order lifecycle transition is not allowed")
    revision = lifecycle.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("Invalid lifecycle revision")
    updated = deepcopy(lifecycle)
    updated.update(stage=spec[1], revision=revision + 1)
    return updated, spec[2]
