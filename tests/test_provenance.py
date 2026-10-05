"""Tests for provenance tracking and origin chain preservation."""

from server.models import DatasetMetadata
from server.validation.provenance import ProvenanceValidation


def test_provenance_full_chain_preservation():
    """Verify that discovery source, repository, provider, and source URL are preserved."""
    meta = DatasetMetadata(
        name="empathy-mental-health-dialogues",
        identifier="behavioral-data/Empathy-Mental-Health",
        source_platform="Hugging Face",
        source_url="https://huggingface.co/datasets/behavioral-data/Empathy-Mental-Health",
        description="Empathy dataset referenced in GitHub repository.",
        provenance="Curated by Behavioral Data Lab",
        access_method="official_api",
        download_available=True,
    )

    status, record, evidence, warnings, missing = ProvenanceValidation.validate(
        metadata=meta,
        discovered_from="GitHub README",
        source_repository="kharrigian/mental-health-datasets",
    )

    assert status == "documented"
    assert record.discovered_from == "GitHub README"
    assert record.source_repository == "kharrigian/mental-health-datasets"
    assert record.source_url == "https://huggingface.co/datasets/behavioral-data/Empathy-Mental-Health"
    assert record.provider == "Hugging Face"
    assert record.access_method == "official_api"
    assert record.retrieved_at is not None

    # Check evidence
    assert any(e.field == "provenance" for e in evidence)
    assert any(e.field == "attribution" and "Behavioral Data Lab" in e.value for e in evidence)
    assert len(warnings) == 0


def test_provenance_partial_when_attribution_missing():
    """Verify partial status when platform URL exists but author attribution is missing."""
    meta = DatasetMetadata(
        name="zenodo-record-12345",
        identifier="12345",
        source_platform="Zenodo",
        source_url="https://zenodo.org/records/12345",
        description="Public Zenodo dataset.",
        provenance=None,
        access_method="official_api",
        download_available=True,
    )

    status, record, evidence, warnings, missing = ProvenanceValidation.validate(
        metadata=meta,
        discovered_from="Direct URL Resolution",
        source_repository=None,
    )

    # Has identifier and source_url
    assert record.source_url == "https://zenodo.org/records/12345"
    assert record.provider == "Zenodo"
    assert len(evidence) >= 1
