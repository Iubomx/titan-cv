"""Modo SHOWCASE: el centro de mando con datos 100 % SIMULADOS, para demostraciones.

- Todo está rotulado: misión «SHOWCASE // SIMULATED DATA», cada evento con [SIM] y el informe final también.
- No navega, no postula, no escribe en la base de datos ni en el historial real (MEMORY queda vacío).
- Separado del modo real a propósito: mezclar cifras inventadas con las reales haría creer que se postuló o se
  encontró algo que no existe.
"""
from __future__ import annotations

import random
import threading
import time

from .. import telemetry

COMPANIES = ["Andes Data Labs", "Atacama Mining Tech", "Pacific Cloud Co", "Nimbus Analytics", "Cordillera Systems",
             "Quantum Fleet", "Austral AI", "Copper Grid", "Northwind Software", "Helix Automation", "Orion Ops",
             "Vertex Mining Digital", "Lumen Robotics", "Sierra BI", "Polar Dispatch"]
ROLES = ["Mine Controller", "Dispatch Coordinator", "Data Analyst", "Python Developer", "FMS Specialist",
         "BI Developer", "Automation Engineer", "Full Stack Engineer", "Support Engineer", "AI Engineer",
         "Remote Operations Controller", "Analytics Engineer", "Backend Engineer", "Reporting Analyst"]
SOURCES = ["Get on Board", "Computrabajo", "Chiletrabajos", "LinkedIn", "Greenhouse", "Lever", "Remotive",
           "We Work Remotely", "Jobicy", "Himalayas"]
COUNTRIES = ["Chile", "Peru", "Argentina", "Colombia", "Mexico", "Brazil", "Canada", "United States", "Spain",
             "Australia", "Germany", "United Kingdom"]
CITIES = ["Santiago", "Antofagasta", "Calama", "Iquique", "Copiapo", "La Serena", "Lima", "Bogota", "Toronto",
          "Perth", "Madrid", "Buenos Aires"]


def run(seconds: float = 60.0, seed: int | None = None, stop: threading.Event | None = None) -> None:
    """Alimenta el estado del centro de mando con una misión simulada durante `seconds`."""
    rng = random.Random(seed)
    stop = stop or threading.Event()
    say = lambda m, lvl=None: telemetry.log(f"[SIM] {m}", lvl)  # noqa: E731
    telemetry.mission("SHOWCASE // SIMULATED DATA", "showcase")
    end = time.time() + seconds
    phases = [("LINE A · CHILE", "Scanning job boards", "TITAN-SCOUT"), ("LINE A · CHILE", "Rules, fit and scoring",
              "TITAN-MATCH"), ("LINE B · GLOBAL", "Scanning global ATS boards", "TITAN-SCOUT"),
              ("LINE B · GLOBAL", "Eligibility, fit and scoring", "TITAN-MATCH"),
              ("LINES A + B", "Processing applications", "TITAN-APPLY")]
    for i, (line, label, agent) in enumerate(phases, 1):
        if stop.is_set():
            break
        telemetry.stage(line, i, len(phases), label + " [SIM]")
        telemetry.agent(agent, "ACTIVE", "simulated workload")
        phase_end = min(end, time.time() + seconds / len(phases))
        total_apply = rng.randint(14, 22) if agent == "TITAN-APPLY" else 0
        if total_apply:
            telemetry.apply_begin(total_apply)
        done = 0
        while time.time() < phase_end and not stop.is_set():
            if agent == "TITAN-SCOUT":
                src = rng.choice(SOURCES)
                n = rng.randint(40, 380)
                telemetry.portal(src, [None] * n)
                telemetry.count("discovered", n)
                telemetry.market([{"source": src, "company": rng.choice(COMPANIES), "country": rng.choice(COUNTRIES),
                                   "city": rng.choice(CITIES), "modality": rng.choice(["remote", "hybrid", "on-site"]),
                                   "fit": rng.randint(10, 95),
                                   "salary_usd": rng.choice([None, None, rng.randint(1800, 7500)])}
                                  for _ in range(n)])
                telemetry.explored(countries=[rng.choice(COUNTRIES)], cities=[rng.choice(CITIES)],
                                   companies=[rng.choice(COMPANIES)])
                say(f"{src}: {n} offers")
            elif agent == "TITAN-MATCH":
                n = rng.randint(30, 140)
                telemetry.count("analyzed", n)
                telemetry.count("compatible", rng.randint(1, 6))
                telemetry.count("discarded", n - 3)
                telemetry.count("duplicates", rng.randint(5, 40))
                say(f"scored {n} offers; top fit {rng.randint(60, 92)}.{rng.randint(0, 9)}")
            elif done < total_apply:
                role, company = rng.choice(ROLES), rng.choice(COMPANIES)
                url = f"https://showcase.invalid/{rng.getrandbits(48):x}"
                telemetry.apply_item(f"{role} - {company}")
                outcome = rng.choices(["applied: Application submitted and confirmed by the platform.",
                                       "pending: CAPTCHA (needs a human)", "skipped: Not eligible from Chile",
                                       "done: already sent (not re-sent)"], weights=[6, 2, 2, 1])[0]
                telemetry.apply_result(outcome, title=f"[SIM] {role} - {company}", url=url)
                say(f"{role} - {company}: {outcome.split(':')[0]}", "warn" if outcome.startswith("pending") else None)
                done += 1
            time.sleep(rng.uniform(0.4, 1.1))
        telemetry.agent(agent, "READY", "simulated workload")
    telemetry.finish()
