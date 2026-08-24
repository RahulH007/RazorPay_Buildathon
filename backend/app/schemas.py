"""
RecoverOS Pydantic Schemas
Request/response models, enums, and JSON schemas for the API layer.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, Field


# --- Enums ---

class FailureClass(str, Enum):
    TRANSIENT_TECHNICAL = "TRANSIENT_TECHNICAL"
    AUTH_FRICTION = "AUTH_FRICTION"
    MANDATE_BALANCE = "MANDATE_BALANCE"
    B2B_RECEIVABLE = "B2B_RECEIVABLE"
    HARD_DECLINE = "HARD_DECLINE"


class RecoveryState(str, Enum):
    INGESTED = "INGESTED"
    DIAGNOSED = "DIAGNOSED"
    INTERVENING = "INTERVENING"
    RECOVERED = "RECOVERED"
    FAILED_STOPPED = "FAILED_STOPPED"


class RecoveryChannel(str, Enum):
    SILENT_RETRY = "silent_retry"
    WHATSAPP_LINK = "whatsapp_link"
    UPI_RESEQUENCE = "upi_resequence"
    HINGLISH_VOICE = "hinglish_voice"
    EMAIL = "email"


class ActorType(str, Enum):
    RULE_ENGINE = "rule_engine"
    LLM_AGENT = "llm_agent"
    SYSTEM = "system"
    CUSTOMER = "customer"


# --- Nested Schemas ---

class CustomerInfo(BaseModel):
    name: str
    email: Optional[str] = None
    phone: str


class ErrorInfo(BaseModel):
    source: Optional[str] = None
    step: Optional[str] = None
    reason: str
    description: Optional[str] = None


class LLMMetadata(BaseModel):
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    confidence: Optional[float] = None


# --- Audit Entry ---

class AuditEntryResponse(BaseModel):
    id: int
    payment_id: str
    timestamp: datetime
    action: str
    actor: str
    details: Optional[str] = None
    cost_incurred_inr: float = 0.0
    llm_model: Optional[str] = None
    llm_input_tokens: Optional[int] = None
    llm_output_tokens: Optional[int] = None
    llm_latency_ms: Optional[int] = None
    llm_confidence: Optional[float] = None

    class Config:
        from_attributes = True


# --- Payment Failure Records ---

class PaymentFailureCreate(BaseModel):
    """Schema for creating a payment failure record (from webhook or batch ingestion)."""
    payment_id: str
    amount: int  # in paise
    currency: str = "INR"
    method: str
    subscription_id: Optional[str] = None
    invoice_id: Optional[str] = None
    merchant_id: str
    customer: CustomerInfo
    error: ErrorInfo
    failure_class: Optional[str] = None
    recovery_state: str = "INGESTED"
    recovery_channel: Optional[str] = None


class PaymentFailureResponse(BaseModel):
    """Full payment failure record with audit trail."""
    payment_id: str
    amount: int
    currency: str
    method: str
    subscription_id: Optional[str] = None
    invoice_id: Optional[str] = None
    merchant_id: str
    customer_name: str
    customer_email: Optional[str] = None
    customer_phone: str
    error_source: Optional[str] = None
    error_step: Optional[str] = None
    error_reason: str
    error_description: Optional[str] = None
    failure_class: Optional[str] = None
    recovery_state: str
    recovery_channel: Optional[str] = None
    batch_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    audit_trail: List[AuditEntryResponse] = []

    class Config:
        from_attributes = True


# --- Batch Run ---

class BatchRunResponse(BaseModel):
    batch_id: str
    status: str
    total_records: int
    processed_records: int
    recovered_count: int = 0
    total_gmv: int = 0
    recovered_gmv: int = 0
    channel_cost: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- Dashboard Metrics ---

class ClassBreakdown(BaseModel):
    failure_class: str
    total_count: int
    recovered_count: int
    total_gmv: int
    recovered_gmv: int
    channel_cost: float
    recovery_rate: float


class DashboardMetrics(BaseModel):
    total_records: int = 0
    total_gmv: int = 0           # in paise
    recovered_gmv: int = 0       # in paise
    recovery_rate: float = 0.0   # percentage
    total_channel_cost: float = 0.0  # INR
    net_roi: float = 0.0         # INR (recovered_gmv_inr - channel_cost)
    cost_per_recovery: float = 0.0   # INR
    recovered_count: int = 0
    failed_count: int = 0
    in_progress_count: int = 0
    class_breakdown: List[ClassBreakdown] = []


# --- Webhook ---

class WebhookPayload(BaseModel):
    """Razorpay webhook payload structure."""
    entity: str = "event"
    event: str
    payload: dict
    account_id: Optional[str] = None


# --- LLM Response Schemas ---

class ParsedIntent(BaseModel):
    """Structured output from LLM customer reply parsing."""
    intent: str  # will_pay, dispute, opt_out, request_delay, unclear
    confidence: float = Field(ge=0.0, le=1.0)
    extracted_date: Optional[str] = None
    sentiment: str = "neutral"  # positive, neutral, negative
    requires_human: bool = False
    reasoning: str = ""
