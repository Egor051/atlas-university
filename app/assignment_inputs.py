"""Validation for the existing student and teacher assignment endpoints."""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from .assignment_workflow import FORMATS, MAX_UPLOAD_BYTES, WORK_KINDS, time_value, validate_https
from .main import StrictBody


SubmissionMethod = Literal['text', 'url', 'files', 'complete']
WorkState = Literal['draft', 'scheduled', 'published', 'closed', 'archived']
RecordID = Annotated[int, Field(strict=True, ge=1, le=2147483647)]


class AttachmentBody(StrictBody):
    name: str = Field(min_length=1, max_length=180)
    content: str = Field(min_length=4, max_length=4 * ((MAX_UPLOAD_BYTES + 2) // 3))


class WorkBody(StrictBody):
    title: str = Field(min_length=4, max_length=180)
    instructions: str = Field(default='', max_length=4000)
    due: date | None = None
    due_at: datetime | None = None
    state: WorkState = 'published'
    publish_at: datetime | None = None
    kind: str = 'homework'
    custom_kind: str = Field(default='', max_length=80)
    description: str = Field(default='', max_length=1500)
    criteria: str = Field(default='', max_length=2000)
    max_points: int = Field(default=100, strict=True, ge=0, le=1000)
    methods: list[SubmissionMethod] = Field(default_factory=lambda: ['text', 'url'], min_length=1, max_length=4)
    required_methods: list[SubmissionMethod] = Field(default_factory=list, max_length=4)
    formats: list[str] = Field(default_factory=lambda: list(FORMATS), max_length=len(FORMATS))
    min_files: int = Field(default=1, strict=True, ge=1, le=3)
    max_files: int = Field(default=3, strict=True, ge=1, le=3)
    allow_resubmission: StrictBool = True
    max_attempts: int | None = Field(default=None, strict=True, ge=1, le=50)
    allow_late: StrictBool = True
    materials: list[str] = Field(default_factory=list, max_length=5)
    material_ids: list[RecordID] = Field(default_factory=list, max_length=5)
    source_files: list[AttachmentBody] = Field(default_factory=list, max_length=3)
    recipient_ids: list[StrictInt] = Field(default_factory=list, max_length=200)
    subgroup_id: int | None = Field(default=None, strict=True, ge=1, le=2147483647)
    team_lead_id: int | None = Field(default=None, strict=True, ge=1)
    award_mode: Literal['all', 'lead'] = 'all'
    class_id: int | None = Field(default=None, strict=True, ge=1)

    @field_validator('title', 'instructions', 'custom_kind', 'description', 'criteria', mode='before')
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator('due_at', 'publish_at')
    @classmethod
    def timestamp(cls, value):
        return time_value(value)

    @model_validator(mode='after')
    def valid_policy(self):
        if self.state != 'draft' and (len(self.instructions) < 12 or (not self.due_at and not self.due)):
            raise ValueError('Укажите срок и инструкцию от 12 символов')
        if self.kind not in WORK_KINDS or (self.kind == 'other' and not self.custom_kind):
            raise ValueError('Выберите тип работы или укажите своё название')
        if self.kind == 'group' and self.team_lead_id is None:
            raise ValueError('Укажите ответственного за сдачу групповой работы')
        if self.award_mode == 'lead' and self.team_lead_id is None:
            raise ValueError('Начисление только ответственному доступно для групповой работы')
        if len(set(self.recipient_ids)) != len(self.recipient_ids) or any(key < 1 for key in self.recipient_ids):
            raise ValueError('Проверьте список студентов')
        if self.subgroup_id is not None and self.recipient_ids:
            raise ValueError('Выберите подгруппу или отдельных студентов')
        if len(set(self.methods)) != len(self.methods):
            raise ValueError('Способы сдачи указаны повторно')
        if len(set(self.required_methods)) != len(self.required_methods) or not set(self.required_methods) <= set(self.methods):
            raise ValueError('Выберите обязательные способы из разрешённых')
        if self.min_files > self.max_files:
            raise ValueError('Минимум файлов не может быть больше максимума')
        if (not set(self.formats) <= set(FORMATS) or
            ('files' in self.methods and not self.formats)):
            raise ValueError('Выберите допустимые форматы файлов')
        if any(not 1 <= len(url) <= 500 or not validate_https(url) for url in self.materials):
            raise ValueError('Материалы должны быть полными HTTPS-ссылками')
        if self.state == 'scheduled' and self.publish_at is None:
            raise ValueError('Укажите дату публикации')
        return self


class WorkEdit(WorkBody):
    title: str | None = Field(default=None, min_length=4, max_length=180)
    version: int = Field(strict=True, ge=1)
    state: WorkState | None = None
    remove_source_ids: list[RecordID] = Field(default_factory=list, max_length=3)

    @model_validator(mode='after')
    def valid_policy(self):
        # A partial change is validated again after merging stored fields.
        return self


class FeedbackBody(StrictBody):
    submitted_version: int = Field(strict=True, ge=1)
    version: int | None = Field(default=None, strict=True, ge=1)
    score: int | None = Field(default=None, strict=True, ge=0, le=1000)
    comment: str = Field(default='', max_length=2000)
    remarks: str = Field(default='', max_length=2000)
    files: list[AttachmentBody] = Field(default_factory=list, max_length=3)
    action: Literal['comment', 'review', 'revise', 'accept', 'grade', 'complete'] = 'comment'
    extended_until: datetime | None = None

    @field_validator('comment', 'remarks', mode='before')
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator('extended_until')
    @classmethod
    def timestamp(cls, value):
        return time_value(value)

    @model_validator(mode='after')
    def review_fields(self):
        has_explanation = max(len(self.comment), len(self.remarks)) >= 3
        if (self.action == 'revise' and not has_explanation) or (
            self.action == 'comment' and not (has_explanation or self.files)
        ):
            raise ValueError('Укажите комментарий или замечания от трёх символов')
        if self.score is not None and self.action not in ('accept', 'grade', 'comment'):
            raise ValueError('Баллы начисляются при оценивании работы')
        if self.action == 'grade' and self.score is None:
            raise ValueError('Укажите балл за работу')
        if self.extended_until is not None and self.action != 'revise':
            raise ValueError('Укажите новый срок при возврате на доработку')
        return self


class ScoreCorrectionBody(StrictBody):
    submitted_version: int = Field(strict=True, ge=1)
    version: int = Field(strict=True, ge=1)
    score: int = Field(strict=True, ge=0, le=1000)
    reason: str = Field(min_length=3, max_length=300)

    @field_validator('reason', mode='before')
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class ExtendBody(StrictBody):
    version: int = Field(strict=True, ge=1)
    individual_due_at: datetime | None = None
    extended_until: datetime | None = None

    @field_validator('individual_due_at', 'extended_until')
    @classmethod
    def timestamp(cls, value):
        return time_value(value)

    @model_validator(mode='after')
    def deadline_change(self):
        fields = self.model_fields_set
        if ('individual_due_at' in fields) == ('extended_until' in fields) or (
            'extended_until' in fields and self.extended_until is None
        ):
            raise ValueError('Укажите персональный срок или продление')
        return self


class SubmissionBody(StrictBody):
    text: str = Field(default='', max_length=8000)
    url: str = Field(default='', max_length=500)
    completed: StrictBool = False
    files: list[AttachmentBody] = Field(default_factory=list, max_length=3)
    version: int | None = Field(default=None, strict=True, ge=0)

    @field_validator('text')
    @classmethod
    def useful_text(cls, value):
        value = value.strip()
        if value and len(value) < 10:
            raise ValueError('Опишите работу минимум десятью символами')
        return value

    @field_validator('url')
    @classmethod
    def https_reference(cls, value):
        return validate_https(value)
