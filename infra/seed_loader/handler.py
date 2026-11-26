"""Lambda seedLoader: carga los datos ficticios desde S3 a RDS con COPY ... FROM STDIN.

Lee s3://<SEED_BUCKET>/seed/<servicio>/<tenant>/manifest.json y sus CSV comprimidos
(generados por seed/generate.py) y los transmite sin descomprimir a disco ni a memoria:
S3 (StreamingBody) -> gzip -> pg8000 COPY.

Eventos:
    {"action": "load",  "service": "incidents", "tenant": "andina"}   # reemplaza los datos del tenant
    {"action": "count", "service": "incidents"}                        # filas por tabla y tenant

La carga es idempotente: en una sola transacción vacía (TRUNCATE ... CASCADE) las tablas del
servicio en el schema del tenant y vuelve a cargarlas. No toca catálogos de las migraciones
(ci_types, sla_policies) ni public.tenants.
"""

import gzip
import json
import os
import re
import time

import boto3

from common.db import _ssl  # mismo contexto SSL que el resto de Lambdas (RDS exige SSL)
from common.db import connect as db_connect  # credenciales desde Secrets Manager

TENANT_RE = re.compile(r"^[a-z0-9_]{2,30}$")
TABLE_RE = re.compile(r"^[a-z_]+$")

# Tablas que se vacían antes de cargar (CASCADE alcanza a las hijas) y tablas que se cuentan.
SERVICES = {
    "identity": {"truncate": ["users", "teams"],
                 "count": ["users", "teams", "team_members", "notifications"]},
    "cmdb": {"truncate": ["configuration_items"],
             "count": ["configuration_items", "ci_relations", "ci_history", "ci_types"]},
    "requests": {"truncate": ["catalog_categories"],
                 "count": ["service_requests", "catalog_items", "catalog_categories", "request_approvals"]},
    "incidents": {"truncate": ["incidents"],
                  "count": ["incidents", "incident_comments", "sla_policies"]},
    "problems": {"truncate": ["problems", "ci_incident_log"],
                 "count": ["problems", "problem_incidents", "known_errors"]},
    "changes": {"truncate": ["changes"],
                "count": ["changes", "change_cis", "change_approvals"]},
}
TENANTS = ["andina", "pacifico", "unitec"]


def connect(service, port=None, host=None, ssl_context=_ssl):
    overrides = {"ssl_context": ssl_context}
    if port:
        overrides["port"] = port
    if host:
        overrides["host"] = host
    return db_connect(f"db_{service}", **overrides)


def load_tenant(conn, service, tenant, manifest, open_table):
    """Vacía y carga las tablas del manifest en tenant_<tenant>. open_table(file) -> stream binario."""
    cfg = SERVICES[service]
    schema = f"tenant_{tenant}"
    started = time.time()
    loaded = {}
    conn.run("BEGIN")
    try:
        conn.run(f"SET LOCAL search_path TO {schema}")
        conn.run(f"TRUNCATE {', '.join(cfg['truncate'])} CASCADE")
        for spec in manifest["tables"]:
            table = spec["table"]
            columns = spec["columns"]
            if not TABLE_RE.match(table) or not all(TABLE_RE.match(c) for c in columns):
                raise ValueError(f"Nombre inválido en el manifest: {table}")
            with open_table(spec["file"]) as stream:
                conn.run(f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv, HEADER true)",
                         stream=stream)
            loaded[table] = conn.row_count
        for sql in manifest.get("post_sql", []):
            conn.run(sql)
        conn.run("COMMIT")
    except Exception:
        conn.run("ROLLBACK")
        raise
    for table in loaded:
        conn.run(f"ANALYZE {schema}.{table}")
    return {"loaded": loaded, "seconds": round(time.time() - started, 1)}


def count(conn, service):
    result = {}
    for tenant in TENANTS:
        schema = f"tenant_{tenant}"
        result[tenant] = {t: conn.run(f"SELECT COUNT(*) FROM {schema}.{t}")[0][0] for t in SERVICES[service]["count"]}
    return result


def handle(event, context):
    action = event.get("action", "load")
    service = event.get("service")
    if service not in SERVICES:
        raise ValueError(f"Servicio inválido: {service}")

    conn = connect(service)
    try:
        if action == "count":
            return {"service": service, "counts": count(conn, service)}

        tenant = event.get("tenant")
        if tenant not in TENANTS or not TENANT_RE.match(tenant):
            raise ValueError(f"Tenant inválido: {tenant}")

        s3 = boto3.client("s3")
        bucket = os.environ["SEED_BUCKET"]
        prefix = f"seed/{service}/{tenant}"
        manifest = json.loads(s3.get_object(Bucket=bucket, Key=f"{prefix}/manifest.json")["Body"].read())

        def open_table(file):
            body = s3.get_object(Bucket=bucket, Key=f"{prefix}/{file}")["Body"]
            return gzip.GzipFile(fileobj=body, mode="rb")

        result = load_tenant(conn, service, tenant, manifest, open_table)
        return {"service": service, "tenant": tenant, **result}
    finally:
        conn.close()
