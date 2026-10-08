"""Backlog hierarchy and artifact versioning (sections 9 and 10.1).

Approved versions are immutable. Every content edit produces a new draft
version and marks the ancestor approval bundles as requiring renewal
(REQ-APP-06).
"""
from __future__ import annotations

from typing import Any, Iterable

from app.core.errors import ConflictState, NotFound, ValidationFailed
from app.core.utils import new_id, utcnow
from app.models.backlog import (AcceptanceCriterion, ArtifactVersion,
                                BacklogItem, BacklogItemCreate,
                                BacklogItemUpdate, BacklogNode)
from app.models.common import (ITEM_PARENT, ArtifactState, ExecutionStatus,
                               ItemType, Priority)
from app.repositories import (artifact_versions, backlog_items,
                              dependency_links, estimates, questions,
                              test_cases)
from app.services import audit

TYPE_PREFIX = {
    ItemType.EPIC: "EPIC",
    ItemType.FEATURE: "FEAT",
    ItemType.STORY: "STORY",
    ItemType.TASK: "TASK",
}

CONTENT_FIELDS = {
    "title", "description", "actor", "need", "benefit", "scope_exclusions",
    "business_rules", "acceptance_criteria", "functional_notes", "technical_notes",
    "nfr_notes", "assumptions", "risk_drivers", "requirement_ids", "citations",
}
ITEM_FIELDS = {
    "priority", "owner_id", "labels", "iteration_id", "release", "kanban_column",
    "blocked_reason", "execution_status",
}
#: Item fields an update may clear by sending null explicitly.
CLEARABLE_ITEM_FIELDS = {"blocked_reason"}


async def next_stable_id(project_id: str, item_type: ItemType) -> str:
    prefix = TYPE_PREFIX[item_type]
    count = await backlog_items.count({"projectId": project_id, "type": str(item_type)})
    for attempt in range(count + 1, count + 50):
        candidate = f"{prefix}-{attempt:03d}"
        if not await backlog_items.exists({"projectId": project_id, "stableId": candidate}):
            return candidate
    return f"{prefix}-{new_id()[:6].upper()}"


async def _validate_parent(project_id: str, item_type: ItemType,
                           parent_id: str | None) -> BacklogItem | None:
    expected = ITEM_PARENT[item_type]
    if expected is None:
        if parent_id:
            raise ValidationFailed(f"A {item_type} cannot have a parent")
        return None
    if not parent_id:
        raise ValidationFailed(f"A {item_type} requires a {expected} parent")
    parent = await backlog_items.get(parent_id, projectId=project_id)
    if not parent:
        raise NotFound("Parent item not found")
    if parent.type != expected:
        raise ValidationFailed(
            f"A {item_type} must sit under a {expected}, not a {parent.type}")
    return parent


async def create_item(project_id: str, payload: BacklogItemCreate, *, actor_id: str,
                      generated_by_role: str | None = None,
                      model_id: str | None = None) -> tuple[BacklogItem, ArtifactVersion]:
    item_type = ItemType(payload.type)
    parent = await _validate_parent(project_id, item_type, payload.parent_id)
    stable_id = await next_stable_id(project_id, item_type)
    order = await backlog_items.count({"projectId": project_id,
                                       "parentId": payload.parent_id})

    item = BacklogItem(
        project_id=project_id, stable_id=stable_id, type=item_type,
        parent_id=payload.parent_id,
        path=(parent.path + [parent.id]) if parent else [],
        order=float(order), title=payload.title, owner_id=payload.owner_id,
        priority=Priority(payload.priority), labels=payload.labels,
        current_version=1, state=ArtifactState.DRAFT,
    )
    version = ArtifactVersion(
        project_id=project_id, item_id=item.id, item_type=item_type, version=1,
        title=payload.title, actor=payload.actor, need=payload.need,
        benefit=payload.benefit, description=payload.description,
        acceptance_criteria=[
            AcceptanceCriterion(id=f"AC-{stable_id}-{index:02d}", text=text,
                                outcome_level=item_type in (ItemType.EPIC, ItemType.FEATURE))
            for index, text in enumerate(payload.acceptance_criteria, start=1)
        ],
        requirement_ids=payload.requirement_ids,
        author_id=actor_id, generated_by_role=generated_by_role, model_id=model_id,
    )
    item.current_version_id = version.id
    await artifact_versions.insert(version)
    await backlog_items.insert(item)
    await _mark_ancestors_for_reapproval(project_id, item.path)
    await audit.record("backlog.created", project_id=project_id, actor_id=actor_id,
                       object_type="backlogItem", object_id=item.id, object_version=1,
                       detail={"stableId": stable_id, "type": str(item_type)})
    return item, version


async def current_version(item: BacklogItem) -> ArtifactVersion:
    if item.current_version_id:
        version = await artifact_versions.get(item.current_version_id)
        if version:
            return version
    found = await artifact_versions.list({"itemId": item.id}, sort=[("version", -1)], limit=1)
    if not found:
        raise NotFound(f"No version stored for item {item.stable_id}")
    return found[0]


async def update_item(project_id: str, item_id: str, payload: BacklogItemUpdate, *,
                      actor_id: str) -> tuple[BacklogItem, ArtifactVersion]:
    item = await backlog_items.get(item_id, projectId=project_id)
    if not item:
        raise NotFound("Backlog item not found")
    if payload.expected_rev is not None and payload.expected_rev != item.rev:
        raise ConflictState("The item changed while you were editing it",
                            details={"currentRev": item.rev})

    data = payload.model_dump(exclude_unset=True, by_alias=False)
    content_changes = {k: v for k, v in data.items() if k in CONTENT_FIELDS and v is not None}
    item_changes = {k: v for k, v in data.items() if k in ITEM_FIELDS
                    and (v is not None or k in CLEARABLE_ITEM_FIELDS)}

    version = await current_version(item)
    new_version = version

    if content_changes:
        if version.state == ArtifactState.APPROVED:
            # Approved versions are immutable: branch a new draft instead.
            new_version = _clone_version(version, item.current_version + 1)
        else:
            new_version = _clone_version(version, version.version)
            new_version.id = version.id
        for key, value in content_changes.items():
            setattr(new_version, key, value)
        new_version.state = ArtifactState.DRAFT
        new_version.author_id = actor_id
        new_version.change_note = payload.change_note
        new_version.approved_by = None
        new_version.approved_at = None
        new_version.approval_event_id = None
        new_version.inherited_from_event_id = None

        if new_version.id == version.id:
            await artifact_versions.replace(new_version)
        else:
            await artifact_versions.insert(new_version)
            await artifact_versions.update(version.id, {
                "state": str(ArtifactState.SUPERSEDED), "supersededAt": utcnow()})
            item_changes["currentVersion"] = new_version.version
        item_changes["currentVersionId"] = new_version.id
        item_changes["title"] = new_version.title
        item_changes["state"] = str(ArtifactState.DRAFT)
        if item.approved_version is not None:
            item_changes["requiresReapproval"] = True
        item_changes["stale"] = False

    if not content_changes and not item_changes:
        return item, version

    if "execution_status" in data and data["execution_status"]:
        await _record_status_change(project_id, item, data["execution_status"], actor_id,
                                    column=data.get("kanban_column") or item.kanban_column)

    normalized = {_camel(k): v for k, v in item_changes.items()}
    updated = await backlog_items.update(item_id, normalized, projectId=project_id)

    if content_changes:
        await _mark_ancestors_for_reapproval(project_id, item.path)
    await audit.record("backlog.updated", project_id=project_id, actor_id=actor_id,
                       object_type="backlogItem", object_id=item_id,
                       object_version=updated.current_version,
                       detail={"contentChanged": bool(content_changes),
                               "fields": sorted(content_changes) + sorted(item_changes)})
    return updated, new_version


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def _clone_version(version: ArtifactVersion, number: int) -> ArtifactVersion:
    data = version.model_dump(by_alias=False)
    data.pop("id", None)
    data["version"] = number
    data["rev"] = 0
    data["created_at"] = utcnow()
    data["updated_at"] = utcnow()
    return ArtifactVersion(**data)


async def _record_status_change(project_id: str, item: BacklogItem, to_status: str,
                                actor_id: str, *, column: str | None = None) -> None:
    from app.models.planning import StatusEvent
    from app.repositories import status_events

    if str(item.execution_status) == str(to_status):
        return
    await status_events.insert(StatusEvent(
        project_id=project_id, item_id=item.id, from_status=str(item.execution_status),
        to_status=str(to_status), at=utcnow(), actor_id=actor_id,
        column=column,
    ))


async def _mark_ancestors_for_reapproval(project_id: str, path: Iterable[str]) -> None:
    ancestor_ids = [a for a in path]
    if not ancestor_ids:
        return
    await backlog_items.raw_update(
        {"_id": {"$in": ancestor_ids}, "approvedVersion": {"$ne": None}},
        {"$set": {"requiresReapproval": True, "updatedAt": utcnow()}},
    )


async def subtree(project_id: str, root_id: str, *,
                  include_root: bool = True) -> list[BacklogItem]:
    """All descendants of a root, resolved through the materialised path."""
    items = await backlog_items.list(
        {"projectId": project_id, "path": root_id}, sort=[("order", 1)])
    if include_root:
        root = await backlog_items.get(root_id, projectId=project_id)
        if root:
            items = [root] + items
    return items


async def tree(project_id: str, *, root_id: str | None = None,
               include_metrics: bool = True) -> list[BacklogNode]:
    query: dict[str, Any] = {"projectId": project_id}
    items = await backlog_items.list(query, sort=[("order", 1)])
    if not items:
        return []

    counts_by_item: dict[str, dict[str, int]] = {}
    hours_by_item: dict[str, float] = {}
    points_by_item: dict[str, float | None] = {}
    if include_metrics:
        test_rows = await test_cases.aggregate([
            {"$match": {"projectId": project_id}},
            {"$group": {"_id": "$storyId", "n": {"$sum": 1}}},
        ])
        test_counts = {row["_id"]: row["n"] for row in test_rows if row["_id"]}
        question_rows = await questions.aggregate([
            {"$match": {"projectId": project_id, "status": "open"}},
            {"$unwind": "$relatedItemIds"},
            {"$group": {"_id": "$relatedItemIds", "n": {"$sum": 1}}},
        ])
        question_counts = {row["_id"]: row["n"] for row in question_rows}
        estimate_rows = await estimates.list({"projectId": project_id, "superseded": False,
                                              "isRoughParent": False})
        for estimate in estimate_rows:
            total = sum(r.hours for r in estimate.role_efforts) + estimate.overhead_hours
            hours_by_item[estimate.item_id] = hours_by_item.get(estimate.item_id, 0.0) + total
            if estimate.story_points is not None:
                points_by_item[estimate.item_id] = estimate.story_points
    else:
        test_counts, question_counts = {}, {}

    versions = await artifact_versions.list(
        {"itemId": {"$in": [i.id for i in items]}}, sort=[("version", -1)])
    version_by_item: dict[str, Any] = {}
    for version in versions:
        version_by_item.setdefault(version.item_id, version)

    nodes: dict[str, BacklogNode] = {}
    for item in items:
        version = version_by_item.get(item.id)
        nodes[item.id] = BacklogNode(
            id=item.id, stable_id=item.stable_id, type=str(item.type),
            parent_id=item.parent_id, title=item.title, state=str(item.state),
            execution_status=str(item.execution_status), priority=str(item.priority),
            current_version=item.current_version, approved_version=item.approved_version,
            requires_reapproval=item.requires_reapproval, stale=item.stale,
            owner_id=item.owner_id,
            story_points=points_by_item.get(item.id),
            effort_hours=round(hours_by_item.get(item.id, 0.0), 2),
            criteria_count=len(version.acceptance_criteria) if version else 0,
            test_count=test_counts.get(item.id, 0),
            open_question_count=question_counts.get(item.id, 0),
        )
        counts_by_item[item.id] = {}

    roots: list[BacklogNode] = []
    for item in items:
        node = nodes[item.id]
        if item.parent_id and item.parent_id in nodes:
            nodes[item.parent_id].children.append(node)
        else:
            roots.append(node)

    def rollup(node: BacklogNode) -> float:
        total = node.effort_hours + sum(rollup(child) for child in node.children)
        node.rollup_hours = round(total, 2)
        return total

    for node in roots:
        rollup(node)

    if root_id:
        return [nodes[root_id]] if root_id in nodes else []
    return roots


async def detect_dependency_cycles(project_id: str) -> list[list[str]]:
    """REQ-PLAN-04 — report dependency cycles instead of silently accepting them."""
    links = await dependency_links.list({"projectId": project_id, "kind": "blocks"})
    graph: dict[str, list[str]] = {}
    for link in links:
        graph.setdefault(link.from_id, []).append(link.to_id)

    cycles: list[list[str]] = []
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for neighbour in graph.get(node, []):
            if state.get(neighbour, 0) == 0:
                visit(neighbour)
            elif state.get(neighbour) == 1:
                index = stack.index(neighbour)
                cycles.append(stack[index:] + [neighbour])
        stack.pop()
        state[node] = 2

    for node in list(graph):
        if state.get(node, 0) == 0:
            visit(node)
    return cycles


async def move_item(project_id: str, item_id: str, *, parent_id: str | None,
                    order: float, actor_id: str) -> BacklogItem:
    item = await backlog_items.require(item_id, projectId=project_id)
    parent = await _validate_parent(project_id, ItemType(item.type), parent_id)
    if parent and (item.id == parent.id or item.id in parent.path):
        raise ValidationFailed("An item cannot be moved under its own descendant")
    new_path = (parent.path + [parent.id]) if parent else []
    descendants = await subtree(project_id, item_id, include_root=False)
    await backlog_items.update(item_id, {"parentId": parent_id, "path": new_path,
                                         "order": order}, projectId=project_id)
    for descendant in descendants:
        suffix = descendant.path[descendant.path.index(item_id):]
        await backlog_items.update(descendant.id, {"path": new_path + suffix})
    await audit.record("backlog.moved", project_id=project_id, actor_id=actor_id,
                       object_type="backlogItem", object_id=item_id,
                       detail={"parentId": parent_id})
    return await backlog_items.require(item_id, projectId=project_id)


async def delete_item(project_id: str, item_id: str, *, actor_id: str) -> int:
    """Archive an item and its subtree. Approved history remains retrievable."""
    items = await subtree(project_id, item_id)
    ids = [i.id for i in items]
    await backlog_items.raw_update({"_id": {"$in": ids}}, {
        "$set": {"state": str(ArtifactState.ARCHIVED),
                 "executionStatus": str(ExecutionStatus.CANCELLED),
                 "updatedAt": utcnow()}})
    await audit.record("backlog.archived", project_id=project_id, actor_id=actor_id,
                       object_type="backlogItem", object_id=item_id,
                       detail={"archivedCount": len(ids)})
    return len(ids)
