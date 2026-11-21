# Cifrado en reposo (`titan vault`)

Protege tus datos personales cuando no usas TITAN (equipo compartido, copia de seguridad, robo del portátil).

```powershell
pip install -e ".[vault]"        # instala cryptography
.\titan vault status             # cuántos archivos cifraría
.\titan vault lock               # pide la passphrase dos veces y cifra
.\titan vault unlock             # restaura los archivos
```

**Qué cifra:** `candidate/*.yaml` (menos las plantillas `*.example.yaml`), `candidate/documents/`, `.env`,
`data/cvtitan.db`, `data/auto/refs.json` y `data/outputs/` (CV generados). Todo queda en `vault.titanvault`.
**Qué no cifra:** `data/browser-profile/` (Chrome lo usa y puede estar abierto). Protégelo con el cifrado de disco de tu
sistema (BitLocker, FileVault, LUKS).

## Garantías y límites
- Cifrado Fernet (AES-128-CBC + HMAC) con clave derivada por scrypt de tu passphrase.
- `lock` verifica que todo se descifra idéntico **antes** de borrar los originales; `unlock` verifica la passphrase y los
  hashes antes de escribir, y no sobrescribe archivos existentes salvo con `--force`.
- **Si olvidas la passphrase, los datos NO se pueden recuperar.** No hay puerta trasera.
- Cierra TITAN, la web y Chrome antes de bloquear (la base de datos no debe estar en uso).
- `CVTITAN_VAULT_PASSPHRASE` permite automatizar, pero deja la passphrase en el entorno: prefiere la entrada interactiva.
- Nunca subas `vault.titanvault` a un repositorio (el escaneo del CI lo rechaza).
