"""Pruebas obligatorias del registro global antiduplicados (ninguna envía postulaciones reales)."""
import threading

from cvtitan.registry import Registry, canonical_url, fingerprint, requisition_id

GH = "https://boards.greenhouse.io/acme/jobs/4012345"


def _reg(tmp_path, worker="w1"):
    return Registry(tmp_path / "cvtitan.db", worker=worker)


def _confirm(reg, vid):
    assert reg.claim(vid)
    reg.mark_clicked(vid)
    return reg.finish(vid, "confirmed", "ok", "confirmacion.png")


def test_1_restart_never_resubmits(tmp_path):
    reg = _reg(tmp_path)
    v = reg.register(GH, "Acme Inc.", "Senior Python Developer", modality="remoto")
    _confirm(reg, v["id"])
    reg.close()
    again = _reg(tmp_path, "w2")                       # «reinicio»: nueva conexión, nuevo proceso
    v2 = again.register(GH + "?utm_source=x", "ACME", "Senior Python Developer (Remote)", modality="remoto")
    assert v2["id"] == v["id"] and v2["status"] == "SUBMITTED_CONFIRMED"
    assert not again.can_submit(v2["id"])[0] and not again.claim(v2["id"])


def test_2_same_vacancy_in_five_portals(tmp_path):
    reg = _reg(tmp_path)
    urls = ["https://www.linkedin.com/jobs/view/3999999/", "https://cl.indeed.com/viewjob?jk=ab12cd34",
            GH, "https://acme.com/careers/senior-python-developer", "https://remoteok.com/remote-jobs/123-acme"]
    titles = ["Senior Python Developer", "Sr. Python Developer", "Senior Python Developer (Remote)",
              "Senior Python Developer - Remote", "Senior Python Developer | Acme"]
    ids = {reg.register(u, c, t, modality="remoto", source=f"s{i}")["id"]
           for i, (u, c, t) in enumerate(zip(urls, ["Acme", "ACME Inc", "Acme", "Acme Corp.", "acme"], titles))}
    assert len(ids) == 1                               # una sola vacante lógica
    vid = ids.pop()
    assert len(reg.sources(vid)) == 5
    _confirm(reg, vid)
    for u in urls:                                     # cualquier portal la reconoce como ya enviada
        assert reg.by_url(u)["status"] == "SUBMITTED_CONFIRMED"


def test_3_two_workers_same_vacancy(tmp_path):
    a, b = _reg(tmp_path, "A"), _reg(tmp_path, "B")
    vid = a.register(GH, "Acme", "Senior Python Developer", modality="remoto")["id"]
    wins = []
    barrier = threading.Barrier(2)

    def worker(reg, name):
        barrier.wait()
        if reg.claim(vid, name):
            wins.append(name)
    threads = [threading.Thread(target=worker, args=(a, "A")), threading.Thread(target=worker, args=(b, "B"))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(wins) == 1                              # solo un worker puede enviar


def test_4_failure_after_pressing_submit(tmp_path):
    reg = _reg(tmp_path)
    vid = reg.register(GH, "Acme", "Senior Python Developer", modality="remoto")["id"]
    assert reg.claim(vid)
    reg.mark_clicked(vid)                              # se pulsó «Enviar» y luego se cortó la conexión
    v = reg.finish(vid, "failed", "ConnectionError")
    assert v["status"] == "SUBMISSION_UNKNOWN"
    assert not reg.can_submit(vid)[0]                  # no se reintenta sin verificar
    # Falla ANTES del clic: sí se puede reintentar.
    vid2 = reg.register("https://boards.greenhouse.io/acme/jobs/4000001", "Acme", "Data Engineer")["id"]
    assert reg.claim(vid2)
    assert reg.finish(vid2, "failed", "timeout")["status"] == "FAILED"
    assert reg.can_submit(vid2)[0]


def test_5_new_requisition_same_title_is_distinct(tmp_path):
    reg = _reg(tmp_path)
    old = reg.register("https://boards.greenhouse.io/acme/jobs/1111111", "Acme", "Senior Python Developer",
                       modality="remoto")
    _confirm(reg, old["id"])
    new = reg.register("https://boards.greenhouse.io/acme/jobs/2222222", "Acme", "Senior Python Developer",
                       modality="remoto")
    assert new["id"] != old["id"] and reg.can_submit(new["id"])[0]
    # Requisición en el texto (sin ATS): distinta requisición -> distinta vacante.
    a = reg.register("https://acme.com/jobs/a", "Acme", "Analista BI", "Chile", "Santiago",
                     text="Req ID: R-1001. Buscamos analista...")
    b = reg.register("https://acme.com/jobs/b", "Acme", "Analista BI", "Chile", "Santiago",
                     text="Req ID: R-2002. Buscamos analista...")
    assert a["id"] != b["id"]


def test_6_same_title_company_different_place_is_distinct(tmp_path):
    reg = _reg(tmp_path)
    a = reg.register("https://x.com/1", "Acme", "Analista de Datos", "Chile", "Santiago", "presencial")
    b = reg.register("https://x.com/2", "Acme", "Analista de Datos", "Perú", "Lima", "presencial")
    assert a["id"] != b["id"]


def test_7_stale_lock_recovered_after_crash(tmp_path):
    reg = _reg(tmp_path)
    vid = reg.register(GH, "Acme", "Senior Python Developer")["id"]
    assert reg.claim(vid)
    reg.mark_clicked(vid)
    reg._conn.execute("UPDATE vacancies SET lock_at='2000-01-01T00:00:00' WHERE id=?", (vid,))   # proceso caído
    assert _reg(tmp_path, "w2").recover_stale() == 1
    assert reg.get(vid)["status"] == "SUBMISSION_UNKNOWN"


def test_10_import_history(tmp_path):
    from cvtitan.db import DB
    db = DB(tmp_path / "cvtitan.db")
    db.upsert("a", url=GH, company="Acme", title="Senior Python Developer", modality="remoto", status="applied")
    db.event("a", "info", "Postulación enviada y confirmada por la plataforma.")
    db.upsert("b", url="https://x.com/2", company="Beta", title="Data Engineer", status="needs_input")
    db.upsert("c", url="https://x.com/3", company="Gamma", title="DevOps", status="error")
    reg = _reg(tmp_path)
    counts = reg.import_history(db)
    assert counts == {"SUBMITTED_CONFIRMED": 1, "PENDING_REVIEW": 1, "FAILED": 1}
    assert reg.import_history(db) == counts           # idempotente
    assert reg.stats()["vacancies"] == 3
    assert not reg.can_submit(reg.by_url(GH)["id"])[0]


def test_helpers():
    assert canonical_url("https://www.Example.com/job/1/?utm=x") == "https://example.com/job/1"
    assert requisition_id("Job ID: JR-20455 — Santiago") == "JR-20455"
    assert fingerprint("Acme Inc.", "Sr. Data Engineer (Remote)", modality="remoto") == \
        fingerprint("ACME", "Senior Data Engineer", modality="remoto")
