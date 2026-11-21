"""Esquema JSON del perfil (`candidate/profile.yaml`) para autocompletado y validación en el editor.

Los modelos son permisivos (claves extra permitidas, casi todo opcional): la validación real y los avisos viven en
`Profile.validate` y `profile_checks`. Generar el archivo: `cvtitan schema --out candidate/profile.schema.json`.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class Personal(_Loose):
    name: str = Field(description="Nombre completo (obligatorio).")
    headline: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    github: str | None = None


class Achievement(_Loose):
    id: str = Field(description="Id único; las skills lo citan como evidencia.")
    text: str = Field(description="Hecho verificable. Las cifras que escribas aquí son las únicas que el CV podrá usar.")
    skills: list[str] = []


class Experience(_Loose):
    id: str
    company: str | None = None
    role: str | None = None
    location: str | None = None
    start: str | None = Field(default=None, description="AAAA-MM")
    end: str | None = Field(default=None, description="AAAA-MM o 'presente'")
    achievements: list[Achievement] = []


class Project(_Loose):
    id: str
    name: str | None = None
    description: str | None = None
    skills: list[str] = []
    status: str | None = Field(default=None, description="completed o in_progress")
    url: str | None = None


class Education(_Loose):
    id: str
    degree: str | None = None
    institution: str | None = None
    year: int | str | None = None
    skills: list[str] = []


class Certification(_Loose):
    id: str
    name: str | None = None
    issuer: str | None = None
    year: int | str | None = None
    skills: list[str] = []


class Skill(_Loose):
    name: str
    status: Literal["backed", "to_demonstrate"] = Field(
        description="backed: defendible, con evidence. to_demonstrate: nunca aparece en el CV.")
    evidence: list[str] = Field(default=[], description="Ids de logros, proyectos, estudios o certificaciones.")
    note: str | None = None


class SummaryVariant(_Loose):
    id: str
    focus: list[str] = []
    text: str


class ProfileModel(_Loose):
    personal: Personal
    summary: str | None = None
    summary_variants: list[SummaryVariant] = []
    experience: list[Experience] = []
    projects: list[Project] = []
    education: list[Education] = []
    certifications: list[Certification] = []
    skills: list[Skill] = []
    preferences: dict[str, Any] = {}
    documents: list[dict[str, Any]] = []
    languages: list[dict[str, Any]] = []
    cv_files: dict[str, str] = {}


def json_schema() -> dict:
    schema = ProfileModel.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "TITAN CV candidate profile"
    return schema
