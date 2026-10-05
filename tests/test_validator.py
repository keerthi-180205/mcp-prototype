"""Tests for DatasetValidator engine orchestrating deterministic validation."""

from server.models import DatasetMetadata, DatasetValidationResult
from server.validation.validator import DatasetValidator


def test_validator_documented_complete():
    """Verify validator returns documented status when license, doc, and de-identification are present."""
    validator = DatasetValidator()
    meta = DatasetMetadata(
        name="empathy-dataset",
        identifier="org/empathy",
        source_platform="Hugging Face",
        source_url="https://huggingface.co/datasets/org/empathy",
        description="A comprehensive empathy dataset. All records were de-identified before release.",
        license="CC-BY-4.0",
        provenance="Curated by Research Lab",
        access_method="official_api",
        download_available=True,
    )

    result = validator.validate(
        meta,
        discovered_from="GitHub README",
        source_repository="test-owner/test-repo",
    )

    assert isinstance(result, DatasetValidationResult)
    assert result.dataset_name == "empathy-dataset"
    assert result.source_platform == "Hugging Face"
    assert result.source_url == "https://huggingface.co/datasets/org/empathy"
    assert result.validation_status == "documented"
    assert result.license_status == "documented"
    assert result.license_name == "CC-BY-4.0"
    assert result.privacy_status == "explicitly_deidentified"
    assert result.explicitly_deidentified is True
    assert result.explicitly_anonymized is None
    assert result.provenance_status == "documented"
    assert result.provenance.discovered_from == "GitHub README"
    assert result.provenance.source_repository == "test-owner/test-repo"
    assert result.access_status == "public_metadata"
    assert result.documentation_available is True
    assert len(result.evidence) >= 3


def test_validator_incomplete_missing_privacy_statement():
    """Verify validator flags missing privacy statements without making legal decisions."""
    validator = DatasetValidator()
    meta = DatasetMetadata(
        name="mental-health-posts",
        identifier="10.5281/zenodo.12345",
        source_platform="Zenodo",
        source_url="https://zenodo.org/records/12345",
        description="Collection of social media posts discussing mental wellbeing.",
        license="MIT",
        provenance="Author Name",
        access_method="official_api",
        download_available=True,
    )

    result = validator.validate(meta)

    assert result.validation_status == "incomplete"
    assert result.license_status == "documented"
    assert result.privacy_status == "no_statement_found"
    assert result.explicitly_deidentified is None
    assert result.explicitly_anonymized is None
    assert "Explicit privacy/de-identification statement" in result.missing_information
    assert any("no explicit dataset-level de-identification" in w.lower() for w in result.warnings)

    # Ensure no legal decision attributes exist
    assert not hasattr(result, "legally_safe")
    assert not hasattr(result, "safe_to_use")
    assert not hasattr(result, "approved")


def test_validator_gated_and_sensitive_warning():
    """Verify gated access triggers restricted access status and preserves sensitive warning."""
    validator = DatasetValidator()
    meta = DatasetMetadata(
        name="clinical-conversations",
        identifier="hf-internal/clinical",
        source_platform="Hugging Face",
        source_url="https://huggingface.co/datasets/hf-internal/clinical",
        description="Clinical psychotherapy dialogues. Contains sensitive mental-health information.",
        license="CC-BY-NC-4.0",
        provenance="Hospital Research Group",
        access_method="gated_access",
        download_available=False,
    )

    result = validator.validate(meta)

    assert result.access_status == "restricted"
    assert result.contains_sensitive_data_warning is True
    assert any("gated access" in w.lower() for w in result.warnings)
    assert any("sensitive mental health" in w.lower() for w in result.warnings)
    assert any("non-commercial" in w.lower() for w in result.warnings)
