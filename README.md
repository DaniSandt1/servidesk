# ServiDesk — SaaS de gestión de servicios TI (multi-tenant, serverless, EDA)

Proyecto final de Cloud Computing. Monorepo con:

| Carpeta | Qué hay | Responsable |
| --- | --- | --- |
| `infra/` | RDS PostgreSQL (privada) + secreto en Secrets Manager, endpoints de VPC, SNS, S3, layer común, Lambda Authorizer | Vannia (+ José el authorizer) |
| `services/identity`, `services/cmdb` | Identidad (login/JWT) y CMDB | José |
| `services/incidents`, `services/problems` | Incidentes y Problemas | Ian |
| `services/changes`, `services/requests` | Cambios y Solicitudes | Daniel |
| `seed/` | Generador de 30 000 registros por servicio | Daniel |
| `frontend/` | React + Vite + TS, desplegado en Amplify | Mía |
| `docs/` | Diagramas | Vannia |

## Despliegue (AWS Academy Learner Lab)

> Guía completa paso a paso, para cualquier integrante en su propia cuenta: [docs/DEPLOY.md](docs/DEPLOY.md).

1. Copiar credenciales de *AWS Details* a `~/.aws/credentials` (caducan cada ~4 h).
2. No hace falta `.env`: la contraseña de RDS y la clave de los JWT las genera CloudFormation en AWS Secrets Manager.
3. `npm install`
4. `npm run deploy`  (instala el layer y despliega infra + 6 servicios con serverless-compose)
5. Ejecutar la función `migrate` de cada servicio, **empezando por identity** (crea `public.tenants` y las cuentas demo):
   `npx serverless identity:invoke --function migrate` y luego igual para cmdb, incidents, problems, changes y requests.
6. Probar el login con una cuenta demo (ver `services/identity/README.md`), por ejemplo
   `andina` / `lucia.paredes@andina.pe` / `Andina#2026`.

Atajos (usan `~/.aws/credentials`):

| Paso | Comando |
| --- | --- |
| URLs de las 6 APIs + `frontend/.env.local` | `python scripts/aws_check.py urls` |
| Migraciones en orden (identity primero) | `python scripts/aws_check.py migrate` |
| Prueba de humo con 2 tenants (HTTP + eventos SNS/SQS) | `python scripts/aws_check.py smoke` |
| Datos ficticios: 30 000 por microservicio (S3 → Lambda `seedLoader` → COPY) | `python seed/generate.py` y `python seed/load.py all` |
| Contrato frontend ↔ APIs desplegadas | `python scripts/frontend_contract.py` |
| Frontend en Amplify (build + despliegue manual) | `python scripts/deploy_frontend.py` |
