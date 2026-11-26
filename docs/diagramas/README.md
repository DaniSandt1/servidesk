# Diagramas

| Archivo | Contenido |
| --- | --- |
| `1b_diagrama_arquitectura_v2.png` | Arquitectura de solución: RDS `servidesk-db-dev` en subredes privadas y credenciales en Secrets Manager |
| `servidesk_arquitectura_v2.drawio` | Fuente editable de la arquitectura (se genera con `python docs/diagramas/build_arquitectura_v2.py`) |
| `2_er_identity.png` … `7_er_requests.png` | Diagrama E/R de la base de cada microservicio |

La fuente editable de los E/R (`servidesk_er.drawio`, una página por microservicio) no se versiona: se
genera en local con `python docs/diagramas/build_diagrams.py`. Los `.drawio` se abren con
[draw.io](https://app.diagrams.net) o draw.io Desktop. Los scripts también exportan los PNG si draw.io
Desktop está instalado, así que los cambios conviene hacerlos en el script para que estilo y datos sigan
alineados con el código.

Criterios de los E/R: todas las bases son PostgreSQL (relacionales), así que solo se dibujan como
entidades las tablas reales con sus FK. Las columnas JSONB se documentan con un ejemplo de su estructura
JSON (no como tablas), las referencias a otro microservicio van punteadas hacia cajas grises (no hay FK
entre bases) y las tablas técnicas sin relaciones (idempotencia de SQS) van en una nota.
