"""Messages the TeamReady agents send each other over uAgents."""
from uagents import Model


class KnowledgeRequest(Model):
    request_id: str
    question: str
    user: dict


class KnowledgeResponse(Model):
    request_id: str
    result: dict


class RoutingRequest(Model):
    request_id: str
    question: str
    user: dict
    retrieved_doc_ids: list[str]
    exclude: list[str] = []


class RoutingResponse(Model):
    request_id: str
    result: dict


class WrongPersonFeedback(Model):
    person_id: str
    topic_key: str


class ApprovalRequest(Model):
    request_id: str
    category: str
    requester: dict
    subject: str
    body: str
    evidence: list[str]
    reply_to: str  # orchestrator address to send the decision to


class ApprovalDecision(Model):
    request_id: str
    decision: str  # "approved" | "rejected"
    note: str = ""
    approver: str = ""


class FrictionEvent(Model):
    doc_id: str
    docs_read: list[str]
    resolved: bool


class TrackItem(Model):
    item_id: str
    user: str          # the new hire's chat address, so the Tracker can follow up there
    kind: str          # message_helper | book_1_1 | access_request
    summary: str
    to_name: str
    to_email: str


class TrackResolved(Model):
    item_id: str
    outcome: str       # approved | rejected | answered
