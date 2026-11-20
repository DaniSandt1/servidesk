# Datos ficticios (F5)

**30 000 registros por microservicio**, 10 000 por tenant (andina, pacifico, unitec) en la tabla
principal de cada servicio, más sus tablas relacionadas:

| Servicio | Tabla principal | Tablas relacionadas (3 tenants) |
|---|---|---|
| identity | `users` 30 000 | `teams` 18, `team_members` ~4 000 |
| cmdb | `configuration_items` 30 000 | `ci_relations` ~10 000, `ci_history` 30 000 |
| requests | `service_requests` 30 000 | `catalog_categories` 15, `catalog_items` 36, `request_approvals` ~17 000 |
| incidents | `incidents` 30 000 | `incident_comments` ~30 000 |
| problems | `problems` 30 000 | `problem_incidents` ~18 000, `known_errors` ~19 500 |
| changes | `changes` 30 000 | `change_cis` ~40 000, `change_approvals` ~17 700 |

## Flujo

```text
seed/generate.py ──► seed/out/<servicio>/<tenant>/*.csv.gz + manifest.json
seed/load.py upload ──► S3  s3://servidesk-seed-<stage>-<cuenta>/seed/...
seed/load.py load ──► Lambda seedLoader (infra) ──► S3 → gzip → COPY ... FROM STDIN ──► RDS (schema del tenant)
seed/load.py count ──► SELECT COUNT(*) por servicio, tenant y tabla
```

```bash
python seed/generate.py          # ~15 s, 24 MB comprimidos (no se versiona: seed/out/)
python seed/load.py all          # sube, carga (~40 s) y cuenta
python seed/load.py count        # solo el conteo (captura para el informe)
```

## Coherencia entre servicios

- Los UUID son deterministas (`uuid5`): usuarios y equipos (`services/identity/handlers/tenant_data.py`),
  CI, incidentes, problemas y cambios. Así `reporter_id`, `requester_id`, `assignee_id`, `owner_team_id`,
  `ci_id`, `problem_id`, `fix_change_id` y `problem_incidents` apuntan a registros que existen en el
  otro microservicio, sin FK entre bases.
- Reglas de negocio respetadas: prioridad = impacto × urgencia, SLA por prioridad (`sla_due_at`,
  `sla_breached`), `resolved_at` solo en resueltos/cerrados, errores conocidos solo en problemas
  `known_error`/`resolved`/`closed`, aprobaciones CAB solo en cambios no estándar decididos, `form_data`
  válido contra el `form_schema` del catálogo, claves correlativas (`INC-000001`…).
- Fechas en los últimos 12–18 meses, más densas cerca de hoy (hay incidentes abiertos con SLA vencido).

## Cuentas

- Las 3 cuentas demo por tenant (ver `services/identity/README.md`) con su contraseña en PBKDF2.
- Los demás usuarios usan la **contraseña del tenant** (`Andina#2026`, `Pacifico#2026`, `Unitec#2026`).
- Roles por tenant: 17 admin + 3 demo, ~1 000 agent, ~9 000 customer.

## Carga idempotente

`seedLoader` (`infra/seed_loader/handler.py`) vacía las tablas del servicio en el schema del tenant
(`TRUNCATE … CASCADE`) y las vuelve a cargar en una sola transacción. No toca los catálogos que crean
las migraciones (`ci_types`, `sla_policies`) ni `public.tenants`; `sla_policy_id` se resuelve por prioridad
después del `COPY`. Las claves siguientes (`INC-010001`…) las calcula la API con `MAX(key)`.

Prueba local completa (migraciones + carga + lectura por la API) contra PostgreSQL con SSL:
`python scripts/integration/it_seed.py` (ver `scripts/integration/README.md`).
