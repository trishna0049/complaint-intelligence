"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.models.auth import AuditLog, RefreshToken
from app.models.org import ROLES, Category, Department, Team, User
from app.models.retrieval import KnowledgeArticle, TicketEmbedding
from app.models.ticket import (
    CUSTOMER_CODE_SEQ,
    TICKET_NUMBER_SEQ,
    AIAnalysis,
    Customer,
    Ticket,
    TicketAttachment,
    TicketComment,
    TicketEvent,
)

__all__ = [
    "CUSTOMER_CODE_SEQ",
    "ROLES",
    "TICKET_NUMBER_SEQ",
    "AIAnalysis",
    "AuditLog",
    "Category",
    "Customer",
    "Department",
    "KnowledgeArticle",
    "RefreshToken",
    "Team",
    "Ticket",
    "TicketAttachment",
    "TicketComment",
    "TicketEmbedding",
    "TicketEvent",
    "User",
]
