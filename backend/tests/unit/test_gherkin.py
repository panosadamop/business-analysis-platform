"""Gherkin parsing, validation and bilingual rendering (section 13)."""
from __future__ import annotations

from app.services import gherkin

VALID_EN = """@STORY-042 @AC-042-02 @negative @high
Feature: Restricted project access
  Scenario: Client cannot access an unshared project
    Given an authenticated client reviewer with access only to Project A
    When the reviewer requests an artifact from Project B
    Then access is denied
    And no Project B content is returned
"""

VALID_EL = """@STORY-042 @positive
Λειτουργία: Περιορισμένη πρόσβαση
  Σενάριο: Ο πελάτης δεν βλέπει μη κοινοποιημένο έργο
    Δεδομένου ένας πιστοποιημένος πελάτης με πρόσβαση μόνο στο Έργο Α
    Όταν ζητά τεκμήριο από το Έργο Β
    Τότε η πρόσβαση απορρίπτεται
"""

OUTLINE_WITH_GAP = """Feature: Boundary handling
  Scenario Outline: Values at the limit
    Given a configured limit
    When the value <value> is submitted
    Then the outcome is <outcome>

    Examples:
      | value | outcome |
      | 10    | accepted |
      |       | rejected |
"""

NO_THEN = """Feature: Incomplete
  Scenario: Missing expected result
    Given a user
    When they act
"""


def test_valid_english_feature_parses_with_tags():
    result = gherkin.validate(VALID_EN)
    assert result.valid is True
    assert result.dialect == "en"
    assert result.scenario_count == 1
    assert "@STORY-042" in result.tags and "@negative" in result.tags


def test_greek_dialect_is_detected_and_parsed():
    result = gherkin.validate(VALID_EL)
    assert result.valid is True
    assert result.dialect == "el"
    assert result.scenario_count == 1


def test_missing_examples_value_blocks_approval():
    """AT-19 — a missing Examples value is a validation error, not a warning."""
    result = gherkin.validate(OUTLINE_WITH_GAP)
    assert result.valid is False
    assert any("empty value" in e["message"] for e in result.errors)


def test_scenario_without_then_is_invalid():
    result = gherkin.validate(NO_THEN)
    assert result.valid is False
    assert any("no Then" in e["message"] for e in result.errors)


def test_invalid_syntax_is_reported():
    result = gherkin.validate("This document has no Feature keyword at all")
    assert result.valid is False
    assert any("No Feature keyword" in e["message"] for e in result.errors)


def test_credentials_in_examples_are_rejected():
    document = """Feature: Login
  Scenario: Sign in
    Given a user with password: hunter2
    When they sign in
    Then the dashboard is shown
"""
    result = gherkin.validate(document)
    assert result.valid is False
    assert any("credential" in e["message"] for e in result.errors)


def test_one_canonical_structure_renders_in_both_dialects():
    """Translated display versions never create duplicate tests."""
    feature = gherkin.feature_from_text(VALID_EN)
    english = gherkin.render_feature(feature, "en")
    greek = gherkin.render_feature(feature, "el")

    assert english.startswith("@STORY-042")
    assert "Feature: Restricted project access" in english
    assert "Λειτουργία: Restricted project access" in greek
    assert "Δεδομένου" in greek and "Τότε" in greek
    # Both renderings parse back to the same scenario count and tags.
    assert (gherkin.validate(english).scenario_count
            == gherkin.validate(greek).scenario_count == 1)
    assert gherkin.validate(greek).valid is True


def test_round_trip_preserves_outline_examples():
    document = """Feature: Limits
  Scenario Outline: Boundary
    Given a limit
    When <value> is submitted
    Then the result is <outcome>

    Examples:
      | value | outcome  |
      | 10    | accepted |
      | 11    | rejected |
"""
    feature = gherkin.feature_from_text(document)
    assert feature.scenarios[0].outline is True
    assert feature.scenarios[0].examples_header == ["value", "outcome"]
    assert len(feature.scenarios[0].examples_rows) == 2
    rendered = gherkin.render_feature(feature)
    assert gherkin.validate(rendered).valid is True
