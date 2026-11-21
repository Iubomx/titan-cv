"""Deduplicación entre portales: la huella de la Línea B usa la misma normalización que el registro global."""
import pytest

from cvtitan.line_b import fingerprint
from cvtitan.registry import fingerprint as registry_fingerprint

SAME = [
    (("Acme Inc.", "Software Engineer (Remote)"), ("ACME", "Software Engineer")),
    (("Initech S.A.", "Sr. Data Engineer [LATAM]"), ("Initech", "Senior Data Engineer")),
    (("Globex Group", "Jr Developer"), ("Globex", "Junior Developer")),
    (("Umbrella Corp", "Analista de Datos - Santiago"), ("Umbrella", "Analista de Datos")),
    (("Hooli LLC", "Backend Engineer | Hooli"), ("hooli", "Backend Engineer")),
    (("Wayne Enterprises (via Lever)", "SRE"), ("Wayne Enterprises", "SRE")),
    (("Café Ñandú Ltda.", "Ingeniero de Datos"), ("Cafe Nandu", "Ingeniero de Datos")),
]
DIFFERENT = [
    (("Acme Inc.", "Software Engineer"), ("Globex Inc.", "Software Engineer")),
    (("Acme", "Data Engineer"), ("Acme", "Data Analyst")),
    (("Acme", "Senior Data Engineer"), ("Acme", "Junior Data Engineer")),
    (("Acme", "Backend Engineer"), ("Acme", "Frontend Engineer")),
]


@pytest.mark.parametrize("a, b", SAME)
def test_same_job_on_different_boards_gets_the_same_fingerprint(a, b):
    assert fingerprint(*a) == fingerprint(*b)


@pytest.mark.parametrize("a, b", DIFFERENT)
def test_different_jobs_keep_different_fingerprints(a, b):
    assert fingerprint(*a) != fingerprint(*b)


@pytest.mark.parametrize("a, b", SAME + DIFFERENT)
def test_line_b_and_registry_agree_on_what_is_a_duplicate(a, b):
    """Si el registro global considera iguales (o distintas) dos ofertas remotas, la Línea B debe coincidir."""
    registry_same = registry_fingerprint(*a, modality="remoto") == registry_fingerprint(*b, modality="remoto")
    assert (fingerprint(*a) == fingerprint(*b)) == registry_same


def test_missing_company_or_title_does_not_crash():
    assert fingerprint(None, None) == "|"
    assert fingerprint("Acme", None) == "acme|"
