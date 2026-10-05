"""Base abstraction for repository and external dataset data providers."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from server.models import DatasetCandidate, DatasetMetadata, RepositoryCandidate


class RepositoryProvider(ABC):
    """Abstract base class for repository and dataset discovery providers."""

    @abstractmethod
    async def search_repositories(
        self,
        query: str,
        limit: int = 20,
        updated_after: Optional[str] = None,
        language: Optional[str] = None,
    ) -> List[RepositoryCandidate]:
        """Search for repositories matching the query and filtering criteria."""
        pass

    @abstractmethod
    async def get_repository_readme(
        self,
        owner: str,
        repository: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch repository README metadata and decoded text content.

        Returns:
            Dict containing 'name', 'path', 'size', 'html_url', and decoded 'content',
            or None if no README is found.
        """
        pass

    @abstractmethod
    async def inspect_repository_resources(
        self,
        owner: str,
        repository: str,
    ) -> List[DatasetCandidate]:
        """Inspect repository resources and documentation to discover dataset candidates."""
        pass


class DatasetProvider(ABC):
    """Abstract base class for external dataset connectors (e.g. Hugging Face, Kaggle, Zenodo)."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Name of the external platform handled by this provider."""
        pass

    @abstractmethod
    async def get_dataset_metadata(
        self,
        identifier: str,
    ) -> DatasetMetadata:
        """Retrieve normalized metadata for a specific dataset identifier using official platform APIs.

        Args:
            identifier: Platform-specific dataset identifier (e.g. 'owner/dataset' or '123456').

        Returns:
            DatasetMetadata normalized representation.
        """
        pass
