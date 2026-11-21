import csv
from datetime import date, timedelta
import shutil

import pytest

from cvtitan import line_b
from cvtitan.apply import mx_boards
from cvtitan.cli import main
from cvtitan.search_mx import _location
from cvtitan.utils import Workspace


@pytest.mark.parametrize(("offer", "mode"), [
    ({"regions": ["Mexico"]}, "Remoto desde México"),
    ({"regions": ["Remote in Mexico / Remote in Argentina"]}, "Remoto desde México"),
    ({"regions": ["Latin America"]}, "Remoto desde México"),
    ({"regions": ["Mexico City, Mexico - Remote"], "text": "Work from anywhere in Mexico."}, "Remoto desde México"),
    ({"title": "Project Manager", "text": "This position is fully remote within Mexico."}, "Remoto desde México"),
    ({"workplace_type": "hybrid", "location": "Apodaca, Nuevo León, Mexico"}, "Híbrido"),
    ({"workplace_type": "on-site", "location": "Monterrey, Mexico"}, "Presencial"),
    ({"workplace_type": "hybrid", "location": "Mexico City, Mexico"}, None),
    ({"workplace_type": "on-site", "location": "Monterrey, Colombia"}, None),
    ({"workplace_type": "remote", "location": "Mexico City, Mexico"}, None),
    ({"workplace_type": "remote", "location": "Remote in Guadalajara, Mexico"}, None),
    ({"workplace_type": "remote", "location": "Remote"}, None),
    ({"regions": ["South America"]}, None),
    ({"regions": ["LATAM"], "text": "Candidates must be based in Brazil for this opening."}, None),
    ({"regions": ["LATAM"], "text": "Remote, except for Mexico."}, None),
    ({"regions": ["LATAM"], "text": "Remote work is available in South America only."}, None),
    ({"regions": ["Worldwide"], "text": "You must be authorized to work in the United States for this role."}, None),
    ({"onsite": "Monterrey, Mexico", "text": "The company supports global remote team collaboration."}, None),
])
def test_search_location(offer, mode):
    found = _location(offer)
    assert (found[0] if found else None) == mode


def test_mexico_search_uses_evidence_and_filters_the_csv(tmp_path, monkeypatch):
    ws = Workspace.resolve(tmp_path)
    ws.profile_path.parent.mkdir()
    shutil.copy(ws.example_profile_path, ws.profile_path)

    def public_offers(workspace, line, say, use_linkedin):
        assert workspace.root == tmp_path and not use_linkedin
        assert "project manager" in line["keywords"]
        role = {
            "title": "Project Manager", "company": "Empresa Ejemplo", "regions": ["Mexico"],
            "text": "Requirements\n- Python\n- Docker", "source": "Tablero Ejemplo",
            "url": "https://example.com/first",
        }
        return [
            role, {**role, "url": "https://example.com/duplicate"},
            {**role, "title": "Project Manager, US", "regions": ["US"]},
            {**role, "company": "Puesto cerrado", "valid_through": (date.today() - timedelta(days=1)).isoformat()},
            {**role, "title": "Junior Project Manager"},
            {**role, "title": "Casino Operations Manager", "company": "Otro empleador"},
        ], {"publica": 6}

    monkeypatch.setattr(line_b, "collect_offers", public_offers)
    assert main(["--root", str(tmp_path), "buscar-mx", "--area", "proyectos"]) == 0
    with (tmp_path / "data/busqueda-mx.csv").open(encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file, delimiter=";"))
    assert len(rows) == 1
    row = rows[0]
    assert row["url"] == "https://example.com/first"
    assert row["modalidad"] == "Remoto desde México"
    assert row["habilidades_respaldadas"] == "Python"
    assert row["requisitos_por_validar"] == "Docker"
    assert "postular" not in row


def test_equipo123go_requires_current_index_and_job_posting(tmp_path, monkeypatch):
    index = """
    <article data-type="hibrido"><h3>Gerente de Operaciones de Casino</h3>
      <a href="/operaciones/">Leer más</a></article>
    <article data-type="tiempo-completo"><h3>Recepcionista</h3>
      <a href="/recepcion/">Leer más</a></article>
    <article data-type="hibrido"><h3>Gerente de Operaciones de Casino</h3>
      <a href="https://otro.example.com/ficha/">Leer más</a></article>
    """
    posting = """
    <script type="application/ld+json">
      {"@type":"JobPosting", "title":"Gerente de Operaciones de Casino",
       "description":"<p>Requisitos</p><p>Gestión de proveedores.</p>",
       "jobLocation":{"address":{"addressLocality":"Monterrey","addressCountry":"MX"}}}
    </script>
    """
    reads = []

    def get(url, **kwargs):
        reads.append(url)
        return {mx_boards.INDEX: index, "https://equipo123go.com/operaciones/": posting}[url].encode()

    monkeypatch.setattr(mx_boards, "_get", get)
    filters = {"keywords": ["gerente de operaciones de casino"]}
    first = mx_boards.equipo123go(tmp_path, filters)
    assert mx_boards.equipo123go(tmp_path, filters) == first
    assert reads == [mx_boards.INDEX, "https://equipo123go.com/operaciones/"]
    assert len(first) == 1 and _location(first[0]) == ("Híbrido", "Monterrey, MX")
