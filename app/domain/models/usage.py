from pydantic import BaseModel


class LLMUsage(BaseModel):
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_s: float
