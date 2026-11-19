"""Plataformas de empleo conocidas: cómo se detectan y qué textos usan sus botones."""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    hosts: tuple[str, ...] = ()
    login_url: str | None = None
    requires_login: bool = False
    apply_texts: tuple[str, ...] = ("Postular", "Postularme", "Postúlate", "Aplicar", "Apply", "Apply now",
                                    "Apply for this job", "Postular ahora", "Solicitar")
    notes: str = ""
    extra: dict = field(default_factory=dict)


PLATFORMS = [
    Platform("linkedin", "LinkedIn", ("linkedin.com",), "https://www.linkedin.com/login", True,
             ("Solicitud sencilla", "Easy Apply", "Solicitar", "Postularse"),
             "LinkedIn prohíbe la automatización en sus términos: ritmo lento, límite diario bajo y revisión final."),
    Platform("indeed", "Indeed", ("indeed.com",), "https://secure.indeed.com/auth", True,
             ("Postularse ahora", "Postúlate ahora", "Solicitar ahora", "Apply now", "Postularme")),
    Platform("getonboard", "Get on Board", ("getonbrd.com", "getonboard.com"), "https://www.getonbrd.com/login", True,
             ("Postular", "Postula ahora", "Apply", "Apply now", "Postular a este empleo",
              "You have an unsent application", "Tienes una postulación sin enviar", "Tienes una postulación por enviar", "Continue your application",
              "Continuar postulación")),
    Platform("greenhouse", "Greenhouse", ("greenhouse.io",), None, False,
             ("Apply", "Apply for this job", "Apply Now", "Postular")),
    Platform("lever", "Lever", ("lever.co",), None, False, ("Apply for this job", "Apply", "Postular")),
    Platform("workday", "Workday", ("myworkdayjobs.com", "workday.com"), None, True,
             ("Apply", "Postular", "Postularse", "Aplicar", "Apply Manually", "Aplicar manualmente", "Postulación manual")),
    Platform("laborum", "Laborum", ("laborum.cl", "bumeran.com"), "https://www.laborum.cl/login", True,
             ("Postularme", "Postular", "Postulación rápida")),
    Platform("computrabajo", "Computrabajo", ("computrabajo.com",), "https://cl.computrabajo.com/", True,
             ("Postularme", "Postular", "Postúlate")),
    Platform("chiletrabajos", "Chiletrabajos", ("chiletrabajos.cl",), "https://www.chiletrabajos.cl/", True,
             ("Postular", "Postula", "Enviar postulación")),
    Platform("bne", "Bolsa Nacional de Empleo", ("bne.cl", "bne.gob.cl"), "https://www.bne.cl/login", True,
             ("Postular", "Postula")),
    Platform("trabajando", "Trabajando.com", ("trabajando.cl", "trabajando.com"), "https://www.trabajando.cl/", True,
             ("Postular", "Postularme")),
]
GENERIC = Platform("generic", "Sitio de la empresa")

# En estos sitios el robot NUNCA llena campos (sus formularios son filtros/buscadores del propio portal):
# solo pulsa «Apply» y sigue hasta el sitio del empleador.
JOB_BOARDS = ("remoteok.com", "weworkremotely.com", "remotive.com", "jobicy.com", "himalayas.app",
              "arbeitnow.com")
BOARD_APPLY_TEXTS = ("Apply for this job", "Apply for this position", "Apply now", "Apply", "How to apply",
                     "Postular", "Aplicar")


def is_job_board(url: str) -> bool:
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    return any(host == b or host.endswith("." + b) for b in JOB_BOARDS)

NEXT_TEXTS = ("siguiente", "next", "continuar", "continue", "revisar", "review", "guardar y continuar",
              "save and continue", "avanzar", "paso siguiente")
SUBMIT_TEXTS = ("enviar postulacion ahora", "enviar solicitud", "submit application", "enviar postulacion", "enviar mi postulacion",
                "submit", "enviar", "finalizar", "send application", "postular", "postularme", "apply",
                "confirmar postulacion", "completar postulacion")
# La vacante ya tiene una postulación enviada (p. ej. hecha a mano antes).
ALREADY_APPLIED_TEXTS = ("see your application", "ver tu postulacion", "your application hasn't been read",
                         "tu postulacion no ha sido leida", "you already applied", "ya postulaste")
# La plataforma no permite postular (país, requisitos, vacante cerrada).
BLOCKED_TEXTS = ("your country doesn't match", "tu pais no coincide", "this job is closed", "esta oferta esta cerrada",
                 "no longer accepting applications", "ya no recibe postulaciones")
SUCCESS_TEXTS = ("gracias por postular", "postulacion enviada", "application submitted", "thank you for applying",
                 "your application was sent", "hemos recibido tu postulacion", "solicitud enviada",
                 "postulacion exitosa", "te postulaste", "you applied", "application received",
                 "ya postulaste", "postulacion realizada", "thanks for applying", "se envio tu solicitud",
                 "fue enviada exitosamente", "enviada exitosamente", "postulacion fue enviada",
                 "application has been submitted", "successfully submitted", "submitted successfully")


def detect(url: str) -> Platform:
    host = (urlparse(url).hostname or "").lower()
    for p in PLATFORMS:
        if any(host == h or host.endswith("." + h) for h in p.hosts):
            return p
    return GENERIC


def login_targets() -> list[dict]:
    return [{"key": p.key, "name": p.name, "url": p.login_url} for p in PLATFORMS if p.login_url]
