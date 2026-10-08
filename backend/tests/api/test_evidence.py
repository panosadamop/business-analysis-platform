"""Evidence workspace functionality (specification section 6)."""
from __future__ import annotations

import json

from tests.support import BRIEF_EN, upload

XLSX_UNSUPPORTED = "not really a workbook"

TRANSCRIPT = """[00:12] Client: the invoice list must load in under two seconds.
[00:48] Analyst: who may deactivate an account?
[01:15] Client: that is still open, we confirm next week.
"""


async def test_limits_are_published_before_upload(lead, project):
    response = await lead.get(f"/projects/{project['id']}/sources/limits")
    assert response.status_code == 200
    payload = response.json()
    assert payload["maxDocumentBytes"] > 0
    assert payload["maxRecordingBytes"] > payload["maxDocumentBytes"]
    assert ".docx" in payload["supported"]["documents"]
    assert any("Macros" in note for note in payload["notes"])


async def test_markdown_upload_is_extracted_with_locators(lead, project):
    source = await upload(lead, project["id"], "brief.md", BRIEF_EN)
    assert source["status"] == "ready"
    assert source["chunkCount"] > 0

    content = await lead.get(f"/projects/{project['id']}/sources/{source['id']}/content")
    assert content.status_code == 200
    chunks = content.json()["chunks"]
    assert chunks
    assert all(chunk["locatorKind"] and chunk["locatorValue"] for chunk in chunks)


async def test_greek_content_round_trips(lead, project):
    body = "# Σημειώσεις\n\nΟ χρήστης πρέπει να μπορεί να συνδεθεί."
    source = await upload(lead, project["id"], "notes-el.md", body, kind="meeting_notes")
    content = await lead.get(f"/projects/{project['id']}/sources/{source['id']}/content")
    text = " ".join(chunk["text"] for chunk in content.json()["chunks"])
    assert "πρέπει" in text


async def test_csv_upload_reports_rows_and_columns(lead, project):
    source = await upload(lead, project["id"], "schedule.csv",
                          "Milestone,Date\nDiscovery,2026-02-28\nRelease,2026-05-15\n",
                          kind="schedule")
    assert source["status"] == "ready"
    versions = await lead.get(f"/projects/{project['id']}/sources/{source['id']}/versions")
    meta = versions.json()[0]["meta"]
    assert meta["rows"] == 2
    assert meta["columns"] == ["Milestone", "Date"]


async def test_unsupported_file_fails_actionably_and_is_not_silently_empty(lead, project):
    response = await lead.post(
        f"/projects/{project['id']}/sources",
        files={"file": ("diagram.bin", b"\x00\x01binary", "application/octet-stream")},
        data={"meta": json.dumps({"title": "Binary", "kind": "other"})})
    assert response.status_code == 201
    source = response.json()
    assert source["status"] == "unsupported"

    versions = await lead.get(f"/projects/{project['id']}/sources/{source['id']}/versions")
    reason = versions.json()[0]["failureReason"]
    assert reason and "No extractor" in reason


async def test_image_without_ocr_is_reported_not_guessed(lead, project):
    response = await lead.post(
        f"/projects/{project['id']}/sources",
        files={"file": ("screen.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        data={"meta": json.dumps({"title": "Design screen", "kind": "image"})})
    source = response.json()
    assert source["status"] == "unsupported"
    versions = await lead.get(f"/projects/{project['id']}/sources/{source['id']}/versions")
    assert "OCR" in versions.json()[0]["failureReason"]


async def test_empty_upload_is_rejected(lead, project):
    response = await lead.post(
        f"/projects/{project['id']}/sources",
        files={"file": ("empty.md", b"", "text/markdown")},
        data={"meta": json.dumps({"title": "Empty"})})
    assert response.status_code == 422


async def test_reimport_creates_a_version_and_an_impact_report(lead, project):
    source = await upload(lead, project["id"], "brief.md", BRIEF_EN)
    revised = BRIEF_EN.replace("under 2 seconds", "under 5 seconds")
    await upload(lead, project["id"], "brief.md", revised, document_id=source["id"])

    versions = await lead.get(f"/projects/{project['id']}/sources/{source['id']}/versions")
    numbers = [row["version"] for row in versions.json()]
    assert numbers == [2, 1], "history is preserved, not overwritten"

    impact = await lead.get(f"/projects/{project['id']}/sources/impact")
    assert impact.status_code == 200
    assert len(impact.json()) >= 1


async def test_transcript_attach_and_correction(lead, project):
    source = await upload(lead, project["id"], "kickoff.md", "# Kick off\n\nPlaceholder.",
                          kind="meeting_notes")
    version_id = source["currentVersionId"]

    attached = await lead.post(
        f"/projects/{project['id']}/sources/versions/{version_id}/transcript",
        json={"text": TRANSCRIPT})
    assert attached.status_code == 200
    assert attached.json()["segments"] == 3
    assert "do not imply verified identity" in attached.json()["note"]

    segments = await lead.get(f"/projects/{project['id']}/sources/{source['id']}/transcript")
    assert [segment["speaker"] for segment in segments.json()] == \
        ["Client", "Analyst", "Client"]

    first = segments.json()[0]
    corrected = await lead.patch(f"/projects/{project['id']}/sources/segments/{first['id']}",
                                 json={"text": "corrected wording", "speaker": "Jo"})
    assert corrected.status_code == 200
    assert corrected.json()["corrected"] is True
    assert corrected.json()["speakerVerified"] is False


async def test_bad_transcript_format_is_refused_with_an_example(lead, project):
    source = await upload(lead, project["id"], "x.md", "# X\n\nbody")
    response = await lead.post(
        f"/projects/{project['id']}/sources/versions/{source['currentVersionId']}/transcript",
        json={"text": "no timestamps here at all"})
    assert response.status_code == 422
    assert "[01:23]" in response.json()["error"]["message"]


async def test_restricted_source_is_indicated_not_leaked(lead, project, outsider):
    source = await upload(lead, project["id"], "secret.md",
                          "# Secret\n\nThe system must protect the secret rate card.",
                          classification="restricted")
    await lead.post(f"/projects/{project['id']}/members",
                    json={"email": outsider.user.email, "roles": ["internal_viewer"]})

    listing = await outsider.get(f"/projects/{project['id']}/sources")
    assert listing.status_code == 200
    row = next(item for item in listing.json() if item["id"] == source["id"])
    assert row["accessRestricted"] is True
    assert row["title"] == "Restricted source"

    content = await outsider.get(f"/projects/{project['id']}/sources/{source['id']}/content")
    assert content.json()["accessRestricted"] is True
    assert "chunks" not in content.json()

    download = await outsider.get(f"/projects/{project['id']}/sources/{source['id']}/download")
    assert download.status_code == 403


async def test_original_is_downloadable_by_an_entitled_analyst(lead, project):
    source = await upload(lead, project["id"], "brief.md", BRIEF_EN)
    response = await lead.get(f"/projects/{project['id']}/sources/{source['id']}/download")
    assert response.status_code == 200
    assert b"Customer portal brief" in response.content


async def test_source_can_be_excluded_from_analysis(lead, project):
    source = await upload(lead, project["id"], "old.md", "# Old\n\nThe system must do X.")
    response = await lead.patch(f"/projects/{project['id']}/sources/{source['id']}",
                                json={"excluded": True,
                                      "exclusionReason": "Superseded by the new brief"})
    assert response.status_code == 200
    assert response.json()["excluded"] is True


async def test_search_is_bilingual_and_accent_insensitive(lead, project):
    await upload(lead, project["id"], "brief.md", BRIEF_EN)
    await upload(lead, project["id"], "notes-el.md",
                 "# Σημειώσεις\n\nΟ πελάτης πρέπει να βλέπει τα τιμολόγια.",
                 kind="meeting_notes")

    english = await lead.get(f"/projects/{project['id']}/search", params={"q": "invoice"})
    assert english.status_code == 200
    assert english.json(), "expected an English hit"
    assert english.json()[0]["locatorValue"]

    greek = await lead.get(f"/projects/{project['id']}/search",
                           params={"q": "τιμολογια"})  # unaccented on purpose
    assert greek.json(), "accent folding should match the accented source text"


async def test_search_excludes_sources_the_caller_may_not_read(lead, project, outsider):
    await upload(lead, project["id"], "secret.md",
                 "# Secret\n\nThe confidential margin must stay internal.",
                 classification="restricted")
    await lead.post(f"/projects/{project['id']}/members",
                    json={"email": outsider.user.email, "roles": ["internal_viewer"]})

    hits = await outsider.get(f"/projects/{project['id']}/search", params={"q": "margin"})
    assert hits.json() == []
