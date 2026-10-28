from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
import re
import unicodedata
from uuid import uuid4


class GraphEntityType(StrEnum):
    COMPANY = "company"
    PERSON = "person"
    ERP_OBJECT = "erp_object"
    TABLE = "table"
    VIEW = "view"
    PROCEDURE = "procedure"
    FUNCTION = "function"
    TRIGGER = "trigger"
    COLUMN = "column"
    ENDPOINT = "endpoint"
    CLASS = "class"
    METHOD = "method"
    LIBRARY = "library"
    FRAMEWORK = "framework"
    PROJECT = "project"
    MODULE = "module"
    CONFIGURATION = "configuration"
    PRODUCT = "product"
    VERSION = "version"
    DOCUMENT = "document"
    INVOICE = "invoice"
    ORDER = "order"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    COUNTRY = "country"
    LOCATION = "location"
    LANGUAGE = "language"
    TECHNOLOGY = "technology"
    UNKNOWN = "unknown"


class GraphRelationshipType(StrEnum):
    CALLS = "CALLS"
    USES = "USES"
    READS_FROM = "READS_FROM"
    WRITES_TO = "WRITES_TO"
    CONTAINS = "CONTAINS"
    MENTIONS = "MENTIONS"
    DEPENDS_ON = "DEPENDS_ON"
    IMPLEMENTS = "IMPLEMENTS"
    EXTENDS = "EXTENDS"
    RETURNS = "RETURNS"
    PARAMETER = "PARAMETER"
    BELONGS_TO = "BELONGS_TO"
    GENERATES = "GENERATES"
    CREATES = "CREATES"
    UPDATES = "UPDATES"
    DELETES = "DELETES"
    EXECUTES = "EXECUTES"
    REFERENCES = "REFERENCES"


@dataclass(frozen=True, slots=True)
class EntityMention:
    name: str
    entity_type: GraphEntityType = GraphEntityType.UNKNOWN
    confidence: float = 0.8
    description: str | None = None
    aliases: tuple[str, ...] = ()
    properties: dict[str, str] = field(default_factory=dict)
    evidence: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Entity names cannot be empty.")
        if not 0 <= self.confidence <= 1:
            raise ValueError("Entity confidence must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class RelationshipMention:
    source_name: str
    target_name: str
    relationship_type: GraphRelationshipType
    confidence: float
    source_type: GraphEntityType = GraphEntityType.UNKNOWN
    target_type: GraphEntityType = GraphEntityType.UNKNOWN
    evidence: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("Relationship confidence must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class GraphEntity:
    entity_id: str
    name: str
    normalized_name: str
    entity_type: GraphEntityType
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
    properties: dict[str, str] = field(default_factory=dict)
    source_document_ids: tuple[str, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_mention(cls, mention: EntityMention) -> GraphEntity:
        return cls(
            entity_id=str(uuid4()),
            name=mention.name.strip(),
            normalized_name=normalize_entity_name(mention.name),
            entity_type=mention.entity_type,
            description=mention.description,
            metadata={"confidence": mention.confidence, "evidence": mention.evidence},
            aliases=mention.aliases,
            properties=mention.properties,
        )


@dataclass(frozen=True, slots=True)
class GraphRelationship:
    relationship_id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: GraphRelationshipType
    confidence: float
    source_document_id: str | None = None
    evidence: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GraphStatistics:
    entity_count: int
    relationship_count: int
    entity_types: dict[str, int]
    most_connected: tuple[tuple[str, int], ...]
    orphan_entity_count: int
    average_degree: float


@dataclass(frozen=True, slots=True)
class GraphDocument:
    document_id: str
    source_path: str
    entities: tuple[GraphEntity, ...] = ()
    relationships: tuple[GraphRelationship, ...] = ()


def normalize_entity_name(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(char for char in folded if not unicodedata.combining(char))
    normalized = re.sub(r"[^\w]+", " ", ascii_text.replace("_", " "))
    normalized = " ".join(normalized.split())
    return {
        "sqlserver": "sql server",
        "microsoft sql server": "sql server",
    }.get(normalized, normalized)