from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class StoredConversationMessage:
    conversation_id: str
    role: str
    content: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StoredConversation:
    conversation_id: str
    title: str
    messages: tuple[StoredConversationMessage, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConversationRepositoryResult:
    conversation_id: str
    message_count: int


class ConversationRepository:
    """SQL-backed conversation repository placeholder for Milestone 2F.

    The repository keeps the data model aligned with the later chat/chat-history
    features while remaining easy to replace with a real pyodbc implementation.
    """

    def __init__(self) -> None:
        self._conversations: dict[str, StoredConversation] = {}

    def upsert_conversation(self, conversation: StoredConversation) -> ConversationRepositoryResult:
        self._conversations[conversation.conversation_id] = conversation
        return ConversationRepositoryResult(
            conversation_id=conversation.conversation_id,
            message_count=len(conversation.messages),
        )

    def append_message(self, conversation_id: str, message: StoredConversationMessage) -> ConversationRepositoryResult:
        existing = self._conversations.get(
            conversation_id,
            StoredConversation(conversation_id=conversation_id, title=conversation_id),
        )
        updated_messages = existing.messages + (message,)
        updated = StoredConversation(
            conversation_id=existing.conversation_id,
            title=existing.title,
            messages=updated_messages,
            created_at=existing.created_at,
            updated_at=datetime.now(timezone.utc),
            metadata=existing.metadata,
        )
        self._conversations[conversation_id] = updated
        return ConversationRepositoryResult(conversation_id=conversation_id, message_count=len(updated_messages))

    def get_conversation(self, conversation_id: str) -> StoredConversation | None:
        return self._conversations.get(conversation_id)

    def list_conversations(self) -> tuple[StoredConversation, ...]:
        return tuple(self._conversations.values())

    def delete_conversation(self, conversation_id: str) -> bool:
        return self._conversations.pop(conversation_id, None) is not None

    def add_messages(self, conversation_id: str, messages: Iterable[StoredConversationMessage]) -> ConversationRepositoryResult:
        result = ConversationRepositoryResult(conversation_id=conversation_id, message_count=0)
        for message in messages:
            result = self.append_message(conversation_id, message)
        return result
