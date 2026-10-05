"""Data models for repository metadata, dataset candidates, external dataset metadata, and validation results."""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class RepositoryCandidate(BaseModel):
    """Normalized representation of a repository discovered from a data provider."""

    id: int = Field(description="Unique repository identifier")
    name: str = Field(description="Repository name")
    full_name: str = Field(description="Full repository name including owner (owner/repo)")
    owner: str = Field(description="Repository owner username or organization")
    owner_type: str = Field(default="User", description="Type of owner (e.g. User, Organization)")
    description: Optional[str] = Field(default=None, description="Repository description or summary")
    html_url: str = Field(description="Web URL to the repository")
    api_url: str = Field(description="REST API URL to the repository")
    language: Optional[str] = Field(default=None, description="Primary programming language")
    topics: List[str] = Field(default_factory=list, description="Repository topic tags")
    stars: int = Field(default=0, description="Number of stargazers")
    forks: int = Field(default=0, description="Number of forks")
    open_issues: int = Field(default=0, description="Number of open issues")
    created_at: str = Field(description="ISO timestamp when the repository was created")
    updated_at: str = Field(description="ISO timestamp when the repository was last updated")
    pushed_at: Optional[str] = Field(default=None, description="ISO timestamp of the most recent push")
    license: Optional[str] = Field(default=None, description="License SPDX identifier or name")
    default_branch: str = Field(default="main", description="Default branch name")
    archived: bool = Field(default=False, description="Whether the repository is archived")
    fork: bool = Field(default=False, description="Whether the repository is a fork")
    source: str = Field(default="github", description="Source platform provenance identifier")


class DatasetCandidate(BaseModel):
    """Normalized candidate representing a mental-health dataset or data resource reference."""

    name: str = Field(description="Name or title of the dataset/resource")
    description: Optional[str] = Field(default=None, description="Description or context of the dataset")
    data_type: str = Field(
        default="unknown",
        description="Classified data type (e.g. conversation, text, survey, emotion, mental_health_assessment, research_data, multimodal, unknown)",
    )
    source_repository: str = Field(description="Full name of source repository (owner/repo)")
    source_repository_url: str = Field(description="URL to the source GitHub repository")
    dataset_url: Optional[str] = Field(
        default=None, description="URL pointing to the dataset resource or download location"
    )
    source_platform: str = Field(
        default="unknown",
        description="Detected hosting platform (e.g. Hugging Face, Kaggle, Zenodo, Figshare, OSF, Google Drive, GitHub, unknown)",
    )
    license: Optional[str] = Field(
        default=None, description="License information explicitly identified for the dataset or repository"
    )
    access_method: str = Field(
        default="unknown",
        description="Method of accessing data (e.g. external_link, repository_files, request_form, unknown)",
    )
    discovered_from: str = Field(
        default="README", description="Document source from which the reference was discovered"
    )
    privacy_status: str = Field(
        default="unknown",
        description="Explicit privacy status (explicitly_deidentified, explicitly_anonymized, contains_sensitive_data_warning, unknown)",
    )
    confidence: str = Field(
        default="medium", description="Confidence level of identification (high, medium, low)"
    )
    notes: Optional[str] = Field(default=None, description="Contextual notes or extraction justification")


class DatasetMetadata(BaseModel):
    """Normalized metadata for a verified external dataset obtained via official platform APIs."""

    name: str = Field(description="Name or title of the dataset")
    description: Optional[str] = Field(default=None, description="Detailed dataset description")

    source_platform: str = Field(description="Hosting platform (e.g. Hugging Face, Kaggle, Zenodo)")
    source_url: str = Field(description="Canonical URL to the dataset on the platform")

    identifier: Optional[str] = Field(
        default=None, description="Platform-specific identifier (e.g. owner/dataset-name or record_id)"
    )

    data_type: str = Field(default="unknown", description="Categorized data type")
    format: Optional[str] = Field(default=None, description="File formats (e.g. csv, json, parquet, audio)")
    language: Optional[str] = Field(default=None, description="Primary language of the dataset")

    license: Optional[str] = Field(default=None, description="License explicitly declared by the platform")

    created_at: Optional[str] = Field(default=None, description="Creation timestamp")
    updated_at: Optional[str] = Field(default=None, description="Last modification timestamp")

    access_method: Optional[str] = Field(
        default=None, description="Access method (e.g. official_api, direct_download, request_access)"
    )

    download_available: bool = Field(
        default=False, description="Whether files are accessible for download via official API/endpoint"
    )

    size_bytes: Optional[int] = Field(default=None, description="Total size in bytes if available")

    tags: List[str] = Field(default_factory=list, description="Platform tags and keywords")

    explicitly_deidentified: Optional[bool] = Field(
        default=None, description="Explicit statement that data is de-identified"
    )
    explicitly_anonymized: Optional[bool] = Field(
        default=None, description="Explicit statement that data is anonymized"
    )
    contains_sensitive_data_warning: Optional[bool] = Field(
        default=None, description="Explicit warning about sensitive content"
    )

    provenance: Optional[str] = Field(default=None, description="Original source or citation if declared")
    notes: Optional[str] = Field(default=None, description="Additional metadata or inspection notes")


class EvidenceRecord(BaseModel):
    """Documented evidence backing a validation assessment."""

    field: str = Field(description="The attribute this evidence pertains to (e.g. license, deidentified, sensitive_data)")
    value: str = Field(description="The observed factual statement or value")
    source: str = Field(description="Origin source URL or document where the evidence was located")
    evidence_type: str = Field(description="Evidence classification (e.g. official_api_metadata, documentation, explicit_statement)")


class ProvenanceRecord(BaseModel):
    """Detailed origin and discovery chain record for a dataset."""

    discovered_from: Optional[str] = Field(default=None, description="Initial discovery origin (e.g. GitHub README, Direct URL)")
    source_repository: Optional[str] = Field(default=None, description="GitHub repository full name if discovered via repository")
    source_url: str = Field(description="Canonical platform URL where dataset was located")
    provider: str = Field(description="Connector or platform name (e.g. Hugging Face, Kaggle, Zenodo)")
    access_method: str = Field(description="Protocol or access mechanism used (e.g. official_api)")
    retrieved_at: str = Field(description="ISO timestamp when metadata was retrieved")


class DatasetValidationResult(BaseModel):
    """Deterministic, evidence-based validation result for a dataset candidate."""

    dataset_name: str = Field(description="Name or title of the dataset")
    source_platform: str = Field(description="Hosting platform (e.g. Hugging Face, Kaggle, Zenodo)")
    source_url: str = Field(description="Canonical URL to the dataset")

    validation_status: str = Field(
        description="Overall validation completeness ('documented', 'incomplete', 'unknown')"
    )

    license_status: str = Field(description="License status ('documented', 'missing', 'unknown')")
    license_name: Optional[str] = Field(default=None, description="Documented license name or SPDX identifier")

    privacy_status: str = Field(
        description="Privacy classification ('explicitly_deidentified', 'explicitly_anonymized', 'sensitive_data_warning', 'no_statement_found', 'unknown')"
    )

    explicitly_deidentified: Optional[bool] = Field(
        default=None, description="True if documentation explicitly confirms de-identification, else None"
    )
    explicitly_anonymized: Optional[bool] = Field(
        default=None, description="True if documentation explicitly confirms anonymization, else None"
    )
    contains_sensitive_data_warning: Optional[bool] = Field(
        default=None, description="True if documentation contains an explicit warning on sensitive content, else None"
    )

    provenance_status: str = Field(description="Provenance completeness ('documented', 'partial', 'unknown')")
    provenance: Optional[ProvenanceRecord] = Field(default=None, description="Origin and retrieval chain details")

    access_status: str = Field(description="Observed access model ('public_metadata', 'authenticated', 'restricted', 'unknown')")
    documentation_available: bool = Field(default=False, description="Whether dataset documentation / description was found")

    evidence: List[EvidenceRecord] = Field(default_factory=list, description="List of factual evidence records backing validation")
    warnings: List[str] = Field(default_factory=list, description="Informational cautions and limitations found during analysis")
    missing_information: List[str] = Field(default_factory=list, description="Key attributes that could not be verified from documented sources")
    notes: Optional[str] = Field(default=None, description="Additional context or validation notes")


class DatasetSummary(BaseModel):
    """Structured concise summary generated by Gemini based on documented metadata."""

    summary: str = Field(description="Objective synthesis of the dataset based strictly on documented facts")
    data_type: str = Field(description="Primary format or structure of the data")
    purpose: str = Field(description="Documented purpose or research goal of the dataset")
    likely_category: Optional[str] = Field(default=None, description="Likely research or usage category")
    language: Optional[str] = Field(default=None, description="Documented language(s) or unknown")
    source: Optional[str] = Field(default=None, description="Platform source and host")
    documented_privacy: str = Field(description="Factual summary of documented privacy/de-identification statements")
    documented_license: str = Field(description="Documented license and associated scope notes")
    limitations: List[str] = Field(default_factory=list, description="Known limitations or missing metadata explicitly noted")


class DatasetCategoryClassification(BaseModel):
    """Gemini-assisted categorization preserving the original deterministic data_type."""

    deterministic_type: str = Field(description="Original deterministic data_type from source metadata")
    gemini_category: str = Field(
        description="Suggested category (conversation, text, survey, emotion, sentiment, mental_health_assessment, research_data, multimodal, other, unknown)"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the categorization interpretation (0.0 to 1.0)")
    reason: str = Field(description="Factual explanation based on documented metadata description/tags")


class DatasetRelevance(BaseModel):
    """Evaluation of dataset relevance to mental-health research (NOT a safety or legal score)."""

    relevance: str = Field(description="Relevance rating ('high', 'medium', 'low', 'unknown')")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the relevance assessment (0.0 to 1.0)")
    reason: str = Field(description="Factual explanation grounded strictly in the provided metadata")


class DatasetReport(BaseModel):
    """Comprehensive human-readable dataset report combining deterministic facts and Gemini interpretation."""

    dataset_name: str = Field(description="Dataset name")
    source_platform: str = Field(description="Platform source")
    purpose: str = Field(description="Documented purpose")
    data_type: str = Field(description="Data type")
    language: Optional[str] = Field(default=None, description="Documented language")
    license: str = Field(description="Documented license")
    privacy_documentation: str = Field(description="Documented privacy/de-identification statements")
    access_method: str = Field(description="Access method")
    provenance: str = Field(description="Provenance chain details")
    warnings: List[str] = Field(default_factory=list, description="Warnings and cautions")
    missing_information: List[str] = Field(default_factory=list, description="Missing information")
    relevance: str = Field(description="Mental-health relevance rating and reasoning")
    notes: Optional[str] = Field(default=None, description="Additional context")
    formatted_report: str = Field(description="Human-readable formatted text report")


# ==============================================================================
# Instagram & Apify Models
# ==============================================================================

class InstagramAuthor(BaseModel):
    """Author or creator of an Instagram post or reel."""

    id: Optional[str] = Field(default=None, description="Public user or creator ID")
    username: Optional[str] = Field(default=None, description="Instagram username handle")
    display_name: Optional[str] = Field(default=None, description="Public display or full name")


class InstagramPost(BaseModel):
    """Normalized representation of a public Instagram post or reel."""

    platform: str = Field(default="instagram", description="Originating social platform")
    content_type: str = Field(default="reel", description="Media content type (e.g. reel, post)")
    content_id: Optional[str] = Field(default=None, description="Unique post or reel identifier / shortcode")
    url: str = Field(description="Canonical public URL to the Instagram post or reel")
    caption: Optional[str] = Field(default=None, description="Public text caption")
    author: Optional[InstagramAuthor] = Field(default=None, description="Public post author details")
    created_at: Optional[str] = Field(default=None, description="ISO or provider timestamp of creation")
    like_count: int = Field(default=0, description="Public like count")
    comment_count: int = Field(default=0, description="Public comment count")
    view_count: int = Field(default=0, description="Public view or play count")


class InstagramCommentUser(BaseModel):
    """Commenter user profile metadata as publicly returned by the provider."""

    id: Optional[str] = Field(default=None, description="Public commenter ID")
    username: Optional[str] = Field(default=None, description="Public commenter username")
    display_name: Optional[str] = Field(default=None, description="Public display name")
    is_verified: bool = Field(default=False, description="Whether the account is verified")
    is_private: bool = Field(default=False, description="Whether the account is private")
    profile_picture_url: Optional[str] = Field(default=None, description="URL to commenter avatar/profile picture")


class InstagramComment(BaseModel):
    """Normalized representation of a public Instagram comment."""

    comment_id: Optional[str] = Field(default=None, description="Unique comment identifier")
    user: Optional[InstagramCommentUser] = Field(default=None, description="Commenter profile details")
    text: Optional[str] = Field(default=None, description="Comment text body")
    created_at: Optional[str] = Field(default=None, description="Timestamp of the comment")
    like_count: int = Field(default=0, description="Comment like count")
    reply_count: int = Field(default=0, description="Comment reply count")


class InstagramCommentsResult(BaseModel):
    """Collection of comments extracted for a specific public Instagram URL."""

    platform: str = Field(default="instagram", description="Platform identifier")
    content_url: str = Field(description="URL of the post or reel")
    comments: List[InstagramComment] = Field(default_factory=list, description="Extracted public comments")


class InstagramTopicPostContent(BaseModel):
    """Concise post content summary for topic research results."""

    url: str = Field(description="Public post or reel URL")
    type: str = Field(default="reel", description="Content type (reel, post)")
    caption: Optional[str] = Field(default=None, description="Post caption")
    author: Optional[InstagramAuthor] = Field(default=None, description="Post author")
    created_at: Optional[str] = Field(default=None, description="Post creation timestamp")


class InstagramTopicPostResult(BaseModel):
    """Post content bundled with extracted comments for end-to-end research."""

    content: InstagramTopicPostContent = Field(description="Post or reel metadata")
    comments: List[InstagramComment] = Field(default_factory=list, description="Extracted comments")


class InstagramTopicResearchResult(BaseModel):
    """Aggregated topic research result across multiple posts and their comments."""

    query: str = Field(description="Search topic query")
    platform: str = Field(default="instagram", description="Platform identifier")
    results: List[InstagramTopicPostResult] = Field(default_factory=list, description="Discovered posts with comments")


# =====================================================================
# Universal Multi-Platform Social Intelligence Data Models
# =====================================================================


class SocialAuthor(BaseModel):
    """Normalized author profile across any social or public platform."""

    username: Optional[str] = Field(default=None, description="Public username or handle")
    user_id: Optional[str] = Field(default=None, description="Public user ID if available")
    display_name: Optional[str] = Field(default=None, description="Public display name")
    profile_url: Optional[str] = Field(default=None, description="Profile URL")
    is_verified: Optional[bool] = Field(default=None, description="Whether the profile is verified")
    is_private: Optional[bool] = Field(default=None, description="Whether the profile is marked private")


class SocialContent(BaseModel):
    """Normalized text and metadata content."""

    text: Optional[str] = Field(default=None, description="Main text body, transcript or article text")
    title: Optional[str] = Field(default=None, description="Title of video, post or article")
    caption: Optional[str] = Field(default=None, description="Caption of post or reel")
    tags: List[str] = Field(default_factory=list, description="Hashtags or topic tags")


class SocialEngagement(BaseModel):
    """Normalized engagement metrics across platforms."""

    likes: Optional[int] = Field(default=None, description="Public like count")
    comments: Optional[int] = Field(default=None, description="Public comments count")
    views: Optional[int] = Field(default=None, description="Public views/impressions count")
    shares: Optional[int] = Field(default=None, description="Public repost/share count")


class SocialInteraction(BaseModel):
    """Normalized interaction such as comment, reply, or mention."""

    interaction_id: Optional[str] = Field(default=None, description="Unique interaction/comment ID")
    type: str = Field(default="comment", description="Interaction type: comment, reply, quote, mention")
    text: str = Field(description="Interaction text content")
    author: SocialAuthor = Field(default_factory=SocialAuthor, description="Author of the interaction")
    created_at: Optional[str] = Field(default=None, description="ISO timestamp of interaction")
    likes: Optional[int] = Field(default=None, description="Like count on the interaction")


class ProvenanceMetadata(BaseModel):
    """Origin and provenance tracking for acquired data."""

    source_platform: str = Field(description="Social platform name (e.g. instagram, youtube, reddit, etc.)")
    source_provider: str = Field(description="Provider or capability layer (e.g. apify, agent-reach, official_api)")
    backend_tool: Optional[str] = Field(default=None, description="Underlying backend tool (e.g. yt-dlp, jina, opencli)")
    fetched_at: str = Field(description="ISO timestamp when data was retrieved")
    source_url: str = Field(description="Direct public URL to the content")
    provider_metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional provider-specific metadata")


class NormalizedSocialRecord(BaseModel):
    """Unified normalized record representing any social or web interaction."""

    record_id: str = Field(description="Deterministic or UUID record identifier (e.g. platform:content_id)")
    platform: str = Field(description="Social platform: instagram, youtube, reddit, x, github, web, rss")
    content_type: str = Field(description="Type of content: reel, post, video, tweet, issue, discussion, article")
    source_url: str = Field(description="Canonical public URL")
    content_id: str = Field(description="Platform-specific content ID or shortcode")
    published_at: Optional[str] = Field(default=None, description="ISO timestamp when published")
    author: SocialAuthor = Field(default_factory=SocialAuthor, description="Content author details")
    content: SocialContent = Field(default_factory=SocialContent, description="Text, title, caption, and tags")
    engagement: SocialEngagement = Field(default_factory=SocialEngagement, description="Engagement metrics")
    interactions: List[SocialInteraction] = Field(default_factory=list, description="Public comments or replies")
    metadata: ProvenanceMetadata = Field(description="Data provenance metadata")
    relevance_score: Optional[float] = Field(default=None, description="Calculated relevance score (0.0 to 1.0)")


class SocialSearchFilter(BaseModel):
    """Filter parameters for social search operations."""

    topic: str = Field(description="Target search topic, query or keyword")
    date_from: Optional[str] = Field(default=None, description="Start date ISO string")
    date_to: Optional[str] = Field(default=None, description="End date ISO string")
    months_back: Optional[int] = Field(default=3, description="Months back filter (e.g. 3, 4, 6, 12)")
    relevance_threshold: Optional[float] = Field(default=0.0, description="Minimum relevance score threshold (0.0 to 1.0)")
    max_results: int = Field(default=10, description="Maximum results to return")


class SocialPlatformSummary(BaseModel):
    """Summary of data collected per platform."""

    platform: str
    total_records: int
    total_interactions: int
    latest_activity: Optional[str] = None


class SocialIntelligenceReport(BaseModel):
    """Executive cross-platform intelligence report."""

    topic: str
    total_records: int
    total_interactions: int
    platforms_covered: List[SocialPlatformSummary] = Field(default_factory=list)
    top_records: List[NormalizedSocialRecord] = Field(default_factory=list)
    generated_at: str
    summary_notes: Optional[str] = None



