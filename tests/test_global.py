"""Etapas 2 y 3: catálogo geográfico, exploración, cola persistente y cortacircuitos (sin red ni envíos)."""
from cvtitan.geo import Geo
from cvtitan.pipeline import CircuitBreaker, TaskQueue, run_parallel


def _geo(tmp_path):
    d = tmp_path / "geo"
    d.mkdir()
    (d / "countryInfo.txt").write_text(
        "#ISO\n" + "\t".join(["US", "USA", "840", "US", "United States", "Washington", "0", "331000000", "NA"] +
                             [""] * 7 + ["6252001"]) + "\n", encoding="utf-8")
    (d / "admin1CodesASCII.txt").write_text("US.NY\tNew York\tNew York\t5128638\nUS.TX\tTexas\tTexas\t4736286\n",
                                            encoding="utf-8")
    city = lambda gid, name, lat, lon, adm, pop: "\t".join(  # noqa: E731
        [str(gid), name, name, "", str(lat), str(lon), "P", "PPL", "US", "", adm, "", "", "", str(pop)] + [""] * 4)
    (d / "cities15000.txt").write_text("\n".join([
        city(1, "New York City", 40.71, -74.0, "NY", 8_800_000), city(2, "Brooklyn", 40.65, -73.95, "NY", 2_700_000),
        city(3, "Austin", 30.27, -97.74, "TX", 960_000), city(4, "Smallville", 31.0, -97.0, "TX", 20_000)]) + "\n",
        encoding="utf-8")
    g = Geo(tmp_path / "t.db")
    g.load(d)
    return g


def test_geo_catalog_hierarchy_and_dedup(tmp_path):
    g = _geo(tmp_path)
    assert g.stats()["countries"] == 1 and g.stats()["cities"] == 4
    names = [c["name"] for c in g.cities("US", 500_000, 10)]
    assert names == ["New York City", "Austin"]                  # Brooklyn queda cubierta por NYC; Smallville < mín.
    assert Geo.city_label(g.cities("US", 500_000, 1)[0]) == "New York City, New York"


def test_exploration_is_recorded_and_not_repeated(tmp_path):
    g = _geo(tmp_path)
    assert g.due("linkedin", "US|United States", "python developer")
    g.record("linkedin", "US|United States", "python developer", 10, ttl_hours=72)
    assert not g.due("linkedin", "US|United States", "python developer")
    assert g.stats()["explored"] == 1


def test_task_queue_resumes_after_crash(tmp_path):
    q = TaskQueue(tmp_path / "t.db")
    assert q.add("discover:x:2026-11-17", "discover") and not q.add("discover:x:2026-11-17", "discover")
    assert q.claim("discover:x:2026-11-17")
    q.c.execute("UPDATE tasks SET started_at='2000-01-01T00:00:00'")           # el proceso murió a la mitad
    q2 = TaskQueue(tmp_path / "t.db")                                           # reinicio
    assert q2.status("discover:x:2026-11-17") == "pending" and q2.claim("discover:x:2026-11-17")
    q2.done("discover:x:2026-11-17", {"count": 5})
    assert not q2.claim("discover:x:2026-11-17")                                # hecha: no se repite


def test_portal_down_does_not_stop_others_and_opens_circuit(tmp_path):
    def down():
        raise ConnectionError("503")
    db = tmp_path / "t.db"
    for day in ("d1", "d2", "d3"):
        res = run_parallel({"ok": lambda: [1, 2, 3], "down": down}, db, day, say=lambda *_: None)
        assert res["ok"] == [1, 2, 3] and str(res["down"]).startswith("error")
    assert not CircuitBreaker(db).allow("down")                                 # 3 fallos seguidos: circuito abierto
    res = run_parallel({"down": down}, db, "d4", say=lambda *_: None)
    assert str(res["down"]).startswith("skipped: circuit open")


def test_parallel_sources_share_db_safely(tmp_path):
    jobs = {f"s{i}": (lambda i=i: list(range(i))) for i in range(12)}
    res = run_parallel(jobs, tmp_path / "t.db", "d1", workers=12, say=lambda *_: None)
    assert all(res[f"s{i}"] == list(range(i)) for i in range(12))


def test_linkedin_guard_limits_only_linkedin(tmp_path):
    from cvtitan.apply.linkedin_guard import LinkedInGuard, is_linkedin
    g = LinkedInGuard({"linkedin": {"max_searches_per_run": 2, "max_reads_per_run": 1, "min_seconds_between": 0,
                                    "max_searches_per_day": 3}}, tmp_path / "g.json")
    assert g.allow("search")[0] and g.allow("search")[0] and not g.allow("search")[0]   # tope por ejecución
    assert g.allow("read")[0] and not g.allow("read")[0]
    g2 = LinkedInGuard({"linkedin": {"max_searches_per_run": 9, "min_seconds_between": 0,
                                     "max_searches_per_day": 3}}, tmp_path / "g.json")
    assert g2.allow("search")[0] and not g2.allow("search")[0]                         # tope diario persistente
    assert is_linkedin("https://www.linkedin.com/jobs/view/1") and not is_linkedin("https://remoteok.com/x")
