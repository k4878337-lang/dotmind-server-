from typing import Optional, List
from pydantic import BaseModel, Field

class ModelInfo(BaseModel):
    id: str = Field(..., description="Short model ID (e.g. 'gemini-2.0-flash')")
    name: str = Field(..., description="Full model resource name (e.g. 'models/gemini-2.0-flash')")
    display_name: str = Field(..., description="Human-readable model name")
    description: Optional[str] = Field(None, description="Model description")
    supported_generation_methods: List[str] = Field(default_factory=list, description="Methods like generateContent")
    input_token_limit: Optional[int] = None
    output_token_limit: Optional[int] = None
    category: str = Field("chat", description="'chat' (generateContent) or 'specialized' (embedding/imagen/etc)")

class DiscoverModelsRequest(BaseModel):
    provider: str = Field("gemini", description="AI Provider name (gemini)")
    api_key: Optional[str] = Field(None, description="Optional personal API key")

class DiscoverModelsResponse(BaseModel):
    status: str = Field(..., description="'success' or 'error'")
    provider: str = "gemini"
    models: List[ModelInfo] = Field(default_factory=list, description="All discovered models")
    chat_models: List[ModelInfo] = Field(default_factory=list, description="Models supporting generateContent")
    total_count: int = 0
    message: Optional[str] = None
    fetched_at: str

class TestConnectionRequest(BaseModel):
    provider: str = Field("gemini", description="AI Provider name (gemini)")
    api_key: Optional[str] = Field(None, description="User personal API key (optional)")
    model: Optional[str] = Field(None, description="Gemini model identifier to test")

class TestConnectionResponse(BaseModel):
    status: str = Field(..., description="'connected' or 'error'")
    provider: str
    model: str
    message: str
    error_code: Optional[str] = None
    server_managed_available: bool = False
    latency_ms: Optional[int] = None

class GatewayStatusResponse(BaseModel):
    supported_providers: List[str]
    available_models: List[str]
    server_managed_available: bool
    default_provider: str
    default_model: str
