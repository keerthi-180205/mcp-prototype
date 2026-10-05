"""Providers package for external structured data sources and dataset connectors."""

from server.providers.base import DatasetProvider, RepositoryProvider
from server.providers.github import GitHubProvider
from server.providers.huggingface import HuggingFaceProvider
from server.providers.kaggle import KaggleProvider
from server.providers.resolver import resolve_dataset_provider
from server.providers.zenodo import ZenodoProvider

__all__ = [
    "RepositoryProvider",
    "DatasetProvider",
    "GitHubProvider",
    "HuggingFaceProvider",
    "KaggleProvider",
    "ZenodoProvider",
    "resolve_dataset_provider",
]
