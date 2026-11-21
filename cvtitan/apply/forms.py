"""Lectura y llenado de formularios web con Playwright, en todos los iframes de la página."""
from __future__ import annotations

import difflib
import re

from ..utils import normalize
from .platforms import ALREADY_APPLIED_TEXTS, BLOCKED_TEXTS, NEXT_TEXTS, SUBMIT_TEXTS, SUCCESS_TEXTS

# Devuelve los campos visibles del formulario activo (o del diálogo modal, como en LinkedIn Easy Apply).
EXTRACT_JS = r"""
() => {
  const root = [...document.querySelectorAll('dialog[open], [role="dialog"], [aria-modal="true"]')]
      .find(d => d.getBoundingClientRect().width > 0 && d.querySelector('input, select, textarea')) || document;
  const vis = el => { if (!el) return false; const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = el => el ? (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ') : '';
  const labelFor = el => {
    let l = '';
    if (el.id) { const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (lab) l = txt(lab); }
    if (!l && el.getAttribute('aria-labelledby'))
      l = el.getAttribute('aria-labelledby').split(/\s+/).map(i => txt(document.getElementById(i))).join(' ');
    if (!l) l = el.getAttribute('aria-label') || '';
    if (!l) { const lab = el.closest('label'); if (lab) l = txt(lab); }
    if (!l) { let c = el.parentElement;
      for (let i = 0; i < 4 && c && !l; i++) { const t = txt(c); if (t && t.length < 250) l = t; c = c.parentElement; } }
    if (!l) l = el.placeholder || el.name || '';
    return l.slice(0, 300);
  };
  let n = window.__cvtN || 0;
  const out = [], groups = {};
  for (const el of root.querySelectorAll('input, select, textarea')) {
    const tag = el.tagName;
    const type = tag === 'SELECT' ? 'select' : tag === 'TEXTAREA' ? 'textarea' : (el.type || 'text').toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes(type)) continue;
    const choice = type === 'radio' || type === 'checkbox';
    const visible = vis(el) || (choice && (vis(el.closest('label')) || (el.id && vis(document.querySelector(`label[for="${CSS.escape(el.id)}"]`)))));
    if (type !== 'file' && !visible) continue;
    if (el.disabled) continue;
    const role = (el.getAttribute('role') || '').toLowerCase();
    let lab = labelFor(el);
    if (type === 'checkbox' && lab.length < 25) {
      const fsq = el.closest('fieldset, [role="group"]');
      const prev = fsq && fsq.previousElementSibling ? txt(fsq.previousElementSibling) : '';
      if (prev && prev.length < 400) lab = (prev + ' ' + lab).trim();
    }
    if (type === 'checkbox' && lab.length < 25) {
      let c = el.parentElement;
      for (let k = 0; k < 8 && c; k++, c = c.parentElement) {
        const t = txt(c);
        if (t.length > lab.length + 10 && t.length < 400 && c.querySelectorAll('input').length <= 2) { lab = t; break; }
      }
    }
    if (/buscar|search/i.test(lab) && type === 'text' && !el.required) continue;
    if (!el.dataset.cvtId) el.dataset.cvtId = 'f' + (++n);
    const required = el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$/.test(lab) ||
        (type === 'checkbox' && /\*/.test(lab));
    if (type === 'radio') {
      const key = el.name || el.dataset.cvtId;
      const sameName = el.name ? [...root.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`)] : [el];
      // Texto de la opción: <label for> o <label> padre; si están vacíos (LinkedIn), el texto del contenedor
      // que encierra SOLO a este botón; el aria-label solo como último recurso.
      const optLabel = r => {
        let t = '';
        if (r.id) { const lab = document.querySelector(`label[for="${CSS.escape(r.id)}"]`); if (lab) t = txt(lab); }
        if (!t && r.closest('label')) t = txt(r.closest('label'));
        if (!t) { let c = r.parentElement;
          for (let k = 0; k < 4 && c && !t; k++, c = c.parentElement)
            if (c.querySelectorAll('input[type=radio]').length === 1) t = txt(c); }
        return t || r.getAttribute('aria-label') || r.value || '';
      };
      if (!groups[key]) {
        const fs = el.closest('fieldset');
        let q = fs && fs.querySelector('legend') ? txt(fs.querySelector('legend')) : '';
        const rg = el.closest('[role="radiogroup"]') || fs;
        if (!q && rg && rg.getAttribute('aria-labelledby'))
          q = rg.getAttribute('aria-labelledby').split(/\s+/).map(x => txt(document.getElementById(x))).join(' ');
        if (!q && rg) q = rg.getAttribute('aria-label') || '';
        if (!q) {   // todos los botones con el mismo aria-label: ese texto es la pregunta
          const al = sameName.map(r => r.getAttribute('aria-label') || '');
          if (al[0] && al.every(a => a === al[0])) q = al[0];
        }
        if (!q && rg && rg.previousElementSibling) q = txt(rg.previousElementSibling).slice(0, 300);
        if (!q) {
          const optTexts = sameName.map(optLabel).filter(Boolean);
          let c = el.parentElement;
          for (let k = 0; k < 7 && c && !q; k++, c = c.parentElement) {
            let t = txt(c);
            for (const o of optTexts) t = t.split(o).join(' ');
            t = t.replace(/\s+/g, ' ').trim();
            if (t.length > 3 && t.length < 300) q = t;
          }
        }
        if (!q) q = key;
        const prevText = rg && rg.previousElementSibling ? txt(rg.previousElementSibling) : '';
        const req = required || /\*/.test(q) || /\*/.test(prevText) || /obligatori|required/i.test(q);
        groups[key] = {id: el.dataset.cvtId, type: 'radio', name: key, label: q, required: req, options: [], value: ''};
        out.push(groups[key]);
      }
      const ol = optLabel(el);
      el.dataset.cvtGroup = groups[key].id;
      el.dataset.cvtOption = ol;
      groups[key].options.push(ol);
      if (el.checked) groups[key].value = ol;
      if (required) groups[key].required = true;
      continue;
    }
    const f = {id: el.dataset.cvtId, type, role, name: el.name || '', label: lab, required,
               value: type === 'file' ? ((el.files && el.files.length) ? el.files[0].name : '')
                    : type === 'password' ? (el.value ? '[oculto]' : '') : (el.value || '')};   // nunca leer contraseñas
    if (type === 'select') f.options = [...el.options].map(o => o.text.trim()).filter(Boolean);
    if (type === 'checkbox') f.checked = el.checked;
    if (type === 'file') f.accept = el.accept || '';
    out.push(f);
  }
  window.__cvtN = n;
  return out;
}
"""

BUTTONS_JS = r"""
() => {
  const root = [...document.querySelectorAll('dialog[open], [role="dialog"], [aria-modal="true"]')]
      .find(d => d.getBoundingClientRect().width > 0 && d.querySelector('button, [type=submit]')) || document;
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  let n = window.__cvtB || 0;
  const out = [];
  for (const el of root.querySelectorAll('button, input[type=submit], input[type=button], a[role=button], [role=button], a')) {
    if (!vis(el)) continue;
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
    if (!text || text.length > 60) continue;
    if (!el.dataset.cvtBtn) el.dataset.cvtBtn = 'b' + (++n);
    out.push({id: el.dataset.cvtBtn, text, tag: el.tagName.toLowerCase(),
              disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
              type: (el.type || '').toLowerCase()});
  }
  window.__cvtB = n;
  return out;
}
"""

CAPTCHA_HINTS = ("recaptcha", "hcaptcha", "turnstile", "captcha", "arkoselabs", "funcaptcha")


# ---------------------------------------------------------------------- lectura
def frames(page):
    return [f for f in page.frames if not f.is_detached()]


def extract_fields(page) -> list[dict]:
    fields = []
    for i, frame in enumerate(frames(page)):
        try:
            for f in frame.evaluate(EXTRACT_JS):
                f["frame"] = i
                fields.append(f)
        except Exception:
            continue
    return fields


def _norm_btn(text: str) -> str:
    return re.sub(r"[^a-z ]", "", normalize(text)).strip()


def find_buttons(page) -> dict:
    """Clasifica botones visibles en next / submit / apply."""
    found: dict[str, list] = {"next": [], "submit": [], "all": []}
    for i, frame in enumerate(frames(page)):
        try:
            buttons = frame.evaluate(BUTTONS_JS)
        except Exception:
            continue
        for b in buttons:
            b["frame"] = i
            t = _norm_btn(b["text"])
            found["all"].append(b)
            if b["disabled"]:
                continue
            if any(t == x or t.startswith(x + " ") for x in NEXT_TEXTS):
                found["next"].append(b)
            elif any(t == x or t.startswith(x + " ") or (len(x) > 8 and x in t) for x in SUBMIT_TEXTS):
                found["submit"].append(b)
    return found


def disabled_progress(page) -> bool:
    """¿Hay un botón «Siguiente/Enviar» visible pero deshabilitado?"""
    for b in find_buttons(page)["all"]:
        if not b["disabled"]:
            continue
        t = _norm_btn(b["text"])
        if any(t == x or t.startswith(x + " ") for x in NEXT_TEXTS) or                 any(t == x or t.startswith(x + " ") or (len(x) > 8 and x in t) for x in SUBMIT_TEXTS):
            return True
    return False


def nudge_inputs(page) -> int:
    """Teclea y borra un espacio al final de cada editor/campo de texto visible YA completo, para que el sitio
    ejecute su validación (no cambia el contenido). Devuelve cuántos campos se tocaron."""
    touched = 0
    for frame in frames(page):
        try:
            boxes = frame.locator("[contenteditable='true']:visible, trix-editor:visible, textarea:visible")
            n = min(boxes.count(), 12)
        except Exception:
            continue
        for i in range(n):
            box = boxes.nth(i)
            try:
                text = box.input_value(timeout=1000) if box.evaluate("e => e.tagName") == "TEXTAREA"                     else box.inner_text(timeout=1000)
                if not text.strip():
                    continue
                box.click(timeout=3000)
                page.keyboard.press("Control+End")
                page.keyboard.type(" ")
                page.keyboard.press("Backspace")
                box.evaluate("e => { e.dispatchEvent(new Event('input', {bubbles: true}));"
                             " e.dispatchEvent(new Event('change', {bubbles: true})); e.blur(); }")
                touched += 1
            except Exception:
                continue
    return touched


def find_apply_button(page, texts: tuple[str, ...]) -> dict | None:
    wanted = [_norm_btn(t) for t in texts]
    for b in find_buttons(page)["all"]:
        if b["disabled"]:
            continue
        t = _norm_btn(b["text"])
        if any(t == w or t.startswith(w) for w in wanted):
            return b
    return None


def click_button(page, button: dict) -> None:
    """Clic en un botón detectado. Si el formulario se redibujó y perdió la marca data-cvt-btn (React),
    se busca de nuevo por su texto visible."""
    frame = frames(page)[button["frame"]]
    if DEMO:
        _demo_show(page, frame.locator(f'[data-cvt-btn="{button["id"]}"]').first, "CLICK", button.get("text", "")[:60])
    try:
        frame.locator(f'[data-cvt-btn="{button["id"]}"]').first.click(timeout=5000)
        return
    except Exception:
        pass
    text = (button.get("text") or "").strip()
    if not text:
        raise RuntimeError("No pude volver a encontrar el botón (sin texto).")
    for loc in (frame.get_by_role("button", name=text, exact=True), frame.get_by_text(text, exact=True)):
        candidates = [loc.nth(i) for i in range(loc.count())]
        visible = [c for c in candidates if c.is_visible()]
        if visible:
            visible[-1].click(timeout=8000)     # el último visible suele ser el del diálogo abierto
            return
    raise RuntimeError(f"No pude volver a encontrar el botón «{text}».")


def has_captcha(page) -> bool:
    for frame in frames(page):
        url = (frame.url or "").lower()
        if any(h in url for h in CAPTCHA_HINTS) and "invisible" not in url:
            try:
                el = frame.frame_element()
                box = el.bounding_box()
                if box and box["width"] > 60 and box["height"] > 60:
                    return True
            except Exception:
                return True
    return False


def needs_login(page) -> bool:
    url = (page.url or "").lower()
    if re.search(r"/(login|signin|sign-in|auth|acceso|ingresar|uas/login|checkpoint)", url):
        return True
    try:
        return page.locator("input[type=password]:visible").count() > 0
    except Exception:
        return False


def page_text(page) -> str:
    try:
        return normalize(page.inner_text("body", timeout=5000))
    except Exception:
        return ""


def submitted(page) -> bool:
    text = page_text(page)
    return any(s in text for s in SUCCESS_TEXTS)


def validation_errors(page) -> list[str]:
    errors = []
    for frame in frames(page):
        try:
            errors += frame.evaluate(r"""() => [...document.querySelectorAll(
                '[role=alert], .error, .errors, .field-error, .invalid-feedback, [aria-invalid=true] ~ *, .artdeco-inline-feedback--error')]
                .map(e => (e.innerText || '').trim()).filter(t => t && t.length < 200)""")
        except Exception:
            continue
    return list(dict.fromkeys(errors))[:10]


# ---------------------------------------------------------------------- llenado
def _best_option(value: str, options: list[str]) -> str | None:
    if not options:
        return None
    nv = normalize(value)
    norm = {normalize(o): o for o in options}
    if nv in norm:
        return norm[nv]
    for k, o in norm.items():
        if nv and (nv in k or k in nv) and len(k) > 1:
            return o
    match = difflib.get_close_matches(nv, list(norm), n=1, cutoff=0.6)
    return norm[match[0]] if match else None


def _attr(loc, name: str) -> str | None:
    try:
        return loc.get_attribute(name, timeout=2000)
    except Exception:
        return None


def _fill_combobox(page, loc, value: str) -> None:
    """Lista con buscador: clic, escribir, elegir la opción visible que mejor coincide (o Enter)."""
    loc.click(timeout=5000, force=True)
    page.keyboard.type(value, delay=40)
    page.wait_for_timeout(900)
    options = page.locator('[role="option"]:visible, .select__option:visible, [id*="-option-"]:visible')
    texts = [options.nth(i).inner_text().strip() for i in range(min(options.count(), 40))]
    best = _best_option(value, texts) if texts else None
    if best is not None:
        options.nth(texts.index(best)).click(timeout=5000)
    else:
        page.keyboard.press("Enter")
    page.wait_for_timeout(300)


def _is_checked(frame, field: dict, loc) -> bool:
    try:
        if field.get("_stable"):
            return frame.locator(f'[id="{field["_stable"]}"]').first.is_checked(timeout=2000)
        return loc.is_checked(timeout=2000)
    except Exception:
        return False


# Modo demostración (`cvtitan demo`): {"delay": ms, "say": función}. None = robot normal.
DEMO: dict | None = None
_HIGHLIGHT_JS = ("e => { e.scrollIntoView({block: 'center'}); e.style.outline = '3px solid #5FB3F9';"
                 " e.style.outlineOffset = '2px'; e.style.transition = 'outline 0.2s'; }")
_UNHIGHLIGHT_JS = "e => { e.style.outline = '2px solid #4CC38A'; }"


def _demo_show(page, locator, tag: str, text: str) -> None:
    """Resalta el elemento (recuadro azul), lo narra en la terminal y espera para que se vea."""
    if not DEMO:
        return
    try:
        locator.evaluate(_HIGHLIGHT_JS)
    except Exception:
        pass
    from ..privacy import redact
    DEMO["say"](redact(f"  [{tag}] {text}"))
    page.wait_for_timeout(int(DEMO.get("delay", 600)))


def fill_field(page, field: dict, value) -> bool:
    """Escribe un valor (o archivo) en un campo. Devuelve True si se pudo."""
    frame = frames(page)[field["frame"]]
    if DEMO:
        shown = str(value).replace("\\", "/").split("/")[-1] if field["type"] == "file" else str(value)
        sel = f'[data-cvt-group="{field["id"]}"]' if field["type"] == "radio" else f'[data-cvt-id="{field["id"]}"]'
        _demo_show(page, frame.locator(sel).first, "FILL", f"{field['label'][:60]}  =  {shown[:80]}")
        ok = _fill_field(page, field, value, frame)
        try:
            frame.locator(sel).first.evaluate(_UNHIGHLIGHT_JS)
        except Exception:
            pass
        if not ok:
            DEMO["say"](f"         could not fill «{field['label'][:50]}»")
        return ok
    return _fill_field(page, field, value, frame)


def _fill_field(page, field: dict, value, frame) -> bool:
    t = field["type"]
    try:
        if t == "radio":
            option = _best_option(str(value), field.get("options", []))
            if not option:
                return False
            loc = frame.locator(f'[data-cvt-group="{field["id"]}"]')
            for i in range(loc.count()):
                el = loc.nth(i)
                if el.get_attribute("data-cvt-option") == option:
                    # Tras marcar, algunos formularios (React) redibujan y pierden data-cvt-*: se verifica por el
                    # nombre del grupo + posición, que sí se mantiene.
                    name = el.get_attribute("name")
                    stable = frame.locator(f'input[type=radio][name="{name}"]').nth(i) if name else el

                    def checked(stable=stable) -> bool:
                        try:
                            return stable.is_checked(timeout=2000)
                        except Exception:
                            return False
                    try:
                        el.check(force=True, timeout=5000)
                    except Exception:
                        # Botones ocultos tras un diseño propio (LinkedIn): clic en su contenedor y, si no basta,
                        # se marca como lo haría el usuario y se avisa al formulario.
                        try:
                            el.evaluate("e => (e.closest('label') || e.parentElement.parentElement || e).click()")
                        except Exception:
                            pass
                        if not checked():
                            rid = stable.get_attribute("id")
                            try:
                                if rid:
                                    frame.locator(f'label[for="{rid}"]').first.click(timeout=4000)
                            except Exception:
                                pass
                            if not checked():
                                stable.evaluate("e => e.click()")
                    for _ in range(6):                # algunos formularios confirman la selección con retraso
                        if checked():
                            return True
                        page.wait_for_timeout(250)
                    return checked()
            return False
        loc = frame.locator(f'[data-cvt-id="{field["id"]}"]').first
        if t == "file":
            loc.set_input_files(str(value), timeout=10000)
        elif t == "select":
            option = _best_option(str(value), field.get("options", []))
            if not option:
                return False
            loc.select_option(label=option, timeout=5000)
        elif t == "checkbox":
            want = normalize(str(value)) in ("si", "yes", "true", "1", "acepto", "x", "on")
            field["_stable"] = loc.get_attribute("id") or ""
            if want != bool(field.get("checked")):
                try:
                    loc.set_checked(want, force=True, timeout=5000)
                    return True
                except Exception:
                    pass
                # Casilla oculta tras un diseño propio (LinkedIn/React): un solo clic nativo sobre su etiqueta
                # visible (o la casilla). El formulario puede redibujarse y perder data-cvt-id; el siguiente
                # paso del robot vuelve a leer el formulario y comprueba el estado real.
                loc.evaluate("""el => {
                    const l = (el.id && document.querySelector('label[for="' + CSS.escape(el.id) + '"]'))
                              || (el.nextElementSibling && el.nextElementSibling.tagName === 'LABEL' && el.nextElementSibling)
                              || el.closest('label');
                    (l || el).click();
                }""", timeout=5000)
                page.wait_for_timeout(500)
                return True
        elif field.get("role") == "combobox" or _attr(loc, "aria-autocomplete") in ("list", "both") \
                or _attr(loc, "role") == "combobox":
            _fill_combobox(page, loc, str(value))
        else:
            try:
                loc.fill(str(value), timeout=5000)
            except Exception:
                _fill_combobox(page, loc, str(value))      # inputs de solo lectura que abren una lista
        return True
    except Exception as e:
        import sys
        print(f"[fill_field] {field.get('type')} «{str(field.get('label'))[:60]}»: {type(e).__name__}: "
              f"{str(e).splitlines()[0][:200]}", file=sys.stderr)
        return False


def page_text_has(page, texts) -> str | None:
    """Devuelve el primer texto de `texts` presente en la página (normalizado), o None."""
    from ..utils import normalize
    try:
        body = normalize(page.inner_text("body", timeout=5000))
    except Exception:
        return None
    return next((t for t in texts if normalize(t) in body), None)


def already_applied(page) -> bool:
    return page_text_has(page, ALREADY_APPLIED_TEXTS) is not None


def blocked_reason(page) -> str | None:
    return page_text_has(page, BLOCKED_TEXTS)


SENSITIVE_LABEL = re.compile(r"(?i)password|contrase|clave|passcode|\bpin\b|token|secret|\brut\b|\bdni\b|"
                             r"pasaporte|passport|social security|\bssn\b|tarjeta|card number|cvv|cuenta bancaria")


def redact_fields(fields: list[dict]) -> list[dict]:
    """Copia de los campos apta para guardar en disco: sin valores de contraseñas ni de identificadores."""
    out = []
    for f in fields:
        g = dict(f)
        if g.get("type") in ("password", "hidden") or SENSITIVE_LABEL.search(f"{g.get('label', '')} {g.get('name', '')}"):
            g["value"] = "[oculto]" if g.get("value") else ""
        out.append(g)
    return out


def redact_html(html_text: str) -> str:
    """Quita atributos value de inputs de contraseña y campos ocultos (tokens) antes de guardar el HTML."""
    def clean(m):
        tag = m.group(0)
        if re.search(r"""(?i)type\s*=\s*["']?(password|hidden)""", tag):
            tag = re.sub(r"""(?i)\svalue\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", ' value="[oculto]"', tag)
        return tag
    return re.sub(r"(?is)<input\b[^>]*>", clean, html_text)
