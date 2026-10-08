"""Gherkin parsing, validation and rendering (section 13).

The canonical scenario structure is stored once. Greek and English are display
dialects of the same structure, so a translated view never creates a duplicate
test. Validation is structural: it blocks approval on invalid syntax or a
missing Examples value (AT-19), and it does not claim semantic quality.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.models.testing import (GherkinFeature, GherkinScenario, GherkinStep,
                                GherkinValidation)

DIALECTS: dict[str, dict[str, list[str]]] = {
    "en": {
        "feature": ["Feature"],
        "background": ["Background"],
        "scenario": ["Scenario", "Example"],
        "scenario_outline": ["Scenario Outline", "Scenario Template"],
        "examples": ["Examples", "Scenarios"],
        "given": ["Given"], "when": ["When"], "then": ["Then"],
        "and": ["And"], "but": ["But"],
    },
    "el": {
        "feature": ["Λειτουργία", "Δυνατότητα"],
        "background": ["Υπόβαθρο"],
        "scenario": ["Σενάριο", "Παράδειγμα"],
        "scenario_outline": ["Περίγραμμα Σεναρίου", "Περιγραφή Σεναρίου"],
        "examples": ["Παραδείγματα", "Σενάρια"],
        "given": ["Δεδομένου", "Δοθέντος"], "when": ["Όταν"], "then": ["Τότε"],
        "and": ["Και"], "but": ["Αλλά"],
    },
}

STEP_KEYS = ("given", "when", "then", "and", "but")
CANONICAL_STEP = {"given": "Given", "when": "When", "then": "Then",
                  "and": "And", "but": "But"}

PLACEHOLDER_RE = re.compile(r"<([^<>]+)>")
SECRET_RE = re.compile(r"(?i)\b(password|secret|api[_\- ]?key|token)\b\s*[:=]\s*\S+")


@dataclass
class _Line:
    number: int
    text: str


def detect_dialect(text: str) -> str:
    for dialect, keywords in DIALECTS.items():
        for keyword in keywords["feature"]:
            if re.search(rf"^\s*{re.escape(keyword)}\s*:", text, re.MULTILINE):
                return dialect
    return "en"


def _match_keyword(line: str, dialect: str, key: str) -> str | None:
    for keyword in DIALECTS[dialect][key]:
        pattern = rf"^\s*{re.escape(keyword)}\s*:\s*(?P<rest>.*)$"
        match = re.match(pattern, line)
        if match:
            return match.group("rest").strip()
    return None


def _match_step(line: str, dialect: str) -> tuple[str, str] | None:
    for key in STEP_KEYS:
        for keyword in DIALECTS[dialect][key]:
            match = re.match(rf"^\s*{re.escape(keyword)}\s+(?P<rest>.+)$", line)
            if match:
                return CANONICAL_STEP[key], match.group("rest").strip()
    return None


def parse(text: str, dialect: str | None = None) -> tuple[GherkinFeature | None,
                                                          list[dict[str, Any]]]:
    """Parse a .feature document. Returns the feature and structural errors."""
    errors: list[dict[str, Any]] = []
    resolved = dialect or detect_dialect(text)
    lines = [_Line(i + 1, raw.rstrip()) for i, raw in enumerate(text.splitlines())]

    feature: GherkinFeature | None = None
    current: GherkinScenario | None = None
    pending_tags: list[str] = []
    in_examples = False
    description: list[str] = []

    for line in lines:
        stripped = line.text.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("@"):
            pending_tags = [t for t in stripped.split() if t.startswith("@")]
            continue

        feature_name = _match_keyword(line.text, resolved, "feature")
        if feature_name is not None:
            if feature is not None:
                errors.append({"line": line.number,
                               "message": "More than one Feature in a single document"})
            feature = GherkinFeature(name=feature_name, tags=pending_tags, dialect=resolved)
            pending_tags = []
            current, in_examples = None, False
            continue

        if feature is None:
            errors.append({"line": line.number,
                           "message": "Content appears before the Feature keyword"})
            continue

        background = _match_keyword(line.text, resolved, "background")
        if background is not None:
            current = GherkinScenario(name="Background", tags=[])
            feature.background = []
            in_examples = False
            continue

        outline_name = _match_keyword(line.text, resolved, "scenario_outline")
        scenario_name = outline_name if outline_name is not None else \
            _match_keyword(line.text, resolved, "scenario")
        if scenario_name is not None:
            current = GherkinScenario(name=scenario_name, tags=pending_tags,
                                      outline=outline_name is not None)
            feature.scenarios.append(current)
            pending_tags = []
            in_examples = False
            continue

        examples = _match_keyword(line.text, resolved, "examples")
        if examples is not None:
            if current is None or not current.outline:
                errors.append({"line": line.number,
                               "message": "Examples block without a Scenario Outline"})
            in_examples = True
            continue

        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if in_examples and current is not None:
                if not current.examples_header:
                    current.examples_header = cells
                else:
                    if len(cells) != len(current.examples_header):
                        errors.append({
                            "line": line.number,
                            "message": (f"Examples row has {len(cells)} values but the "
                                        f"header declares {len(current.examples_header)}")})
                    if any(cell == "" for cell in cells):
                        errors.append({"line": line.number,
                                       "message": "Examples row contains an empty value"})
                    current.examples_rows.append(cells)
            continue

        step = _match_step(line.text, resolved)
        if step is not None:
            keyword, body = step
            if current is None:
                feature.background.append(GherkinStep(keyword=keyword, text=body))
            else:
                current.steps.append(GherkinStep(keyword=keyword, text=body))
            continue

        description.append(stripped)

    if feature is not None and description:
        feature.description = "\n".join(description)
    if feature is None:
        errors.append({"line": 1, "message": "No Feature keyword was found"})
    return feature, errors


def validate(text: str, dialect: str | None = None) -> GherkinValidation:
    feature, errors = parse(text, dialect)
    warnings: list[dict[str, Any]] = []
    tags: list[str] = []

    if feature is not None:
        tags = list(feature.tags)
        if not feature.scenarios:
            errors.append({"line": 0, "message": "The feature contains no scenarios"})
        for scenario in feature.scenarios:
            tags += scenario.tags
            keywords = [s.keyword for s in scenario.steps]
            if "Given" not in keywords and "When" not in keywords:
                errors.append({"line": 0,
                               "message": f"Scenario '{scenario.name}' has no Given or When"})
            if "Then" not in keywords:
                errors.append({"line": 0,
                               "message": f"Scenario '{scenario.name}' has no Then, so it "
                                          "states no expected result"})
            placeholders = {p for step in scenario.steps
                            for p in PLACEHOLDER_RE.findall(step.text)}
            if scenario.outline:
                if not scenario.examples_rows:
                    errors.append({"line": 0,
                                   "message": f"Scenario Outline '{scenario.name}' has no "
                                              "Examples rows"})
                missing = placeholders - set(scenario.examples_header)
                if missing:
                    errors.append({"line": 0,
                                   "message": f"Placeholders {sorted(missing)} are not "
                                              "present in the Examples header"})
            elif placeholders:
                warnings.append({"line": 0,
                                 "message": f"Scenario '{scenario.name}' uses placeholders "
                                            "but is not a Scenario Outline"})
            for step in scenario.steps:
                if SECRET_RE.search(step.text):
                    errors.append({"line": 0,
                                   "message": "A step appears to contain a credential; "
                                              "examples must use synthetic data only"})
        if not any(t.startswith("@") for t in tags):
            warnings.append({"line": 0,
                             "message": "No stable tags were found. Requirement, story, "
                                        "criterion, priority and category tags are expected."})

    return GherkinValidation(
        valid=not errors,
        dialect=(feature.dialect if feature else (dialect or "en")),
        errors=errors, warnings=warnings,
        scenario_count=len(feature.scenarios) if feature else 0,
        tags=sorted(set(tags)),
    )


def render_feature(feature: GherkinFeature, dialect: str = "en") -> str:
    """Render the canonical structure in the requested display dialect."""
    keywords = DIALECTS.get(dialect, DIALECTS["en"])
    lines: list[str] = []
    if feature.tags:
        lines.append(" ".join(feature.tags))
    lines.append(f"{keywords['feature'][0]}: {feature.name}")
    if feature.description:
        lines += [f"  {line}" for line in feature.description.splitlines()]
    if feature.background:
        lines.append("")
        lines.append(f"  {keywords['background'][0]}:")
        lines += [f"    {_step_keyword(step.keyword, keywords)} {step.text}"
                  for step in feature.background]
    for scenario in feature.scenarios:
        lines.append("")
        if scenario.tags:
            lines.append("  " + " ".join(scenario.tags))
        header = keywords["scenario_outline"][0] if scenario.outline else keywords["scenario"][0]
        lines.append(f"  {header}: {scenario.name}")
        lines += [f"    {_step_keyword(step.keyword, keywords)} {step.text}"
                  for step in scenario.steps]
        if scenario.outline and scenario.examples_header:
            lines.append("")
            lines.append(f"    {keywords['examples'][0]}:")
            lines.append("      | " + " | ".join(scenario.examples_header) + " |")
            for row in scenario.examples_rows:
                lines.append("      | " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def _step_keyword(canonical: str, keywords: dict[str, list[str]]) -> str:
    mapping = {"Given": "given", "When": "when", "Then": "then",
               "And": "and", "But": "but"}
    return keywords[mapping.get(canonical, "given")][0]


def feature_from_text(text: str, dialect: str | None = None) -> GherkinFeature | None:
    feature, _ = parse(text, dialect)
    return feature
