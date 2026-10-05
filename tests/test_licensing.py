"""Tests for deterministic license validation layer."""

from server.models import DatasetMetadata
from server.validation.licensing import LicenseValidation


def _make_metadata(license_val: str | None) -> DatasetMetadata:
    return DatasetMetadata(
        name="test-dataset",
        identifier="test/dataset",
        source_platform="Hugging Face",
        source_url="https://huggingface.co/datasets/test/dataset",
        description="A dataset for testing.",
        license=license_val,
        access_method="official_api",
        download_available=True,
    )


def test_explicit_mit_license():
    """Verify explicit MIT license is documented with evidence and no restrictions."""
    meta = _make_metadata("MIT")
    status, name, evidence, warnings, missing = LicenseValidation.validate(meta)

    assert status == "documented"
    assert name == "MIT"
    assert len(evidence) == 1
    assert evidence[0].field == "license"
    assert evidence[0].value == "MIT"
    assert evidence[0].evidence_type == "platform_license_metadata"
    assert len(warnings) == 0
    assert len(missing) == 0


def test_explicit_cc_by_license():
    """Verify CC-BY-4.0 license is documented."""
    meta = _make_metadata("CC-BY-4.0")
    status, name, evidence, warnings, missing = LicenseValidation.validate(meta)

    assert status == "documented"
    assert name == "CC-BY-4.0"
    assert len(evidence) == 1
    assert len(warnings) == 0
    assert len(missing) == 0


def test_explicit_cc_by_nc_license():
    """Verify CC-BY-NC contains non-commercial informational warning without rejecting."""
    meta = _make_metadata("CC-BY-NC-4.0")
    status, name, evidence, warnings, missing = LicenseValidation.validate(meta)

    assert status == "documented"
    assert name == "CC-BY-NC-4.0"
    assert len(evidence) == 1
    assert any("non-commercial" in w.lower() for w in warnings)
    assert len(missing) == 0


def test_missing_license():
    """Verify None license reports missing status and records missing information."""
    meta = _make_metadata(None)
    status, name, evidence, warnings, missing = LicenseValidation.validate(meta)

    assert status == "missing"
    assert name is None
    assert len(evidence) == 0
    assert any("no explicit license" in w.lower() for w in warnings)
    assert "Explicit dataset license" in missing


def test_unknown_or_unspecified_license():
    """Verify 'unknown' or 'unspecified' license strings are treated as missing."""
    for raw in ["unknown", "UNKNOWN", "unspecified", "none", "null"]:
        meta = _make_metadata(raw)
        status, name, evidence, warnings, missing = LicenseValidation.validate(meta)

        assert status == "missing"
        assert name is None
        assert "Explicit dataset license" in missing
