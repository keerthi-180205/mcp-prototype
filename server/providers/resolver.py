"""Deterministic URL to provider and identifier resolution."""

import re
from typing import Optional, Tuple
from urllib.parse import urlparse


def resolve_dataset_provider(url: str) -> Tuple[str, Optional[str]]:
    """Deterministically parse a dataset URL into its platform and platform-specific identifier.

    Args:
        url: Full URL pointing to a dataset resource.

    Returns:
        A tuple of (platform, identifier).
        Platform is one of: 'huggingface', 'kaggle', 'zenodo', or 'unknown'.
        Identifier is the extracted platform key (e.g. 'owner/dataset' or '123456'), or None.
    """
    if not url or not isinstance(url, str):
        return "unknown", None

    clean_url = url.strip()
    try:
        parsed = urlparse(clean_url)
        domain = parsed.netloc.lower()
        path = parsed.path.strip("/")
    except Exception:
        return "unknown", None

    # 1. Hugging Face: huggingface.co/datasets/{owner}/{name} or hf.co/datasets/{owner}/{name}
    if "huggingface.co" in domain or "hf.co" in domain:
        # Match /datasets/owner/name or /datasets/name
        match = re.search(r"^datasets/([^/]+(?:/[^/]+)?)(?:/.*)?$", path)
        if match:
            return "huggingface", match.group(1)
        # If path is directly owner/name without /datasets/
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] != "models":
            return "huggingface", f"{parts[0]}/{parts[1]}"
        return "huggingface", path or None

    # 2. Kaggle: kaggle.com/datasets/{owner}/{name}
    if "kaggle.com" in domain:
        match = re.search(r"^(?:datasets/)?([^/]+/[^/]+)(?:/.*)?$", path)
        if match:
            return "kaggle", match.group(1)
        return "kaggle", path or None

    # 3. Zenodo: zenodo.org/records/{id} or zenodo.org/record/{id}
    if "zenodo.org" in domain:
        match = re.search(r"records?/(\d+)", path)
        if match:
            return "zenodo", match.group(1)
        return "zenodo", None

    # 4. DOI resolution e.g. doi.org/10.5281/zenodo.{id}
    if "doi.org" in domain and "zenodo." in path:
        match = re.search(r"zenodo\.(\d+)", path)
        if match:
            return "zenodo", match.group(1)

    return "unknown", None
