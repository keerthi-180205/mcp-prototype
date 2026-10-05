"""Deterministic provenance and retrieval chain tracking."""

from datetime import datetime, timezone
from typing import List, Optional, Tuple
from server.models import DatasetMetadata, EvidenceRecord, ProvenanceRecord


class ProvenanceValidation:
    """Evaluates and records the discovery and origin chain for a dataset."""

    @staticmethod
    def validate(
        metadata: DatasetMetadata,
        discovered_from: Optional[str] = None,
        source_repository: Optional[str] = None,
    ) -> Tuple[str, ProvenanceRecord, List[EvidenceRecord], List[str], List[str]]:
        """Validate dataset provenance and build structured ProvenanceRecord.

        Returns:
            Tuple of (provenance_status, provenance_record, evidence_list, warnings_list, missing_info_list)
        """
        evidence: List[EvidenceRecord] = []
        warnings: List[str] = []
        missing_info: List[str] = []

        retrieved_at = datetime.now(timezone.utc).isoformat()
        access_method = metadata.access_method or "official_api"
        discovery_source = discovered_from or "Direct URL Resolution"

        provenance_rec = ProvenanceRecord(
            discovered_from=discovery_source,
            source_repository=source_repository,
            source_url=metadata.source_url,
            provider=metadata.source_platform,
            access_method=access_method,
            retrieved_at=retrieved_at,
        )

        evidence.append(
            EvidenceRecord(
                field="provenance",
                value=f"Retrieved from {metadata.source_platform} via {access_method} (Source: {metadata.source_url})",
                source=metadata.source_url,
                evidence_type="provenance_chain",
            )
        )

        if metadata.provenance:
            evidence.append(
                EvidenceRecord(
                    field="attribution",
                    value=metadata.provenance,
                    source=metadata.source_url,
                    evidence_type="author_attribution",
                )
            )

        # Assess provenance completeness
        has_url = bool(metadata.source_url)
        has_platform = bool(metadata.source_platform and metadata.source_platform != "unknown")
        has_attribution = bool(metadata.provenance or source_repository or metadata.identifier)

        if has_url and has_platform and has_attribution:
            provenance_status = "documented"
        elif has_url and has_platform:
            provenance_status = "partial"
            warnings.append("Partial provenance: original dataset author/creator attribution is not explicitly declared.")
            missing_info.append("Creator / author attribution")
        else:
            provenance_status = "unknown"
            warnings.append("Incomplete provenance: primary hosting origin could not be fully verified.")
            missing_info.append("Complete provenance chain")

        return provenance_status, provenance_rec, evidence, warnings, missing_info
