import logging
from typing import List, Optional
from server.models import DatasetMetadata, DatasetValidationResult, EvidenceRecord
from server.validation.licensing import LicenseValidation
from server.validation.privacy import PrivacyValidation
from server.validation.provenance import ProvenanceValidation

logger = logging.getLogger(__name__)


class DatasetValidator:
    """Deterministic, evidence-based validation engine for dataset metadata."""

    def validate(
        self,
        metadata: DatasetMetadata,
        discovered_from: Optional[str] = None,
        source_repository: Optional[str] = None,
    ) -> DatasetValidationResult:
        """Run complete deterministic validation suite on dataset metadata.

        Args:
            metadata: Normalized DatasetMetadata object.
            discovered_from: Optional discovery origin (e.g. 'GitHub README').
            source_repository: Optional GitHub repository full name (e.g. 'owner/repo').

        Returns:
            DatasetValidationResult containing documented facts, evidence, and warnings.
        """
        all_evidence: List[EvidenceRecord] = []
        all_warnings: List[str] = []
        all_missing_info: List[str] = []

        # 1. License Validation
        lic_status, lic_name, lic_ev, lic_warn, lic_miss = LicenseValidation.validate(metadata)
        all_evidence.extend(lic_ev)
        all_warnings.extend(lic_warn)
        all_missing_info.extend(lic_miss)
        if lic_status == "documented":
            logger.info("[VALIDATION] License documented: %s", lic_name)
        else:
            logger.info("[VALIDATION] License missing or undocumented")

        # 2. Privacy & Sensitivity Validation
        (
            priv_status,
            explicitly_deid,
            explicitly_anon,
            has_sensitive_warn,
            priv_ev,
            priv_warn,
            priv_miss,
        ) = PrivacyValidation.validate(metadata)
        all_evidence.extend(priv_ev)
        all_warnings.extend(priv_warn)
        all_missing_info.extend(priv_miss)
        if priv_status in ("explicitly_deidentified", "explicitly_anonymized"):
            logger.info("[VALIDATION] Privacy documented: %s", priv_status)
        elif priv_status == "sensitive_data_warning":
            logger.info("[VALIDATION] Sensitive data warning detected in documentation")
        else:
            logger.info("[VALIDATION] Privacy statement not found")

        # 3. Provenance Validation
        prov_status, prov_rec, prov_ev, prov_warn, prov_miss = ProvenanceValidation.validate(
            metadata,
            discovered_from=discovered_from,
            source_repository=source_repository,
        )
        all_evidence.extend(prov_ev)
        all_warnings.extend(prov_warn)
        all_missing_info.extend(prov_miss)
        logger.info("[VALIDATION] Provenance status: %s (Source: %s)", prov_status, metadata.source_platform)

        # 4. Access Status & Documentation Completeness
        if metadata.access_method == "gated_access":
            access_status = "restricted"
            all_warnings.append("Dataset requires approval or gated access before files can be requested.")
        elif metadata.source_platform == "Kaggle" and metadata.access_method == "official_api":
            access_status = "authenticated"
        elif metadata.download_available:
            access_status = "public_metadata"
        else:
            access_status = "unknown"

        doc_available = bool(metadata.description and len(metadata.description.strip()) > 15)
        if not doc_available:
            all_warnings.append("Dataset description/documentation is brief or missing from metadata.")
            all_missing_info.append("Detailed dataset documentation")

        # 5. Overall Validation Status
        if lic_status == "documented" and doc_available and (explicitly_deid or explicitly_anon):
            validation_status = "documented"
        elif lic_status == "documented" or doc_available:
            validation_status = "incomplete"
        else:
            validation_status = "unknown"

        logger.info("[VALIDATION] Dataset '%s' validation status: %s", metadata.name, validation_status)

        return DatasetValidationResult(
            dataset_name=metadata.name,
            source_platform=metadata.source_platform,
            source_url=metadata.source_url,
            validation_status=validation_status,
            license_status=lic_status,
            license_name=lic_name,
            privacy_status=priv_status,
            explicitly_deidentified=explicitly_deid,
            explicitly_anonymized=explicitly_anon,
            contains_sensitive_data_warning=has_sensitive_warn,
            provenance_status=prov_status,
            provenance=prov_rec,
            access_status=access_status,
            documentation_available=doc_available,
            evidence=all_evidence,
            warnings=all_warnings,
            missing_information=all_missing_info,
            notes=metadata.notes,
        )
