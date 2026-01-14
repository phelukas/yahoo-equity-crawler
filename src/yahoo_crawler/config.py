from pydantic import BaseModel, Field


class Settings(BaseModel):
    region: str = Field(..., min_length=2)
    output: str
    headless: bool
    log_level: str
    strict: bool = False
