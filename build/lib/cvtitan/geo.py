"""Catálogo geográfico jerárquico: Continente → País → Región → Ciudad (fuente: GeoNames, CC BY 4.0).

    cvtitan geo cargar            # importa data/geo/{countryInfo,admin1CodesASCII,cities15000}.txt a SQLite
    cvtitan geo estado            # países/regiones/ciudades cargados y exploración registrada

Identificadores estables: geonameid (ciudades), ISO-3166 (países), "CC.ADM1" (regiones).
La tabla `exploration` registra qué consulta se hizo en qué lugar y fuente, cuándo y cuántos resultados dio, para
no repetir búsquedas antes de su `next_run` y para medir cobertura.

Estrategia de búsqueda (evita consultas redundantes):
  1. Primero país (o región supranacional: "Latin America", "Worldwide").
  2. Solo si la búsqueda nacional se SATURA (devuelve el máximo de resultados), se expande a sus ciudades más
     pobladas (min_population), una por una, y se registra cada una.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .utils import now_iso

CONTINENTS = {"AF": "África", "AS": "Asia", "EU": "Europa", "NA": "Norteamérica", "OC": "Oceanía",
              "SA": "Sudamérica", "AN": "Antártida"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS geo_countries (
    code TEXT PRIMARY KEY, name TEXT NOT NULL, continent TEXT, population INTEGER, geonameid INTEGER
);
CREATE TABLE IF NOT EXISTS geo_regions (
    code TEXT PRIMARY KEY, country TEXT NOT NULL, name TEXT NOT NULL, geonameid INTEGER
);
CREATE TABLE IF NOT EXISTS geo_cities (
    geonameid INTEGER PRIMARY KEY, name TEXT NOT NULL, ascii TEXT, country TEXT NOT NULL, admin1 TEXT,
    population INTEGER, lat REAL, lon REAL
);
CREATE INDEX IF NOT EXISTS idx_cities_country ON geo_cities(country, population);
CREATE TABLE IF NOT EXISTS exploration (
    source TEXT NOT NULL, geo_key TEXT NOT NULL, query TEXT NOT NULL,
    last_run TEXT, results INTEGER, next_run TEXT, runs INTEGER DEFAULT 0,
    PRIMARY KEY (source, geo_key, query)
);
"""


class Geo:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    # -------------------------------------------------- carga
    def load(self, geo_dir: Path) -> dict:
        c = self.conn
        c.execute("BEGIN")
        for line in (geo_dir / "countryInfo.txt").read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            f = line.split("\t")
            c.execute("INSERT OR REPLACE INTO geo_countries VALUES (?,?,?,?,?)",
                      (f[0], f[4], f[8], int(f[7] or 0), int(f[16] or 0) if f[16].isdigit() else None))
        for line in (geo_dir / "admin1CodesASCII.txt").read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if len(f) >= 4:
                c.execute("INSERT OR REPLACE INTO geo_regions VALUES (?,?,?,?)", (f[0], f[0].split(".")[0], f[1],
                                                                                   int(f[3] or 0)))
        with (geo_dir / "cities15000.txt").open(encoding="utf-8") as fh:
            for line in fh:
                f = line.rstrip("\n").split("\t")
                if len(f) < 15:
                    continue
                c.execute("INSERT OR REPLACE INTO geo_cities VALUES (?,?,?,?,?,?,?,?)",
                          (int(f[0]), f[1], f[2], f[8], f"{f[8]}.{f[10]}", int(f[14] or 0), float(f[4]), float(f[5])))
        c.execute("COMMIT")
        return self.stats()

    def stats(self) -> dict:
        q = lambda s: self.conn.execute(s).fetchone()[0]  # noqa: E731
        return {"countries": q("SELECT COUNT(*) FROM geo_countries"), "regions": q("SELECT COUNT(*) FROM geo_regions"),
                "cities": q("SELECT COUNT(*) FROM geo_cities"), "explored": q("SELECT COUNT(*) FROM exploration"),
                "explored_countries": q("SELECT COUNT(DISTINCT substr(geo_key,1,2)) FROM exploration "
                                        "WHERE geo_key GLOB '[A-Z][A-Z]*'")}

    # -------------------------------------------------- consultas
    def country(self, code: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM geo_countries WHERE code=?", (code.upper(),)).fetchone()
        return dict(r) if r else None

    def countries(self, continent: str | None = None) -> list[dict]:
        sql = "SELECT * FROM geo_countries"
        args: tuple = ()
        if continent:
            sql += " WHERE continent=?"
            args = (continent,)
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY population DESC", args)]

    def cities(self, country: str, min_population: int = 300_000, limit: int = 50, merge_km: float = 25) -> list[dict]:
        """Ciudades más pobladas, sin redundancias: se omite la que esté a < merge_km de una mayor ya elegida
        (p. ej. Brooklyn/Queens dentro de Nueva York): una búsqueda en la ciudad grande ya las cubre."""
        import math
        rows = self.conn.execute(
            "SELECT c.*, r.name AS region FROM geo_cities c LEFT JOIN geo_regions r ON r.code=c.admin1 "
            "WHERE c.country=? AND c.population>=? ORDER BY c.population DESC LIMIT ?",
            (country.upper(), min_population, limit * 4)).fetchall()
        chosen: list[dict] = []
        for r in map(dict, rows):
            near = any(6371 * 2 * math.asin(math.sqrt(
                math.sin(math.radians(r["lat"] - c["lat"]) / 2) ** 2 + math.cos(math.radians(r["lat"])) *
                math.cos(math.radians(c["lat"])) * math.sin(math.radians(r["lon"] - c["lon"]) / 2) ** 2)) < merge_km
                for c in chosen)
            if not near:
                chosen.append(r)
            if len(chosen) >= limit:
                break
        return chosen

    @staticmethod
    def city_label(city: dict) -> str:
        """Texto de ubicación para portales: «Austin, Texas, United States»."""
        parts = [city["name"], city.get("region")]
        return ", ".join(p for p in parts if p)

    # -------------------------------------------------- exploración
    def due(self, source: str, geo_key: str, query: str) -> bool:
        r = self.conn.execute("SELECT next_run FROM exploration WHERE source=? AND geo_key=? AND query=?",
                              (source, geo_key, query)).fetchone()
        return r is None or not r["next_run"] or r["next_run"] <= now_iso()

    def record(self, source: str, geo_key: str, query: str, results: int, ttl_hours: int = 72) -> None:
        nxt = (datetime.now() + timedelta(hours=ttl_hours)).replace(microsecond=0).isoformat()
        self.conn.execute(
            "INSERT INTO exploration(source, geo_key, query, last_run, results, next_run, runs) VALUES (?,?,?,?,?,?,1) "
            "ON CONFLICT(source, geo_key, query) DO UPDATE SET last_run=excluded.last_run, results=excluded.results, "
            "next_run=excluded.next_run, runs=runs+1", (source, geo_key, query, now_iso(), results, nxt))
