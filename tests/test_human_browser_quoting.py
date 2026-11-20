"""El escape de rutas para PowerShell no debe romperse con apóstrofes ni comodines."""
from pathlib import Path

from cvtitan.apply.human_browser import _ps_like


def test_apostrophe_is_doubled():
    assert "''" in _ps_like(Path("C:/Users/O'Brien/data/browser-profile"))


def test_wildcards_are_escaped():
    out = _ps_like(Path("C:/data[1]/p*"))
    assert "`[" in out and "`]" in out and "`*" in out
