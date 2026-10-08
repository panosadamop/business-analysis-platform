"""Version bound parent approval cascade (specification section 10.2).

Design rules implemented here:

* REQ-APP-01 approving a parent approves the current descendant versions and
  the acceptance criteria and test artifacts those descendants own.
* REQ-APP-02 the approver sees the exact version manifest, counts, blockers,
  estimate totals, the diff against the previous approved bundle and the client
  visible subset before deciding.
* REQ-APP-03 the approver must hold authority over every included descendant;
  artifacts owned by another subtree stay references.
* REQ-APP-04 the decision is logically atomic. A manifest hash pins the exact
  (item, version) set; if anything moved, the submission fails with a refreshed
  diff and nothing is approved.
* REQ-APP-05 the event records explicit versus inherited approval and waivers.
* REQ-APP-06 later changes are not covered; the parent needs renewed approval.
* REQ-APP-07 revocation is evaluated per version and inherited scope.
* REQ-APP-08 publication is separate and only for approved, non revoked versions.
"""
from __future__ import annotations

from typing import Any, Iterable

from app.core.errors import ConflictState, Forbidden, NotFound, VersionConflict
from app.core.utils import stable_hash, utcnow
from app.db.mongo import supports_transactions
from app.models.approval import (ApprovalEvent, ApprovalManifest, ApprovalSubmit,
                                 BlockerView, Decision, ManifestDiff,
                                 ManifestEntry, Waiver)
from app.models.backlog import ArtifactVersion, BacklogItem
from app.models.common import ArtifactState, ItemType, Severity
from app.models.project import Project
from app.repositories import (approval_events, approval_manifests,
                              artifact_versions, backlog_items, estimates,
                              evidence_links, findings, questions,
                              source_documents, source_versions,
                              specifications, test_cases)
from app.services import audit
from app.services.estimation import total_hours


# --- manifest construction --------------------------------------------------

async def _collect_subtree(project_id: str, root_id: str) -> list[BacklogItem]:
    root = await backlog_items.get(root_id, projectId=project_id)
    if not root:
        raise NotFound("Backlog item not found")
    descendants = await backlog_items.list(
        {"projectId": project_id, "path": root_id,
         "state": {"$ne": str(ArtifactState.ARCHIVED)}},
        sort=[("order", 1)])
    return [root] + descendants


async def _versions_for(items: Iterable[BacklogItem]) -> dict[str, ArtifactVersion]:
    ids = [i.current_version_id for i in items if i.current_version_id]
    versions = await artifact_versions.list({"_id": {"$in": ids}})
    return {v.item_id: v for v in versions}


def manifest_hash(entries: list[ManifestEntry]) -> str:
    """Pins the exact version set. Any movement invalidates the submission."""
    return stable_hash(sorted(
        (e.item_id, e.version_id, e.version, e.content_rev, e.reference_only)
        for e in entries))


async def build_manifest(project: Project, root_id: str, *, actor_id: str,
                         actor_is_approver: bool = True) -> ApprovalManifest:
    items = await _collect_subtree(project.id, root_id)
    root = items[0]
    versions = await _versions_for(items)
    subtree_ids = {i.id for i in items}

    entries: list[ManifestEntry] = []
    for item in items:
        version = versions.get(item.id)
        if not version:
            continue
        entries.append(ManifestEntry(
            item_id=item.id, stable_id=item.stable_id, item_type=str(item.type),
            title=version.title, version=version.version, version_id=version.id,
            content_rev=version.rev, state=str(version.state),
            inherited=item.id != root.id,
            owner_subtree_root=root.id,
            previous_approved_version=item.approved_version,
            changed=item.approved_version != version.version,
        ))

    # Owned test artifacts travel with their story. Tests whose story sits in a
    # different subtree are references and never acquire approval here.
    story_ids = [i.id for i in items if i.type == ItemType.STORY]
    tests = await test_cases.list({"projectId": project.id,
                                   "storyId": {"$in": story_ids}}) if story_ids else []
    for test in tests:
        owned = test.story_id in subtree_ids
        entries.append(ManifestEntry(
            item_id=test.id, stable_id=test.stable_id, item_type="test_case",
            title=test.title, version=test.version,
            version_id=f"{test.id}:v{test.version}", content_rev=test.rev,
            state=str(test.state), inherited=True, owner_subtree_root=root.id,
            reference_only=not owned,
        ))

    specs = await specifications.list({"projectId": project.id,
                                       "itemId": {"$in": list(subtree_ids)}})
    for spec in specs:
        entries.append(ManifestEntry(
            item_id=spec.id, stable_id=f"SPEC-{spec.kind}", item_type="specification",
            title=spec.title, version=spec.version,
            version_id=f"{spec.id}:v{spec.version}", content_rev=spec.rev,
            state=str(spec.state), inherited=True, owner_subtree_root=root.id,
        ))

    # Linked artifacts owned elsewhere: cross subtree test links are shown as
    # references so they cannot silently acquire approval.
    cross_links = await test_cases.list(
        {"projectId": project.id, "requirementIds": {"$exists": True},
         "storyId": {"$nin": story_ids}}, limit=200)
    for test in cross_links:
        if any(cid.startswith("AC-") and cid.split("-")[1] in
               {i.stable_id for i in items} for cid in test.criterion_ids):
            entries.append(ManifestEntry(
                item_id=test.id, stable_id=test.stable_id, item_type="test_case",
                title=test.title, version=test.version,
                version_id=f"{test.id}:v{test.version}", content_rev=test.rev,
                state=str(test.state), inherited=True, reference_only=True,
                owner_subtree_root=test.story_id,
            ))

    blockers = await _blockers(project, items, versions, tests)
    previous = await _previous_event(project.id, root_id)
    diff = _diff(previous, entries)
    totals = await _estimate_totals(project.id, items)
    client_visible = [e.item_id for e in entries if not e.reference_only
                      and e.item_type in {"epic", "feature", "story", "specification"}]

    counts: dict[str, int] = {}
    for entry in entries:
        key = entry.item_type if not entry.reference_only else f"{entry.item_type}_reference"
        counts[key] = counts.get(key, 0) + 1

    manifest = ApprovalManifest(
        project_id=project.id, root_id=root.id, root_type=str(root.type),
        root_title=root.title, root_version=root.current_version,
        entries=entries, counts=counts, blockers=blockers, diff=diff,
        estimate_totals=totals, client_visible_entries=client_visible,
        previous_approval_event_id=previous.id if previous else None,
        manifest_hash=manifest_hash(entries), generated_at=utcnow(),
        generated_by=actor_id,
    )
    await approval_manifests.insert(manifest)
    return manifest


async def _previous_event(project_id: str, root_id: str) -> ApprovalEvent | None:
    found = await approval_events.list(
        {"projectId": project_id, "rootId": root_id, "decision": str(Decision.APPROVE),
         "committed": True, "revoked": False},
        sort=[("decidedAt", -1)], limit=1)
    return found[0] if found else None


def _diff(previous: ApprovalEvent | None, entries: list[ManifestEntry]) -> ManifestDiff:
    if not previous:
        return ManifestDiff(added=list(entries))
    before = {e.item_id: e for e in previous.entries}
    after = {e.item_id: e for e in entries}
    added = [e for item_id, e in after.items() if item_id not in before]
    removed = [e for item_id, e in before.items() if item_id not in after]
    changed = [e for item_id, e in after.items()
               if item_id in before
               and (before[item_id].version != e.version
                    or before[item_id].content_rev != e.content_rev)]
    unchanged = len(after) - len(added) - len(changed)
    return ManifestDiff(added=added, removed=removed, changed=changed,
                        unchanged_count=max(unchanged, 0))


async def _estimate_totals(project_id: str, items: list[BacklogItem]) -> dict[str, Any]:
    ids = [i.id for i in items]
    rows = await estimates.list({"projectId": project_id, "itemId": {"$in": ids},
                                 "superseded": False, "isRoughParent": False})
    story_ids = {i.id for i in items if i.type in (ItemType.STORY, ItemType.TASK)}
    hours = round(sum(total_hours(e) for e in rows if e.item_id in story_ids), 2)
    overhead = round(sum(e.overhead_hours for e in rows if e.item_id not in story_ids), 2)
    points = [e.story_points for e in rows if e.story_points is not None
              and e.item_id in story_ids]
    return {
        "unit": "person_hours",
        "detailedHours": round(hours + overhead, 2),
        "overheadHours": overhead,
        "storyPoints": round(sum(points), 2) if points else None,
        "itemsWithEstimate": len({e.item_id for e in rows}),
        "itemsTotal": len(ids),
    }


async def _blockers(project: Project, items: list[BacklogItem],
                    versions: dict[str, ArtifactVersion], tests: list[Any]) -> list[BlockerView]:
    """Critical blockers listed in section 8.2."""
    gates = project.quality_gates
    blockers: list[BlockerView] = []
    item_ids = [i.id for i in items]
    stories = [i for i in items if i.type == ItemType.STORY]

    # 1. invalid hierarchy
    by_id = {i.id: i for i in items}
    for item in items[1:]:
        parent = by_id.get(item.parent_id or "")
        if parent is None and item.parent_id not in (None, ""):
            continue
        if item.type == ItemType.FEATURE and parent and parent.type != ItemType.EPIC:
            blockers.append(BlockerView(kind="invalid_hierarchy", severity=Severity.CRITICAL,
                                        message=f"{item.stable_id} is not under an epic",
                                        target_id=item.id, target_title=item.title,
                                        waivable=False))

    # 2. missing acceptance criteria
    if gates.require_acceptance_criteria:
        for item in items:
            version = versions.get(item.id)
            if version and not version.acceptance_criteria and item.type != ItemType.TASK:
                blockers.append(BlockerView(
                    kind="missing_acceptance_criteria", severity=Severity.CRITICAL,
                    message=f"{item.stable_id} has no acceptance criteria",
                    target_id=item.id, target_title=item.title))

    # 3. untestable mandatory requirements
    if gates.require_tests_for_stories:
        tested = {t.story_id for t in tests}
        for story in stories:
            if story.id not in tested:
                blockers.append(BlockerView(
                    kind="untestable_requirement", severity=Severity.CRITICAL,
                    message=f"{story.stable_id} has no linked test case",
                    target_id=story.id, target_title=story.title))

    # 4. unresolved critical contradictions
    if gates.block_on_unresolved_critical_questions:
        open_questions = await questions.list({
            "projectId": project.id, "status": "open", "severity": str(Severity.CRITICAL),
            "relatedItemIds": {"$in": item_ids}})
        for question in open_questions:
            blockers.append(BlockerView(
                kind="unresolved_critical_question", severity=Severity.CRITICAL,
                message=question.title, target_id=question.id,
                target_title=question.title))

    # 5. open critical findings
    if gates.block_on_critical_findings:
        open_findings = await findings.list({
            "projectId": project.id, "status": "open", "severity": str(Severity.CRITICAL),
            "targetId": {"$in": item_ids}})
        for finding in open_findings:
            blockers.append(BlockerView(
                kind="critical_finding", severity=Severity.CRITICAL,
                message=finding.title, target_id=finding.target_id,
                target_title=finding.title, finding_id=finding.id))

    # 6. inaccessible evidence essential to a claim
    links = await evidence_links.list({"projectId": project.id,
                                       "targetId": {"$in": item_ids}})
    version_ids = {l.source_version_id for l in links if l.source_version_id}
    if version_ids:
        present = await source_versions.list({"_id": {"$in": list(version_ids)}})
        present_ids = {v.id for v in present}
        documents = await source_documents.list(
            {"_id": {"$in": [v.document_id for v in present]}})
        excluded_docs = {d.id for d in documents if d.excluded}
        for link in links:
            if not link.source_version_id:
                continue
            missing = link.source_version_id not in present_ids
            excluded = any(v.id == link.source_version_id and v.document_id in excluded_docs
                           for v in present)
            if missing or excluded:
                blockers.append(BlockerView(
                    kind="inaccessible_evidence", severity=Severity.CRITICAL,
                    message=("The cited evidence is no longer available or has been "
                             "excluded from the project"),
                    target_id=link.target_id))

    # 7. stale artifacts after a source revision
    for item in items:
        if item.stale:
            blockers.append(BlockerView(
                kind="stale_artifact", severity=Severity.MAJOR,
                message=f"{item.stable_id} is marked potentially stale after an "
                        "evidence change and needs review",
                target_id=item.id, target_title=item.title))
    return blockers


# --- decision ---------------------------------------------------------------

async def submit(project: Project, payload: ApprovalSubmit, *, actor_id: str,
                 actor_email: str | None, can_waive: bool) -> ApprovalEvent:
    manifest = await approval_manifests.get(payload.manifest_id, projectId=project.id)
    if not manifest:
        raise NotFound("Approval manifest not found")
    if manifest.manifest_hash != payload.manifest_hash:
        raise VersionConflict("The approval preview is out of date",
                              details={"expected": manifest.manifest_hash})

    # Recompute against live data. Any movement between preview and submission
    # fails the whole operation; no partial approvals are written.
    fresh = await build_manifest(project, manifest.root_id, actor_id=actor_id)
    if fresh.manifest_hash != payload.manifest_hash:
        raise VersionConflict(
            "An item changed while the approval was being submitted. "
            "Nothing was approved; review the refreshed manifest.",
            details={"refreshedManifestId": fresh.id,
                     "refreshedHash": fresh.manifest_hash,
                     "diff": fresh.diff.model_dump(by_alias=True) if fresh.diff else None},
        )

    waivers = _build_waivers(payload, fresh, actor_id, can_waive)
    waived = {(w.blocker_kind, w.target_id) for w in waivers}
    unresolved = [b for b in fresh.blockers
                  if b.severity == Severity.CRITICAL
                  and (b.kind, b.target_id) not in waived]
    if payload.decision == Decision.APPROVE and unresolved:
        raise ConflictState(
            "Critical blockers must be resolved or explicitly waived before approval",
            details={"blockers": [b.model_dump(by_alias=True) for b in unresolved]},
        )

    event = ApprovalEvent(
        project_id=project.id, manifest_id=fresh.id, manifest_hash=fresh.manifest_hash,
        root_id=fresh.root_id, root_type=fresh.root_type, root_version=fresh.root_version,
        decision=payload.decision, decided_by=actor_id, decided_at=utcnow(),
        note=payload.note, entries=fresh.entries, waivers=waivers, committed=False,
    )
    await approval_events.insert(event)

    try:
        if await supports_transactions():
            await _apply_in_transaction(event, fresh)
        else:
            await _apply_sequential(event, fresh)
    except Exception:
        # Nothing is published or treated as approved while committed is False.
        await approval_events.update(event.id, {"committed": False,
                                                "revocationReason": "apply failed"})
        raise

    await approval_events.update(event.id, {"committed": True})
    event.committed = True

    await audit.record(
        "approval.decided", project_id=project.id, actor_id=actor_id,
        actor_email=actor_email, object_type="approvalEvent", object_id=event.id,
        detail={"decision": str(payload.decision), "rootId": fresh.root_id,
                "entries": len(fresh.entries),
                "explicit": sum(1 for e in fresh.entries if not e.inherited),
                "inherited": sum(1 for e in fresh.entries if e.inherited),
                "waivers": [w.model_dump(by_alias=True) for w in waivers],
                "manifestHash": fresh.manifest_hash})
    return event


def _build_waivers(payload: ApprovalSubmit, manifest: ApprovalManifest,
                   actor_id: str, can_waive: bool) -> list[Waiver]:
    if not payload.waivers:
        return []
    if not can_waive:
        raise Forbidden("You do not have permission to waive approval blockers")
    waivers: list[Waiver] = []
    for raw in payload.waivers:
        rationale = (raw.get("rationale") or "").strip()
        if not rationale:
            raise ConflictState("Every waiver requires a recorded rationale")
        kind = raw.get("blockerKind") or raw.get("blocker_kind")
        target = raw.get("targetId") or raw.get("target_id")
        blocker = next((b for b in manifest.blockers
                        if b.kind == kind and b.target_id == target), None)
        if blocker and not blocker.waivable:
            raise ConflictState(f"The blocker '{kind}' cannot be waived",
                                details={"targetId": target})
        waivers.append(Waiver(blocker_kind=kind or "unknown", target_id=target,
                              rationale=rationale, waived_by=actor_id,
                              waived_at=utcnow()))
    return waivers


def _approved_item_updates(entry: ManifestEntry, event: ApprovalEvent) -> dict[str, Any]:
    return {
        "approvedVersion": entry.version,
        "approvedAt": event.decided_at,
        "state": str(ArtifactState.APPROVED),
        "requiresReapproval": False,
    }


async def _apply_sequential(event: ApprovalEvent, manifest: ApprovalManifest) -> None:
    approved = event.decision == Decision.APPROVE
    state = ArtifactState.APPROVED if approved else ArtifactState.REJECTED
    for entry in manifest.entries:
        if entry.reference_only:
            continue
        if entry.item_type in {"epic", "feature", "story", "task"}:
            await artifact_versions.update(entry.version_id, {
                "state": str(state),
                "approvedBy": event.decided_by if approved else None,
                "approvedAt": event.decided_at if approved else None,
                "approvalEventId": event.id,
                "inheritedFromEventId": event.id if entry.inherited else None,
            })
            if approved:
                await backlog_items.update(entry.item_id,
                                           _approved_item_updates(entry, event))
            else:
                await backlog_items.update(entry.item_id,
                                           {"state": str(ArtifactState.REJECTED)})
        elif entry.item_type == "test_case":
            await test_cases.update(entry.item_id, {
                "state": str(state),
                "reviewState": "approved" if approved else "rejected"})
        elif entry.item_type == "specification":
            await specifications.update(entry.item_id, {"state": str(state)})


async def _apply_in_transaction(event: ApprovalEvent, manifest: ApprovalManifest) -> None:
    from app.db.mongo import get_client

    client = get_client()
    async with await client.start_session() as session:
        async with session.start_transaction():
            await _apply_sequential(event, manifest)


async def revoke(project_id: str, event_id: str, *, reason: str, item_ids: list[str],
                 actor_id: str) -> ApprovalEvent:
    """REQ-APP-07 / REQ-APP-08.

    Revocation affects the selected versions and the approval inherited from this
    event. Independently approved versions are evaluated separately, and already
    published items are not deleted; a reconciliation task is raised instead.
    """
    event = await approval_events.get(event_id, projectId=project_id)
    if not event:
        raise NotFound("Approval event not found")
    if event.revoked:
        raise ConflictState("This approval was already revoked")

    targets = [e for e in event.entries
               if not e.reference_only and (not item_ids or e.item_id in item_ids)]
    for entry in targets:
        if entry.item_type in {"epic", "feature", "story", "task"}:
            version = await artifact_versions.get(entry.version_id)
            if version and version.approval_event_id != event.id:
                # Approved independently by another event: left intact.
                continue
            await artifact_versions.update(entry.version_id, {
                "state": str(ArtifactState.DRAFT), "approvedBy": None,
                "approvedAt": None, "approvalEventId": None,
                "inheritedFromEventId": None})
            await backlog_items.update(entry.item_id, {
                "approvedVersion": None, "approvedAt": None,
                "state": str(ArtifactState.DRAFT), "requiresReapproval": True})
        elif entry.item_type == "test_case":
            await test_cases.update(entry.item_id, {"state": str(ArtifactState.DRAFT),
                                                    "reviewState": "pending_review"})
        elif entry.item_type == "specification":
            await specifications.update(entry.item_id, {"state": str(ArtifactState.DRAFT)})

    updated = await approval_events.update(event_id, {
        "revoked": not item_ids, "revokedBy": actor_id, "revokedAt": utcnow(),
        "revocationReason": reason})

    reconciliation = None
    if event.published_targets:
        from app.models.integration import OutboxJob

        from app.repositories import outbox
        reconciliation = OutboxJob(
            project_id=project_id, integration_id=event.published_targets[0],
            kind="reconcile_revocation",
            payload={"approvalEventId": event_id,
                     "itemIds": [e.item_id for e in targets],
                     "reason": reason},
        )
        await outbox.insert(reconciliation)

    await audit.record("approval.revoked", project_id=project_id, actor_id=actor_id,
                       object_type="approvalEvent", object_id=event_id,
                       detail={"reason": reason, "items": len(targets),
                               "reconciliationJobId": reconciliation.id if reconciliation
                               else None})
    return updated


async def approved_versions(project_id: str, item_ids: list[str] | None = None
                            ) -> dict[str, int]:
    """Only approved, non revoked versions may be published (REQ-APP-08)."""
    query: dict[str, Any] = {"projectId": project_id, "approvedVersion": {"$ne": None}}
    if item_ids:
        query["_id"] = {"$in": item_ids}
    items = await backlog_items.list(query)
    return {i.id: i.approved_version for i in items if i.approved_version is not None}


async def pending_count(project_id: str) -> int:
    return await backlog_items.count({
        "projectId": project_id,
        "$or": [{"requiresReapproval": True}, {"approvedVersion": None}],
        "state": {"$nin": [str(ArtifactState.ARCHIVED)]},
    })
