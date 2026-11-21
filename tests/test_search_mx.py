import csv
from datetime import date, timedelta
import shutil

import pytest

from cvtitan import line_b
from cvtitan.apply import mx_boards
from cvtitan.cli import main
from cvtitan.search_mx import CONFIG, _areas, _location
from cvtitan.utils import PACKAGE_ROOT, Workspace, load_yaml


@pytest.mark.parametrize(("offer", "mode"), [
    ({"regions": ["Mexico"]}, "Remoto desde México"),
    ({"location": "Work from Home - Mexico"}, "Remoto desde México"),
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
            "posted_at": date.today().isoformat(),
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


def test_mx_search_counts_all_areas_and_requires_recent_dates(tmp_path, monkeypatch, capsys):
    ws = Workspace.resolve(tmp_path)
    ws.profile_path.parent.mkdir()
    shutil.copy(ws.example_profile_path, ws.profile_path)
    today = date.today()
    common = {"company": "Empresa Ejemplo", "regions": ["Mexico"], "source": "Tablero Ejemplo",
              "text": "Requirements\n- Python", "posted_at": today.isoformat()}

    def offer(title, key, **overrides):
        return {**common, "title": title, "url": f"https://example.com/{key}", **overrides}

    def fetch(*args, **kwargs):
        return [
            offer("Project Manager", "project"),
            offer("Casino Operations Manager", "casino"),
            offer("Telecom Project Manager", "telecom"),
            offer("Marketing Operations Manager", "martech"),
            offer("CRM Manager", "old", posted_at=(today - timedelta(days=30)).isoformat()),
            offer("MarTech Manager", "undated", posted_at=None),
            offer("Sportsbook Manager", "future", company="Empresa Ejemplo",
                  posted_at=(today + timedelta(days=1)).isoformat()),
        ], {"publica": 7}

    monkeypatch.setattr(line_b, "collect_offers", fetch)
    assert main(["--root", str(tmp_path), "buscar-mx"]) == 0
    output = capsys.readouterr().out
    assert "proyectos: 2/20" in output
    for area in ("casinos", "telecom", "martech"):
        assert f"{area}: 1/20" in output
    assert "1 vacante(s) compatibles sin fecha comprobable" in output
    with (tmp_path / "data/busqueda-mx.csv").open(encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file, delimiter=";"))
    assert len(rows) == 4
    assert {row["fecha_publicacion"] for row in rows} == {today.isoformat()}


def test_workable_uses_original_publish_date_and_explicit_remote_locations(tmp_path, monkeypatch):
    import json
    from cvtitan.apply import ats_boards

    body = {"name": "Publicador", "jobs": [{
        "url": "https://apply.workable.com/j/FICTICIO",
        "title": "Technical Project Manager",
        "description": "<p>Requirements</p><p>Project planning.</p>",
        "telecommuting": True, "country": "Mexico", "city": "Guadalajara",
        "published_on": "2026-11-01",
        "locations": [
            {"country": "Mexico", "city": "Guadalajara", "region": "Jalisco", "hidden": False},
            {"country": "Mexico", "city": "Monterrey", "region": "Nuevo León", "hidden": False},
            {"country": "Canada", "city": "Toronto", "hidden": True},
        ],
    }]}
    monkeypatch.setattr(ats_boards, "_get", lambda url: json.dumps(body).encode())
    offer, = ats_boards.workable(tmp_path, ["example"], {"include_posted_metadata": True})
    assert offer["posted_at"] == "2026-11-01"
    assert offer["posting_regions"] == ["Guadalajara, Jalisco, Mexico", "Monterrey, Nuevo León, Mexico"]
    assert _location(offer)[0] == "Remoto desde México"


def test_telecom_role_requires_sector_for_generic_network_and_routing_titles():
    cfg = load_yaml(PACKAGE_ROOT / CONFIG)
    telecom = {"telecom": cfg["areas"]["telecom"]}
    social = {"company": "Casino de ejemplo", "title": "Gerente de Redes Sociales", "text": "Marketing digital."}
    routing = {"company": "Proveedor de ejemplo", "title": "Technical Routing Analyst", "text": "CPaaS carrier routing."}
    assert _areas(social, telecom, cfg["exclude_titles"]) == []
    assert _areas(routing, telecom, cfg["exclude_titles"]) == ["telecom"]
