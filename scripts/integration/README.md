# Pruebas de integración contra PostgreSQL real

Ejecutan los handlers y consumidores **reales** (con el `common.db` del layer, pg8000 y SSL) contra
PostgreSQL 16 con SSL y SCRAM, igual que RDS. SNS se simula: los eventos publicados se capturan y se verifican.
Detectan errores de SQL que las pruebas unitarias con mocks no ven (tipos de parámetros, migraciones,
transacciones, aislamiento entre schemas).

```bash
# 1. Base de prueba con SSL (RDS lo exige; sin SSL no se ejercita el mismo camino de
#    autenticación). Puerto 55432 para no chocar con un PostgreSQL local.
#    En Git Bash anteponer MSYS_NO_PATHCONV=1 para que no convierta las rutas /etc/ssl.
docker run -d --name servidesk-pg -e POSTGRES_USER=servidesk_admin \
  -e POSTGRES_PASSWORD=localpass123 -p 55432:5432 postgres:16 \
  -c ssl=on -c ssl_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem \
  -c ssl_key_file=/etc/ssl/private/ssl-cert-snakeoil.key

# 2. Dependencias del layer (pg8000, PyJWT)
npm run layer

# 3. Pruebas (cada una recrea su base db_<servicio>)
python scripts/integration/it_identity.py
python scripts/integration/it_services.py cmdb
python scripts/integration/it_services.py incidents
python scripts/integration/it_services.py problems
python scripts/integration/it_services.py changes
python scripts/integration/it_services.py requests

# 4. Flujo completo de la demo entre los 6 servicios (bus SNS -> SQS en memoria,
#    suscripciones y FilterPolicy leídas de los serverless.yml reales)
python scripts/integration/it_e2e.py

# 5. Limpieza
docker rm -f servidesk-pg
```

En Windows, si la consola no muestra bien las tildes: `set PYTHONIOENCODING=utf-8` (cmd) o
`$env:PYTHONIOENCODING="utf-8"` (PowerShell).
