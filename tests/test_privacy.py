"""Tests for deterministic privacy and sensitive-data analysis."""

from server.models import DatasetMetadata
from server.validation.privacy import PrivacyValidation


def _make_metadata_with_desc(description: str, notes: str | None = None) -> DatasetMetadata:
    return DatasetMetadata(
        name="test-privacy-dataset",
        identifier="test/privacy-dataset",
        source_platform="Hugging Face",
        source_url="https://huggingface.co/datasets/test/privacy-dataset",
        description=description,
        notes=notes,
        access_method="official_api",
        download_available=True,
    )


def test_explicitly_deidentified_records():
    """Verify 'All records were de-identified.' marks explicitly_deidentified = True."""
    meta = _make_metadata_with_desc("This corpus is public. All records were de-identified.")
    (
        priv_status,
        deid,
        anon,
        sensitive,
        evidence,
        warnings,
        missing,
    ) = PrivacyValidation.validate(meta)

    assert deid is True
    assert priv_status == "explicitly_deidentified"
    assert any(e.field == "deidentified" for e in evidence)


def test_general_privacy_discussion_not_marked_deidentified():
    """Verify 'The project discusses privacy.' does NOT mark explicitly_deidentified."""
    meta = _make_metadata_with_desc("The project discusses privacy and machine learning security.")
    (
        priv_status,
        deid,
        anon,
        sensitive,
        evidence,
        warnings,
        missing,
    ) = PrivacyValidation.validate(meta)

    assert deid is None
    assert anon is None
    assert priv_status == "no_statement_found"
    assert "Explicit privacy/de-identification statement" in missing


def test_pii_removed_statement():
    """Verify 'PII was removed before release.' marks explicitly_deidentified = True."""
    meta = _make_metadata_with_desc("PII was removed before release to protect user identities.")
    (
        priv_status,
        deid,
        anon,
        sensitive,
        evidence,
        warnings,
        missing,
    ) = PrivacyValidation.validate(meta)

    assert deid is True
    assert priv_status == "explicitly_deidentified"
    assert any("PII was removed" in e.value for e in evidence)


def test_explicitly_anonymized():
    """Verify 'All participants were anonymized.' marks explicitly_anonymized = True."""
    meta = _make_metadata_with_desc("Clinical interview transcripts. All participants were anonymized.")
    (
        priv_status,
        deid,
        anon,
        sensitive,
        evidence,
        warnings,
        missing,
    ) = PrivacyValidation.validate(meta)

    assert anon is True
    assert priv_status == "explicitly_anonymized"
    assert any(e.field == "anonymized" for e in evidence)


def test_sensitive_mental_health_warning():
    """Verify explicit mental-health warning is detected and preserved with evidence."""
    meta = _make_metadata_with_desc(
        "This dataset contains sensitive mental-health information and expressions of distress."
    )
    (
        priv_status,
        deid,
        anon,
        sensitive,
        evidence,
        warnings,
        missing,
    ) = PrivacyValidation.validate(meta)

    assert sensitive is True
    assert any(e.field == "sensitive_data_warning" for e in evidence)
    assert any("sensitive mental health" in w.lower() for w in warnings)


def test_sensitive_hyperparameters_not_flagged():
    """Verify unrelated use like 'sensitive hyperparameters' does NOT trigger sensitive data warning."""
    meta = _make_metadata_with_desc("This project uses sensitive hyperparameters for learning rate scheduling.")
    (
        priv_status,
        deid,
        anon,
        sensitive,
        evidence,
        warnings,
        missing,
    ) = PrivacyValidation.validate(meta)

    assert sensitive is None
    assert not any(e.field == "sensitive_data_warning" for e in evidence)
