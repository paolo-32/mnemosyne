from pydantic import BaseModel, Field

class ExtractedContent(BaseModel):
    raw_content: str
    metadata: dict = Field(default_factory=dict)
