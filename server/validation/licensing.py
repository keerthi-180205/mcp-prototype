"""Deterministic license validation layer for dataset metadata."""

from typing import List, Optional, Tuple
from server.models import DatasetMetadata, EvidenceRecord


class LicenseValidation:
    """Evaluates explicit license declarations from platform metadata."""

    @staticmethod
    def validate(
        metadata: DatasetMetadata,
    ) -> Tuple[str, Optional[str], List[EvidenceRecord], List[str], List[str]]:
        """Validate dataset license metadata deterministically.

        Returns:
            Tuple of (license_status, license_name, evidence_list, warnings_list, missing_info_list)
        """
        evidence: List[EvidenceRecord] = []
        warnings: List[str] = []
        missing_info: List[str] = []

        raw_license = metadata.license

        if raw_license and str(raw_license).strip().lower() not in ("none", "null", "unknown", "unspecified"):
            clean_license = str(raw_license).strip()
            license_status = "documented"
            license_name = clean_license

            evidence.append(
                EvidenceRecord(
                    field="license",
                    value=clean_license,
                    source=metadata.source_url,
                    evidence_type="platform_license_metadata",
                )
            )

            # Informational cautions on common license scopes (NOT a legal decision)
            lic_lower = clean_license.lower()
            if any(term in lic_lower for term in ("-nc", "non-commercial", "noncommercial", "research")):
                warnings.append(
                    f"Dataset license '{clean_license}' contains non-commercial or academic research restrictions."
                )
            elif "other" in lic_lower:
                warnings.append(
                    f"Dataset license is listed as '{clean_license}'. Review original repository or documentation for bespoke terms."
                )

        else:
            license_status = "missing"
            license_name = None
            warnings.append("No explicit license declaration found in dataset metadata.")
            missing_info.append("Explicit dataset license")

        return license_status, license_name, evidence, warnings, missing_info
