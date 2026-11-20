# Política de seguridad

TITAN CV maneja datos personales (perfil, declaraciones legales, sesiones de navegador), por lo que la seguridad importa.

## Reportar una vulnerabilidad

**No abras un issue público.** Usa *Security > Report a vulnerability* (aviso privado de GitHub) en este repositorio. Incluye pasos para reproducir y el impacto. Intentaremos responder en pocos días.

## Alcance

Son de interés, por ejemplo: fuga de datos personales a logs, informes o servicios externos; evasión del enmascarado (`cvtitan/privacy.py`); envíos sin `send_enabled`; ejecución de comandos mediante rutas o entradas manipuladas; manejo de secretos (`.env`, `data/browser-profile/`).

## Si subiste datos personales por error

Rota de inmediato cualquier credencial expuesta y avisa a los mantenedores: borrar el commit no basta, el historial de Git puede estar copiado.

## Buenas prácticas para usuarios

- No subas `candidate/*` (salvo `*.example.yaml`), `data/` ni `.env`.
- No compartas `data/browser-profile/`: contiene sesiones iniciadas.
- Mantén `send_enabled: false` hasta revisar varias misiones sin envío.
