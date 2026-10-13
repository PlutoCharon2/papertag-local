from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Evidence(StrictModel):
    block_id: str = ''
    page: int | None = Field(default=None, ge=1)
    quote: str = Field(min_length=1, max_length=6000)


class Tag(StrictModel):
    label_id: str
    evidence: list[Evidence] = Field(min_length=1)


class Claim(StrictModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,60}$')
    kind: Literal['contribution', 'author_gap', 'mechanism', 'assumption', 'limitation', 'theoretical_result', 'empirical_result']
    text: str = Field(min_length=1, max_length=6000)
    method: str = Field(min_length=1, max_length=500)
    system: str = Field(min_length=1, max_length=500)
    conditions: list[str]
    target: str
    result_form: str
    scope: str
    residual: str
    label_ids: list[str]
    evidence: list[Evidence] = Field(min_length=1)


class Analysis(StrictModel):
    paper_id: int
    document_hash: str
    ontology_version: int
    schema_version: Literal[1, 2]
    title: str = Field(min_length=1, max_length=1000)
    authors: list[str]
    year: int | None = Field(default=None, ge=1500, le=2200)
    doi: str = ''
    paper_type: Literal['theory', 'empirical', 'review', 'mixed', 'unknown']
    summary: str = Field(max_length=6000)
    tags: list[Tag]
    claims: list[Claim]
    suggestions: list[str] = Field(default_factory=list)


class ImportRequest(StrictModel):
    path: str = ''
    paths: list[str] = Field(default_factory=list, max_length=10000)


class AnalysisInput(StrictModel):
    text: str = Field(min_length=1, max_length=2000000)


class Decision(StrictModel):
    label_id: str
    decision: Literal['accepted', 'rejected', 'manual', 'reset']


class LabelInput(StrictModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{1,70}$')
    dimension: Literal['topic', 'method', 'problem', 'feedback', 'system', 'result', 'application', 'personal']
    name: str = Field(min_length=1, max_length=150)
    definition: str = Field(min_length=1, max_length=2000)
    parent_id: str | None = None
    synonyms: list[str] = Field(default_factory=list)


class SearchInput(StrictModel):
    text: str = ''
    filters: dict[str, list[str]] = Field(default_factory=dict)
    same_claim: bool = False
    reviewed_only: bool = False
    pending_only: bool = False
    show_versions: bool = False


class LabelEdit(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    definition: str | None = Field(default=None, min_length=1, max_length=2000)
    active: bool | None = None


class ProposedLabel(StrictModel):
    key: str = Field(pattern=r'^new_[a-z0-9_]{1,60}$')
    dimension: Literal['topic', 'method', 'problem', 'feedback', 'system', 'result', 'application']
    name: str = Field(min_length=1, max_length=150)
    definition: str = Field(min_length=1, max_length=2000)


class AutoAnalysis(Analysis):
    schema_version: Literal[2]
    new_labels: list[ProposedLabel] = Field(default_factory=list, max_length=15)


class AISettings(StrictModel):
    enabled: bool
    max_pages: int = Field(ge=1, le=80)
    timeout: int = Field(ge=60, le=3600)
    model: str = Field(default='', max_length=100, pattern=r'^[a-zA-Z0-9._/-]*$')


class APIProfile(StrictModel):
    provider: Literal['qwen', 'doubao', 'deepseek', 'zhipu']
    url: str = Field(min_length=8, max_length=300)
    model: str = Field(min_length=1, max_length=150)
    api_key: str = Field(default='', max_length=1000)
    clear_key: bool = False
