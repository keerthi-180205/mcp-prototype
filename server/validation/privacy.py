"""Deterministic privacy and sensitive-data analysis for dataset documentation."""

import re
from typing import List, Optional, Tuple
from server.models import DatasetMetadata, EvidenceRecord


class PrivacyValidation:
    """Evaluates explicit privacy, de-identification, and sensitive-data warnings in dataset documentation."""

    # Patterns indicating dataset-level de-identification (NOT general discussions of privacy)
    DEIDENTIFIED_PATTERNS = [
        re.compile(r"\b(?:all\s+)?(?:records|data|transcripts|conversations|participants|responses)\s+(?:were|are|have been)\s+de-?identified\b", re.I),
        re.compile(r"\bde-?identified\s+(?:survey|dataset|data|corpus|records|transcripts|responses)\b", re.I),
        re.compile(r"\b(?:pii|personally\s+identifiable\s+information)\s+(?:was|were|has\s+been|have\s+been)?\s*removed\b", re.I),
        re.compile(r"\b(?:contains?\s+)?no\s+personally\s+identifiable\s+information\b", re.I),
    ]

    # Patterns indicating explicit anonymization
    ANONYMIZED_PATTERNS = [
        re.compile(r"\b(?:all\s+)?(?:records|data|transcripts|conversations|participants|responses)\s+(?:were|are|have been)\s+anonymi[zs]ed\b", re.I),
        re.compile(r"\banonymi[zs]ed\s+(?:dataset|data|corpus|dialogues?|conversations?|transcripts?|responses)\b", re.I),
        re.compile(r"\bexplicitly\s+anonymi[zs]ed\b", re.I),
    ]

    # Patterns indicating explicit sensitive data warnings (requires sensitive + data/personal/mental health context)
    SENSITIVE_WARNING_PATTERNS = [
        re.compile(r"\b(?:contains?\s+)?sensitive\s+(?:personal|mental[\s\-_]health|health|medical|patient|clinical|data|content|information)\b", re.I),
        re.compile(r"\b(?:suicid\w*|self[\s\-_]harm|distress\s+warning|trigger\s+warning|crisis\s+content)\b", re.I),
        re.compile(r"\bconfidential\s+(?:medical|clinical|personal|patient)\s+(?:data|information|records)\b", re.I),
    ]

    @classmethod
    def validate(
        cls,
        metadata: DatasetMetadata,
    ) -> Tuple[str, Optional[bool], Optional[bool], Optional[bool], List[EvidenceRecord], List[str], List[str]]:
        """Run deterministic privacy and sensitivity analysis.

        Returns:
            Tuple of:
            (privacy_status, explicitly_deidentified, explicitly_anonymized,
             contains_sensitive_data_warning, evidence_list, warnings_list, missing_info_list)
        """
        evidence: List[EvidenceRecord] = []
        warnings: List[str] = []
        missing_info: List[str] = []

        # Aggregate all documented text fields
        text_fields = [
            ("description", metadata.description or ""),
            ("notes", metadata.notes or ""),
            ("tags", " ".join(metadata.tags)),
            ("provenance", metadata.provenance or ""),
        ]

        explicitly_deidentified: Optional[bool] = None
        explicitly_anonymized: Optional[bool] = None
        contains_sensitive_data_warning: Optional[bool] = None

        # Check existing metadata fields (from Phase 4/5 extraction)
        if metadata.explicitly_deidentified is True:
            explicitly_deidentified = True
        if metadata.explicitly_anonymized is True:
            explicitly_anonymized = True
        if metadata.contains_sensitive_data_warning is True:
            contains_sensitive_data_warning = True

        # Perform deterministic pattern search over documentation text
        for field_name, text in text_fields:
            if not text:
                continue

            # 1. De-identification
            if explicitly_deidentified is not True:
                for pat in cls.DEIDENTIFIED_PATTERNS:
                    match = pat.search(text)
                    if match:
                        explicitly_deidentified = True
                        evidence.append(
                            EvidenceRecord(
                                field="deidentified",
                                value=f"Dataset documentation states: '{match.group(0)}'",
                                source=metadata.source_url,
                                evidence_type="documentation_statement",
                            )
                        )
                        break

            # 2. Anonymization
            if explicitly_anonymized is not True:
                for pat in cls.ANONYMIZED_PATTERNS:
                    match = pat.search(text)
                    if match:
                        explicitly_anonymized = True
                        evidence.append(
                            EvidenceRecord(
                                field="anonymized",
                                value=f"Dataset documentation states: '{match.group(0)}'",
                                source=metadata.source_url,
                                evidence_type="documentation_statement",
                            )
                        )
                        break

            # 3. Sensitive data warning
            if contains_sensitive_data_warning is not True:
                for pat in cls.SENSITIVE_WARNING_PATTERNS:
                    match = pat.search(text)
                    if match:
                        contains_sensitive_data_warning = True
                        evidence.append(
                            EvidenceRecord(
                                field="sensitive_data_warning",
                                value=f"Documentation contains explicit warning: '{match.group(0)}'",
                                source=metadata.source_url,
                                evidence_type="documentation_warning",
                            )
                        )
                        break

        # Determine overall privacy_status
        if explicitly_deidentified:
            privacy_status = "explicitly_deidentified"
        elif explicitly_anonymized:
            privacy_status = "explicitly_anonymized"
        elif contains_sensitive_data_warning:
            privacy_status = "sensitive_data_warning"
        else:
            privacy_status = "no_statement_found"

        # Warnings and missing information
        if contains_sensitive_data_warning:
            warnings.append(
                "Documentation explicitly mentions sensitive mental health, medical, or crisis content."
            )

        if not explicitly_deidentified and not explicitly_anonymized:
            warnings.append(
                "No explicit dataset-level de-identification or anonymization statement was found in documented metadata."
            )
            missing_info.append("Explicit privacy/de-identification statement")

        return (
            privacy_status,
            explicitly_deidentified,
            explicitly_anonymized,
            contains_sensitive_data_warning,
            evidence,
            warnings,
            missing_info,
        )
