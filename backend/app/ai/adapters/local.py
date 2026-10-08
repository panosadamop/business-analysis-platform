"""Local model adapters.

``LocalHttpAdapter`` talks to a company hosted inference server exposing an
OpenAI compatible ``/chat/completions`` endpoint (llama.cpp, vLLM, Ollama).

``HeuristicLocalAdapter`` is the deterministic, dependency free analyst used
when no inference server is deployed and in tests. It is a transparent rule
based baseline: it extracts requirement candidates, questions and a backlog
skeleton from the evidence with real citations, and it labels everything it
infers. It never invents confirmed client decisions or source references.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass
from typing import Any

import httpx

from app.ai.adapters.base import (AdapterRequest, AdapterResponse,
                                  AdapterUnavailable, ModelAdapter,
                                  ModelCapabilities)
from app.core.config import settings
from app.services.search import tokenize

CHUNK_RE = re.compile(
    r"<<CHUNK src=(?P<src>[^\s]+) kind=(?P<kind>[^\s]+) loc=(?P<loc>[^>]*)>>\n(?P<text>.*?)(?=\n<<CHUNK |\Z)",
    re.DOTALL)

MODALS = re.compile(
    r"(?i)\b(must|shall|should|needs? to|has to|is required to|will be able to|"
    r"πρέπει|θα πρέπει|απαιτείται|χρειάζεται|να μπορεί)\b")
GOAL_WORDS = re.compile(r"(?i)\b(goal|objective|aim|purpose|στόχος|σκοπός)\b")
RULE_WORDS = re.compile(r"(?i)\b(if|when|unless|only if|rule|εφόσον|όταν|κανόνας|εάν)\b")
QUESTION_WORDS = re.compile(
    r"(?i)(\?|\btbd\b|\btbc\b|unclear|unknown|to be (defined|confirmed)|"
    r"ασαφ|διευκριν|εκκρεμ)")
STAKEHOLDER_WORDS = re.compile(
    r"(?i)\b(administrator|admin|analyst|manager|client|customer|user|reviewer|"
    r"operator|χρήστης|πελάτης|διαχειριστής|αναλυτής)\b")
NFR_WORDS = re.compile(
    r"(?i)\b(performance|availability|scalab|security|latency|throughput|uptime|"
    r"backup|recovery|retention|accessib|απόδοση|διαθεσιμότητα|ασφάλεια)\b")
INTEGRATION_WORDS = re.compile(
    r"(?i)\b(jira|azure devops|asana|api|integration|webhook|sso|oidc|ldap|"
    r"erp|crm|export|import|ολοκλήρωση|διασύνδεση)\b")
NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(%|ms|s|sec|min|hours?|days?|gb|mb|users?)?\b")
PERMISSION_WORDS = re.compile(
    r"(?i)\b(permission|role|access|authoris|authoriz|restrict|δικαίωμα|πρόσβαση)\b")
FEEDBACK_WORDS = re.compile(
    r"(?i)(error|fail|invalid|reject|denied|refus|not allowed|message|warn|confirm|"
    r"σφάλμα|μήνυμα|απόρριψ|επιβεβαί)")
REFUSAL_WORDS = re.compile(r"(?i)(denied|refus|not allowed|forbidden|απαγορ|άρνηση)")
UX_WORDS = re.compile(
    r"(?i)\b(accessib|usab|mobile|responsive|screen reader|keyboard|easy to|intuitive|"
    r"greek|english|language|προσβασιμ|ευχρηστ|κινητ|γλώσσα)")
PERSONAL_WORDS = re.compile(
    r"(?i)\b(e-?mail|phone|address|birth|tax|vat|iban|passport|identity|"
    r"τηλέφωνο|διεύθυνση|ΑΦΜ|ταυτότητα|γέννησης)")
RETENTION_WORDS = re.compile(
    r"(?i)(retain|retention|keep for|kept for|delete after|purge|archiv|"
    r"διατήρηση|διαγραφή|αρχειοθέτ)")
METRIC_WORDS = re.compile(
    r"(?i)\b(report|dashboard|kpi|metric|average|total|count|rate|percentage|"
    r"statistic|ποσοστό|αναφορά|σύνολο|μέσος)")
MIGRATION_WORDS = re.compile(
    r"(?i)(migrat|legacy|existing system|current system|import from|spreadsheet|excel|"
    r"μετάπτωση|υφιστάμεν|παλαιό σύστημα)")

SENTENCE_SPLIT = re.compile(r"(?<=[.;!?·])\s+|\n")
PROSE_SPLIT = re.compile(r"(?<=[.;!?·])\s+")

#: Chunks that hold table cells or structured paths rather than prose; their
#: column headers are not domain entities.
TABULAR_KINDS = {"row", "cell_range", "table", "schema_path"}

#: The same kind of person named in English or Greek, keyed by one canonical
#: English name, with the Greek name used when the output language is Greek.
PERSONA_KINDS: dict[str, tuple[str, str, set[str]]] = {
    "customer": ("Customer", "Πελάτης", {"customer", "client", "πελάτης", "πελάτη"}),
    "administrator": ("Administrator", "Διαχειριστής",
                      {"administrator", "admin", "διαχειριστής", "διαχειριστή"}),
    "user": ("User", "Χρήστης", {"user", "χρήστης", "χρήστη"}),
    "manager": ("Manager", "Υπεύθυνος", {"manager"}),
    "operator": ("Operator", "Χειριστής", {"operator"}),
    "reviewer": ("Reviewer", "Αξιολογητής", {"reviewer"}),
}

#: Nouns that follow an article or determiner, used to find candidate entities.
DETERMINER_NOUN = re.compile(
    r"(?i)\b(?:a|an|the|each|every|their|its|ο|η|το|τον|την|του|της|κάθε)\s+"
    r"([a-zα-ωάέήίόύώϊϋΐΰ]{4,})\b")
NOT_ENTITIES = {
    "system", "portal", "application", "first", "last", "same", "following", "goal",
    "release", "figures", "list", "need", "brief", "notes", "σύστημα", "στόχος",
}


@dataclass
class ParsedChunk:
    source_version_id: str
    kind: str
    locator: str
    text: str


def parse_context(context: str) -> list[ParsedChunk]:
    return [
        ParsedChunk(source_version_id=m.group("src"), kind=m.group("kind"),
                    locator=m.group("loc").strip(), text=m.group("text").strip())
        for m in CHUNK_RE.finditer(context)
    ]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT.split(text) if len(s.strip()) > 12]


def _prose_sentences(text: str) -> list[str]:
    """Whole sentences, joining lines that a document wrapped mid sentence."""
    paragraphs = re.split(r"\n\s*\n", text)
    out: list[str] = []
    for paragraph in paragraphs:
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        # Headings and list items stand alone; wrapped prose lines are joined.
        joined: list[str] = []
        for line in lines:
            if line.startswith(("#", "-", "*", "•")) or not joined:
                joined.append(line.lstrip("#-*• ").strip())
            else:
                joined[-1] = f"{joined[-1]} {line}"
        for block in joined:
            out += [s.strip() for s in PROSE_SPLIT.split(block) if len(s.strip()) > 12]
    return out


def _citation(chunk: ParsedChunk, quote: str | None = None) -> dict[str, Any]:
    return {
        "sourceVersionId": chunk.source_version_id,
        "locatorKind": chunk.kind,
        "locatorValue": chunk.locator,
        "quote": (quote or chunk.text)[:280],
    }


def _title_from(sentence: str, limit: int = 90) -> str:
    cleaned = re.sub(r"\s+", " ", sentence).strip(" -•*\t")
    cleaned = re.sub(r"^(the system|to system|το σύστημα)\s+", "", cleaned, flags=re.I)
    if len(cleaned) <= limit:
        return cleaned.rstrip(".")
    return cleaned[:limit].rsplit(" ", 1)[0] + "…"


def _topic_of(text: str, fallback: str = "general") -> str:
    tokens = [t for t in tokenize(text) if len(t) > 3]
    if not tokens:
        return fallback
    return Counter(tokens).most_common(1)[0][0]


class HeuristicLocalAdapter(ModelAdapter):
    """Deterministic analyst. Same evidence in, same analysis out."""

    deployment = "local"
    model_id = "local/heuristic-analyst-1"

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(name=self.model_id, deployment="local",
                                 context_tokens=1_000_000, supports_json_schema=True)

    async def health(self) -> tuple[bool, str]:
        return True, "Deterministic local analyst is always available"

    async def generate(self, request: AdapterRequest) -> AdapterResponse:
        started = time.perf_counter()
        chunks = parse_context(request.context)
        if request.role == "business_analyst":
            payload = self._business_analysis(chunks, request.language)
        elif request.role == "ux_analyst":
            payload = self._ux_review(chunks, request)
        elif request.role == "data_analyst":
            payload = self._data_review(chunks, request)
        elif request.role == "technical_analyst":
            payload = self._technical_review(chunks, request)
        elif request.role == "qa_analyst":
            payload = self._qa_review(chunks, request)
        else:  # pragma: no cover - guarded by the orchestrator
            raise AdapterUnavailable(f"Unknown analyst role {request.role}")
        latency = int((time.perf_counter() - started) * 1000)
        return AdapterResponse(
            payload=payload, model_id=self.model_id, deployment="local",
            prompt_tokens=len(request.context) // 4,
            completion_tokens=len(json.dumps(payload)) // 4,
            latency_ms=latency,
        )

    # --- business analyst ---------------------------------------------------
    def _business_analysis(self, chunks: list[ParsedChunk], language: str) -> dict[str, Any]:
        requirements: list[dict[str, Any]] = []
        rules: list[dict[str, Any]] = []
        questions: list[dict[str, Any]] = []
        goals: list[str] = []
        stakeholders: Counter[str] = Counter()
        glossary: OrderedDict[str, dict[str, Any]] = OrderedDict()
        seen_statements: set[str] = set()

        for chunk in chunks:
            for sentence in _sentences(chunk.text):
                normalized = re.sub(r"\s+", " ", sentence.lower())[:160]
                if GOAL_WORDS.search(sentence) and len(goals) < 12:
                    goals.append(_title_from(sentence, 140))
                for match in STAKEHOLDER_WORDS.finditer(sentence):
                    stakeholders[match.group(0).lower()] += 1

                if QUESTION_WORDS.search(sentence):
                    severity = "critical" if re.search(
                        r"(?i)(tbd|tbc|unknown|conflict|αντίφαση)", sentence) else "major"
                    questions.append({
                        "title": _title_from(sentence),
                        "detail": sentence.strip(),
                        "kind": "ambiguity",
                        "severity": severity,
                        "proposedClarification": (
                            "Confirm the intended behaviour and record the decision with "
                            "its owner and date."),
                        "citations": [_citation(chunk, sentence)],
                    })
                    continue

                if MODALS.search(sentence) and normalized not in seen_statements:
                    seen_statements.add(normalized)
                    is_rule = bool(RULE_WORDS.search(sentence))
                    is_nfr = bool(NFR_WORDS.search(sentence))
                    entry = {
                        "title": _title_from(sentence),
                        "statement": sentence.strip(),
                        "type": ("non_functional" if is_nfr else
                                 "business_rule" if is_rule else "business"),
                        "priority": "high" if re.search(r"(?i)\b(must|shall|πρέπει)\b",
                                                        sentence) else "medium",
                        # Derived from evidence, but the wording is a proposal.
                        "provenance": "ai_suggestion",
                        "confidence": 0.6 if is_nfr else 0.7,
                        "rationale": "Derived from a modal obligation in the evidence.",
                        "citations": [_citation(chunk, sentence)],
                    }
                    (rules if is_rule else requirements).append(entry)

            for term in self._glossary_candidates(chunk.text):
                if term.lower() not in glossary and len(glossary) < 40:
                    glossary[term.lower()] = {
                        "term": term,
                        "definition": "Appears repeatedly in the evidence; confirm the "
                                      "agreed definition with the client.",
                        "language": language,
                        "citations": [_citation(chunk)],
                    }

        if not requirements and chunks:
            questions.append({
                "title": "No obligation wording was found in the evidence",
                "detail": ("The supplied sources contain no 'must/shall/πρέπει' style "
                           "statements, so no requirement could be derived. Confirm "
                           "whether the right documents were uploaded."),
                "kind": "missing_rule",
                "severity": "critical",
                "proposedClarification": "Provide the brief or specification that states "
                                         "the required behaviour.",
                "citations": [_citation(chunks[0])],
            })

        epics = self._build_hierarchy(requirements, rules)
        summary = (f"Derived {len(requirements)} requirement candidates, {len(rules)} "
                   f"business rules and {len(questions)} open questions from "
                   f"{len(chunks)} evidence excerpts.")
        return {
            "schemaVersion": "1.0",
            "summary": summary,
            "goals": goals[:10],
            "stakeholders": [s for s, _ in stakeholders.most_common(10)],
            "scopeBoundaries": [],
            "glossary": list(glossary.values()),
            "businessRules": rules,
            "requirements": requirements,
            "questions": questions[:60],
            "epics": epics,
            "functionalSpecification": self._functional_spec(requirements, rules, epics),
        }

    def _glossary_candidates(self, text: str) -> list[str]:
        words = re.findall(r"\b[A-ZΑ-Ω][\wΑ-Ωα-ω]{3,}(?:\s+[A-ZΑ-Ω][\wΑ-Ωα-ω]{3,})?\b", text)
        counts = Counter(w for w in words if not w.isupper())
        return [w for w, n in counts.items() if n >= 2][:5]

    def _build_hierarchy(self, requirements: list[dict[str, Any]],
                         rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Group requirement candidates into epics, features and stories."""
        if not requirements:
            return []
        grouped: dict[str, list[dict[str, Any]]] = {}
        for requirement in requirements:
            topic = _topic_of(requirement["statement"])
            grouped.setdefault(topic, []).append(requirement)

        ordered = sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True)[:6]
        epics: list[dict[str, Any]] = []
        for topic, group in ordered:
            features: list[dict[str, Any]] = []
            for index in range(0, len(group), 4):
                batch = group[index:index + 4]
                stories = [self._story_from(r, rules) for r in batch]
                features.append({
                    "title": f"{topic.capitalize()} capability {index // 4 + 1}",
                    "description": ("Groups related requirement candidates for "
                                    f"'{topic}'. Grouping is a proposal for review."),
                    "acceptanceCriteria": [{
                        "text": (f"All '{topic}' stories in this feature are approved and "
                                 "their acceptance criteria are demonstrably met."),
                        "outcomeLevel": True,
                    }],
                    "stories": stories,
                })
            epics.append({
                "title": f"{topic.capitalize()}",
                "description": (f"Outcome area derived from {len(group)} requirement "
                                "candidates sharing this topic."),
                "acceptanceCriteria": [{
                    "text": (f"The {topic} outcome is validated end to end, not only by "
                             "completion of the child stories."),
                    "outcomeLevel": True,
                }],
                "features": features,
            })
        return epics

    def _story_from(self, requirement: dict[str, Any],
                    rules: list[dict[str, Any]]) -> dict[str, Any]:
        statement = requirement["statement"]
        actor_match = STAKEHOLDER_WORDS.search(statement)
        actor = actor_match.group(0).lower() if actor_match else "user"
        criteria = [{
            "text": f"Given a valid context, when the flow runs, then {_title_from(statement, 140)}.",
            "outcomeLevel": False,
        }]
        if PERMISSION_WORDS.search(statement):
            criteria.append({
                "text": ("A user without the required permission is denied and no "
                         "restricted content is returned."),
                "outcomeLevel": False,
            })
        numbers = NUMBER_RE.findall(statement)
        if numbers:
            criteria.append({
                "text": ("Values at the stated boundary are accepted and values beyond "
                         "it are rejected with an actionable message."),
                "outcomeLevel": False,
            })
        related_rules = [r["statement"] for r in rules
                         if _topic_of(r["statement"]) == _topic_of(statement)][:3]
        return {
            "title": _title_from(statement),
            "actor": actor,
            "need": _title_from(statement, 120),
            "benefit": "the agreed business outcome is achieved",
            "description": statement,
            "acceptanceCriteria": criteria,
            "businessRules": related_rules,
            "assumptions": ["Decomposition and wording are proposals pending analyst review."],
            "citations": requirement.get("citations", []),
            "provenance": "ai_suggestion",
            "estimateHintHours": 8.0 + 4.0 * len(criteria),
            "storyPointsHint": float(min(13, 2 * len(criteria) + 1)),
            "riskDrivers": (["external integration"] if INTEGRATION_WORDS.search(statement)
                            else []),
        }

    def _functional_spec(self, requirements: list[dict[str, Any]],
                         rules: list[dict[str, Any]],
                         epics: list[dict[str, Any]]) -> str:
        lines = ["# Functional specification (draft)", "",
                 "## Scope", "",
                 f"Derived from {len(requirements)} requirement candidates across "
                 f"{len(epics)} outcome areas. Every statement below is a proposal "
                 "pending analyst review and human approval.", "",
                 "## Actors", ""]
        actors = sorted({(STAKEHOLDER_WORDS.search(r["statement"]) or [None])
                         and STAKEHOLDER_WORDS.search(r["statement"]).group(0).lower()
                         for r in requirements
                         if STAKEHOLDER_WORDS.search(r["statement"])})
        lines += [f"- {a}" for a in actors if a] or ["- Not stated in the evidence"]
        lines += ["", "## Flows", ""]
        for epic in epics:
            lines.append(f"### {epic['title']}")
            for feature in epic["features"]:
                lines.append(f"- **{feature['title']}**")
                for story in feature["stories"]:
                    lines.append(f"  - {story['title']}")
            lines.append("")
        lines += ["## Business rules", ""]
        lines += [f"- {r['statement']}" for r in rules[:40]] or ["- None identified"]
        lines += ["", "## Validations and exceptions", "",
                  "- Validation and error behaviour is not fully stated in the evidence "
                  "and is raised as open questions."]
        return "\n".join(lines)

    # --- technical analyst --------------------------------------------------
    def _technical_review(self, chunks: list[ParsedChunk],
                          request: AdapterRequest) -> dict[str, Any]:
        stories = _stories_from_instruction(request.instruction)
        findings: list[dict[str, Any]] = []
        dependencies: list[dict[str, Any]] = []
        effort_drivers: list[dict[str, Any]] = []
        nfrs: list[dict[str, Any]] = []
        technical_notes: dict[str, str] = {}

        for story in stories:
            text = f"{story.get('title', '')} {story.get('description', '')}"
            stable_id = story.get("stableId")
            if NFR_WORDS.search(text) and not NUMBER_RE.search(text):
                findings.append({
                    "title": f"{stable_id}: non functional expectation without a "
                             "measurable target",
                    "rationale": ("The wording implies a quality attribute but states no "
                                  "measurable target, context or verification method."),
                    "severity": "major",
                    "category": "testability",
                    "recommendation": ("Add target, measurement context, verification "
                                       "method and accountable owner."),
                    "targetStableId": stable_id,
                    "blocking": False,
                })
            if INTEGRATION_WORDS.search(text):
                dependencies.append({
                    "stableId": stable_id,
                    "kind": "external_system",
                    "description": ("Depends on an external system; capabilities, "
                                    "permissions and rate limits need discovery."),
                    "owner": None,
                })
                effort_drivers.append({
                    "stableId": stable_id, "driver": "external integration",
                    "impact": "high",
                    "note": "Discovery, mapping and failure handling are not yet estimated.",
                })
            if not story.get("acceptanceCriteria"):
                findings.append({
                    "title": f"{stable_id}: no acceptance criteria",
                    "rationale": "A story without acceptance criteria cannot be verified.",
                    "severity": "critical",
                    "category": "completeness",
                    "recommendation": "Add observable acceptance criteria before approval.",
                    "targetStableId": stable_id,
                    "blocking": True,
                })
            technical_notes[stable_id] = (
                "Architectural proposal (not a confirmed decision): implement behind the "
                "existing service boundary; validate inputs server side and enforce "
                "authorization on every record read.")

        # Project wide NFR candidates, labelled as proposals.
        for text, name in [
            ("P95 interactive API responses stay below 2 seconds at the agreed reference "
             "load, excluding AI, import and export jobs.", "Performance"),
            ("No cross project or cross client data is reachable through API, retrieval, "
             "export or job results.", "Isolation"),
            ("Local only projects produce no project derived outbound cloud requests.",
             "Data residency"),
        ]:
            nfrs.append({
                "title": f"{name} target (proposal)",
                "statement": text,
                "type": "non_functional",
                "priority": "high",
                "provenance": "ai_suggestion",
                "confidence": 0.5,
                "rationale": "Proposed baseline target; confirm with the delivery team.",
                "citations": [],
            })

        entities = self._data_entities(chunks)
        operations = self._api_operations(stories)
        diagrams = self._diagrams(stories)
        return {
            "schemaVersion": "1.0",
            "findings": findings,
            "technicalNotes": technical_notes,
            "nfrRequirements": nfrs,
            "dependencies": dependencies,
            "effortDrivers": effort_drivers,
            "dataEntities": entities,
            "apiOperations": operations,
            "processDiagrams": diagrams,
            "architectureProposals": [
                "Proposal: keep generated artifacts versioned and immutable once approved.",
                "Proposal: enforce authorization in the data access layer, not in the UI.",
            ],
        }

    def _data_entities(self, chunks: list[ParsedChunk]) -> list[dict[str, Any]]:
        # Candidate entities are nouns the prose refers to with an article or
        # determiner ("a customer", "the invoice", "ο πελάτης"). Table cells and
        # schema paths are skipped so column headers are not mistaken for them.
        prose = "\n".join(c.text for c in chunks if c.kind not in TABULAR_KINDS).lower()
        # Ordered by first mention (a dict, not a set) so ties rank the same way
        # on every run: same evidence in, same analysis out.
        candidates: dict[str, None] = {}
        for word in DETERMINER_NOUN.findall(prose):
            noun = word.lower()
            # Fold a simple English plural onto its singular.
            if noun.endswith("s") and len(noun) > 4:
                noun = noun[:-1]
            if noun not in NOT_ENTITIES:
                candidates.setdefault(noun, None)
        # A candidate counts every time the prose mentions it, plural included.
        counts: Counter[str] = Counter({
            noun: len(re.findall(rf"\b{re.escape(noun)}s?\b", prose)) for noun in candidates})
        entities = []
        for noun, hits in counts.most_common(8):
            if hits < 2:
                continue
            name = noun[:1].upper() + noun[1:]
            entities.append({
                "name": name,
                "description": f"Candidate entity observed {hits} times in the evidence.",
                "fields": [
                    {"name": "id", "type": "string", "required": True, "unique": True},
                    {"name": "name", "type": "string", "required": True},
                    {"name": "createdAt", "type": "datetime", "required": True},
                ],
                "relationships": [],
                "privacyClassification": "internal",
                "lifecycle": "created, updated, archived",
            })
        return entities

    def _api_operations(self, stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        operations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for story in stories[:20]:
            topic = _topic_of(story.get("title", "")) or "resource"
            resource = re.sub(r"[^a-z0-9]+", "-", topic).strip("-") or "resource"
            if resource in seen:
                continue
            seen.add(resource)
            operations += [
                {"method": "GET", "path": f"/api/v1/{resource}s", "summary": f"List {resource}s",
                 "auth": "bearer", "requestSchema": {}, "paginated": True,
                 "responseSchema": {"type": "object",
                                    "properties": {"items": {"type": "array"},
                                                   "total": {"type": "integer"}}},
                 "errors": [{"status": 401, "code": "unauthorized"},
                            {"status": 403, "code": "forbidden"}]},
                {"method": "POST", "path": f"/api/v1/{resource}s",
                 "summary": f"Create a {resource}", "auth": "bearer", "idempotent": True,
                 "requestSchema": {"type": "object", "required": ["name"],
                                   "properties": {"name": {"type": "string"}}},
                 "responseSchema": {"type": "object",
                                    "properties": {"id": {"type": "string"}}},
                 "errors": [{"status": 409, "code": "version_conflict"},
                            {"status": 422, "code": "validation_failed"}]},
            ]
        return operations

    def _diagrams(self, stories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not stories:
            return []
        lines = ["flowchart TD", "  start([Start])", "  start --> validate[Validate input]"]
        for index, story in enumerate(stories[:6], start=1):
            node = f"s{index}"
            label = _title_from(story.get("title", f"Step {index}"), 40).replace('"', "'")
            lines.append(f'  validate --> {node}["{label}"]')
            lines.append(f"  {node} --> decision{index}{{Allowed?}}")
            lines.append(f"  decision{index} -- no --> denied[/Access denied/]")
            lines.append(f"  decision{index} -- yes --> done([Recorded])")
        return [{
            "title": "Main flow with alternate and error paths",
            "mermaid": "\n".join(lines),
            "actors": ["user", "system"],
            "requirementIds": [s.get("stableId") for s in stories[:6]],
        }]

    # --- UX analyst ---------------------------------------------------------
    def _ux_review(self, chunks: list[ParsedChunk],
                   request: AdapterRequest) -> dict[str, Any]:
        stories = [s for s in _stories_from_instruction(request.instruction)
                   if s.get("type", "story") == "story"]

        # Personas: one per kind of person, whichever language names them, cited
        # where the evidence first does, and only when a story involves them.
        greek = request.language == "el"
        seen: OrderedDict[str, ParsedChunk] = OrderedDict()
        for chunk in chunks:
            if chunk.kind in TABULAR_KINDS:
                continue
            lowered = chunk.text.lower()
            for kind, (_, _, words) in PERSONA_KINDS.items():
                if any(re.search(rf"\b{re.escape(w)}", lowered) for w in words):
                    seen.setdefault(kind, chunk)
        personas: list[dict[str, Any]] = []
        journeys: list[dict[str, Any]] = []
        for kind, chunk in seen.items():
            english, greek_name, words = PERSONA_KINDS[kind]
            covered = [s for s in stories if any(
                re.search(rf"\b{re.escape(w)}",
                          f"{s.get('title', '')} {s.get('description') or ''}".lower())
                for w in words)]
            if not covered:
                continue
            name = greek_name if greek else english
            personas.append({
                "name": f"{name} (proposal)",
                "goals": [_title_from(s.get("title", ""), 70) for s in covered[:3]],
                "painPoints": [],
                "citations": [_citation(chunk)],
            })
            journeys.append(self._journey(name, covered[:6]))
            if len(personas) == 4:
                break

        screens: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        for story in stories[:12]:
            stable_id = story.get("stableId")
            criteria = [c.get("text", "") if isinstance(c, dict) else str(c)
                        for c in story.get("acceptanceCriteria") or []]
            text = " ".join([story.get("title", ""), story.get("description") or "", *criteria])
            states = ["empty", "loading", "error", "success"]
            if PERMISSION_WORDS.search(text):
                states.append("permission refused")
            screens.append({
                "name": _title_from(story.get("title", "Screen"), 60),
                "purpose": "Lets the user complete this story (proposal).",
                "storyStableIds": [stable_id] if stable_id else [],
                "states": states,
                "keyElements": [_title_from(c, 60) for c in criteria[:3]],
            })
            if not FEEDBACK_WORDS.search(text):
                findings.append({
                    "title": f"{stable_id}: no error or feedback state described",
                    "rationale": ("The story says what succeeds but not what the user sees "
                                  "when it fails, is refused or needs confirmation."),
                    "severity": "minor", "category": "ux",
                    "recommendation": "Add a criterion for the error and feedback states.",
                    "targetStableId": stable_id, "blocking": False,
                })
            if PERMISSION_WORDS.search(text) and not REFUSAL_WORDS.search(text):
                findings.append({
                    "title": f"{stable_id}: refused access is not designed",
                    "rationale": ("The story restricts access but does not say what a user "
                                  "without permission sees."),
                    "severity": "major", "category": "ux",
                    "recommendation": "Describe the refused state and how the user recovers.",
                    "targetStableId": stable_id, "blocking": False,
                })

        requirements: list[dict[str, Any]] = [{
            "title": "Accessibility baseline (proposal)",
            "statement": ("Every screen meets WCAG 2.1 level AA: keyboard operable, "
                          "screen reader labelled, 4.5:1 text contrast and usable at 320px."),
            "type": "ux", "priority": "high", "provenance": "ai_suggestion",
            "confidence": 0.5,
            "rationale": "Proposed baseline; confirm the required conformance level.",
            "citations": [],
        }]
        for chunk in chunks:
            for sentence in _prose_sentences(chunk.text):
                if UX_WORDS.search(sentence) and len(requirements) < 8:
                    requirements.append({
                        "title": _title_from(sentence),
                        "statement": sentence, "type": "ux", "priority": "medium",
                        "provenance": "evidence", "confidence": 0.7,
                        "citations": [_citation(chunk, sentence)],
                    })
        return {
            "schemaVersion": "1.0",
            "findings": findings,
            "personas": personas,
            "journeys": journeys,
            "screens": screens,
            "uxRequirements": requirements,
        }

    def _journey(self, persona: str, stories: list[dict[str, Any]]) -> dict[str, Any]:
        steps = [_title_from(s.get("title", ""), 50) for s in stories]
        lines = ["flowchart LR", f'  start(["{persona} arrives"])']
        previous = "start"
        for index, step in enumerate(steps, start=1):
            node = f"step{index}"
            lines.append(f'  {previous} --> {node}["{step.replace(chr(34), chr(39))}"]')
            previous = node
        lines.append(f"  {previous} --> done([Goal reached])")
        return {
            "title": f"{persona} journey (proposal)",
            "persona": persona,
            "steps": steps,
            "mermaid": "\n".join(lines),
            "storyStableIds": [s.get("stableId") for s in stories if s.get("stableId")],
        }

    # --- data analyst -------------------------------------------------------
    def _data_review(self, chunks: list[ParsedChunk],
                     request: AdapterRequest) -> dict[str, Any]:
        entities = self._data_entities(chunks)
        findings: list[dict[str, Any]] = []
        requirements: list[dict[str, Any]] = [{
            "title": "Every personal data field is classified (proposal)",
            "statement": ("Each field holding personal data carries a privacy classification, "
                          "a retention rule and a deletion method before it is built."),
            "type": "data", "priority": "high", "provenance": "ai_suggestion",
            "confidence": 0.5, "rationale": "Proposed baseline for GDPR accountability.",
            "citations": [],
        }]
        quality_rules: list[dict[str, Any]] = []
        for entity in entities:
            quality_rules.append({"entity": entity["name"], "field": "id",
                                  "rule": "Present and unique", "severity": "critical"})
            quality_rules.append({"entity": entity["name"], "field": "name",
                                  "rule": "Present and not blank", "severity": "major"})

        metrics: list[dict[str, Any]] = []
        retention: list[dict[str, Any]] = []
        migration: list[dict[str, Any]] = []
        personal: list[tuple[ParsedChunk, str]] = []
        for chunk in chunks:
            if chunk.kind in TABULAR_KINDS:
                continue
            for sentence in _prose_sentences(chunk.text):
                cite = [_citation(chunk, sentence)]
                if PERSONAL_WORDS.search(sentence):
                    personal.append((chunk, sentence))
                if RETENTION_WORDS.search(sentence):
                    retention.append({
                        "entity": _topic_of(sentence, "record").capitalize(),
                        "classification": "confidential",
                        "retention": sentence,
                        "deletion": None,
                        "citations": cite,
                    })
                    requirements.append({
                        "title": _title_from(sentence), "statement": sentence,
                        "type": "data", "priority": "high", "provenance": "evidence",
                        "confidence": 0.7, "citations": cite,
                    })
                if METRIC_WORDS.search(sentence) and len(metrics) < 6:
                    name = _metric_name(sentence)
                    metrics.append({"name": name, "definition": f"As stated: {sentence}",
                                    "formula": None, "sourceEntities": [],
                                    "citations": cite})
                    findings.append({
                        "title": f"Metric without an exact definition: {name}",
                        "rationale": ("The evidence names a report or figure but not how it "
                                      "is calculated, from which data or for which period."),
                        "severity": "minor", "category": "data",
                        "recommendation": "Agree the formula, source data and period.",
                        "blocking": False, "citations": cite,
                    })
                if MIGRATION_WORDS.search(sentence) and len(migration) < 6:
                    migration.append({"source": _title_from(sentence, 60), "target": None,
                                      "notes": sentence, "citations": cite})
        if personal and not retention:
            chunk, sentence = personal[0]
            findings.append({
                "title": "Personal data without a retention rule",
                "rationale": ("The evidence mentions personal data but no retention period "
                              "or deletion rule for it."),
                "severity": "major", "category": "data",
                "recommendation": ("Ask the client for the retention period and its legal "
                                   "basis before the data model is approved."),
                "blocking": False, "citations": [_citation(chunk, sentence)],
            })
        return {
            "schemaVersion": "1.0",
            "findings": findings,
            "dataRequirements": requirements[:10],
            "qualityRules": quality_rules,
            "metrics": metrics,
            "retention": retention[:6],
            "migration": migration,
        }

    # --- QA analyst ---------------------------------------------------------
    def _qa_review(self, chunks: list[ParsedChunk],
                   request: AdapterRequest) -> dict[str, Any]:
        stories = _stories_from_instruction(request.instruction)
        findings: list[dict[str, Any]] = []
        tests: list[dict[str, Any]] = []
        refined: dict[str, list[str]] = {}
        coverage_notes: list[str] = []

        for story in stories:
            stable_id = story.get("stableId")
            criteria = story.get("acceptanceCriteria") or []
            if not criteria:
                findings.append({
                    "title": f"{stable_id}: untestable, no acceptance criteria",
                    "rationale": "No observable outcome is stated, so no test can verify it.",
                    "severity": "critical", "category": "testability",
                    "recommendation": "Add observable criteria before approval.",
                    "targetStableId": stable_id, "blocking": True,
                })
                continue

            for index, criterion in enumerate(criteria):
                text = criterion.get("text") if isinstance(criterion, dict) else str(criterion)
                if not text:
                    continue
                if len(text.split()) < 5:
                    findings.append({
                        "title": f"{stable_id}: criterion {index + 1} is too vague to verify",
                        "rationale": "The criterion does not state an observable outcome.",
                        "severity": "major", "category": "testability",
                        "recommendation": "Restate as Given/When/Then with an expected result.",
                        "targetStableId": stable_id, "blocking": False,
                    })
                    refined.setdefault(stable_id, []).append(
                        f"Given a valid context, when the action runs, then {text.strip('.')}.")

                tests.append(self._positive_test(story, text, index))
                if PERMISSION_WORDS.search(text) or index == 0:
                    tests.append(self._negative_test(story, text, index))
                if NUMBER_RE.search(text):
                    tests.append(self._boundary_test(story, text, index))

        if stories:
            tests.append({
                "title": "End to end: approved scope reaches delivery without losing traceability",
                "storyStableId": None,
                "objective": ("Validate the cross story outcome rather than the sum of "
                              "individual stories."),
                "testType": "end_to_end", "priority": "high",
                "preconditions": ["Approved bundle exists", "A delivery destination is configured"],
                "steps": [
                    {"ordinal": 1, "action": "Approve the parent bundle",
                     "expected": "All descendant versions are approved with inherited events"},
                    {"ordinal": 2, "action": "Publish the approved manifest",
                     "expected": "Each item reports success, conflict or failure individually"},
                ],
                "expectedResults": ["Traceability from evidence to external item is intact"],
                "environmentAssumptions": ["Reference deployment with seeded data"],
                "gherkin": {
                    "feature": "Approved scope reaches delivery",
                    "scenario": "Publishing an approved bundle preserves traceability",
                    "tags": ["@end_to_end", "@high"],
                    "given": ["an approved parent bundle"],
                    "when": ["the publication job runs"],
                    "then": ["every item reports an individual outcome",
                             "no unapproved version is published"],
                },
            })
            coverage_notes.append(
                "Generated tests are drafts in review state; generation never marks a "
                "test as passed.")
        return {"schemaVersion": "1.0", "findings": findings, "refinedCriteria": refined,
                "tests": tests, "coverageNotes": coverage_notes}

    def _positive_test(self, story: dict[str, Any], criterion: str, index: int) -> dict[str, Any]:
        stable_id = story.get("stableId")
        return {
            "title": f"{stable_id} criterion {index + 1}: expected behaviour",
            "storyStableId": stable_id, "criterionIndex": index,
            "objective": criterion,
            "testType": "positive", "priority": story.get("priority", "medium"),
            "preconditions": ["An authenticated user with the required permission"],
            "steps": [{"ordinal": 1, "action": "Perform the described action with valid data",
                       "expected": criterion}],
            "expectedResults": [criterion],
            "environmentAssumptions": ["Synthetic data only, no production content"],
            "gherkin": {
                "feature": story.get("title", "Feature"),
                "scenario": f"Criterion {index + 1} is satisfied",
                "tags": [f"@{stable_id}", f"@AC-{index + 1:02d}", "@positive"],
                "given": ["an authenticated user with the required permission"],
                "when": ["the action is performed with valid data"],
                "then": [criterion.rstrip(".")],
            },
        }

    def _negative_test(self, story: dict[str, Any], criterion: str, index: int) -> dict[str, Any]:
        stable_id = story.get("stableId")
        return {
            "title": f"{stable_id} criterion {index + 1}: unauthorized access is refused",
            "storyStableId": stable_id, "criterionIndex": index,
            "objective": "No content is returned to a caller without permission.",
            "testType": "permissions", "priority": "high",
            "preconditions": ["An authenticated user without the required permission"],
            "steps": [{"ordinal": 1, "action": "Attempt the same action",
                       "expected": "Access is denied and no content is returned"}],
            "expectedResults": ["Access is denied", "No restricted content is returned"],
            "environmentAssumptions": ["Synthetic data only"],
            "gherkin": {
                "feature": story.get("title", "Feature"),
                "scenario": f"Criterion {index + 1} denies an unauthorized caller",
                "tags": [f"@{stable_id}", f"@AC-{index + 1:02d}", "@negative", "@high"],
                "given": ["an authenticated user without the required permission"],
                "when": ["the action is attempted"],
                "then": ["access is denied", "no restricted content is returned"],
            },
        }

    def _boundary_test(self, story: dict[str, Any], criterion: str, index: int) -> dict[str, Any]:
        stable_id = story.get("stableId")
        return {
            "title": f"{stable_id} criterion {index + 1}: boundary values",
            "storyStableId": stable_id, "criterionIndex": index,
            "objective": "Values at and beyond the stated boundary behave as specified.",
            "testType": "boundary", "priority": "medium",
            "preconditions": ["An authenticated user with the required permission"],
            "steps": [{"ordinal": 1, "action": "Submit the value at the boundary",
                       "expected": "Accepted"},
                      {"ordinal": 2, "action": "Submit the value beyond the boundary",
                       "expected": "Rejected with an actionable message"}],
            "expectedResults": ["Boundary accepted", "Beyond boundary rejected"],
            "environmentAssumptions": ["Synthetic data only"],
            "gherkin": {
                "feature": story.get("title", "Feature"),
                "scenario": f"Criterion {index + 1} boundary handling",
                "tags": [f"@{stable_id}", f"@AC-{index + 1:02d}", "@boundary"],
                "given": ["an authenticated user with the required permission"],
                "when": ["the value <value> is submitted"],
                "then": ["the outcome is <outcome>"],
                "examplesHeader": ["value", "outcome"],
                "examplesRows": [["at the limit", "accepted"],
                                 ["beyond the limit", "rejected"]],
            },
        }


def _metric_name(sentence: str) -> str:
    """The figure a sentence is about: its words before the first verb."""
    head = re.split(MODALS, sentence, maxsplit=1)[0].strip(" ,:")
    words = head.split()
    if 1 <= len(words) <= 6:
        return head[:1].upper() + head[1:]
    return _title_from(sentence, 60)


def _stories_from_instruction(instruction: str) -> list[dict[str, Any]]:
    """The orchestrator passes the current backlog as JSON in the instruction."""
    match = re.search(r"<<BACKLOG>>\n(?P<json>.*?)\n<<END>>", instruction, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group("json"))
    except json.JSONDecodeError:
        return []


class LocalHttpAdapter(ModelAdapter):
    """Company hosted inference server with an OpenAI compatible API."""

    deployment = "local"

    def __init__(self, base_url: str, model_id: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(name=self.model_id, deployment="local",
                                 context_tokens=32_768, supports_json_schema=True)

    async def health(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/models")
            return response.status_code < 500, f"HTTP {response.status_code}"
        except Exception as exc:
            return False, str(exc)

    async def generate(self, request: AdapterRequest) -> AdapterResponse:
        started = time.perf_counter()
        body = {
            "model": self.model_id,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": f"{request.instruction}\n\n{request.context}"},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(f"{self.base_url}/chat/completions", json=body)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise AdapterUnavailable(
                f"The local inference service at {self.base_url} is unreachable: {exc}"
            ) from exc

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AdapterUnavailable(
                f"The local model returned output that is not valid JSON: {exc}") from exc
        return AdapterResponse(
            payload=payload, model_id=self.model_id, deployment="local",
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=int((time.perf_counter() - started) * 1000), raw=content,
        )


def default_local_adapter() -> ModelAdapter:
    if settings.local_inference_url:
        return LocalHttpAdapter(settings.local_inference_url, settings.default_local_model)
    return HeuristicLocalAdapter()
