"""Conexión a RDS con aislamiento por schema de tenant (Patrón 2).

Las credenciales salen de AWS Secrets Manager (DB_SECRET_ARN: username, password, host, port).
Sin DB_SECRET_ARN se usan DB_USER / DB_PASSWORD / DB_HOST (pruebas locales con Docker).
"""
import json
import os
import re
import ssl

import pg8000.exceptions
import pg8000.native

_SCHEMA_RE = re.compile(r"^tenant_[a-z0-9_]+$")
_conn = None  # se reutiliza entre invocaciones de la misma Lambda

# RDS PostgreSQL 16 exige SSL. Para el laboratorio no verificamos el certificado;
# en producción se usaría el bundle de CA de RDS.
_ssl = ssl.create_default_context()
_ssl.check_hostname = False
_ssl.verify_mode = ssl.CERT_NONE


_secret = None  # caché del secreto: una llamada a Secrets Manager por contenedor


def _read_secret(refresh=False):
    from common.secrets import get_secret

    return json.loads(get_secret(os.environ["DB_SECRET_ARN"], refresh=refresh))


def db_credentials(refresh=False):
    """{user, password, host, port} desde Secrets Manager (o desde variables de entorno en local)."""
    global _secret
    if not os.environ.get("DB_SECRET_ARN"):
        return {
            "user": os.environ["DB_USER"],
            "password": os.environ["DB_PASSWORD"],
            "host": os.environ["DB_HOST"],
            "port": 5432,
        }
    if _secret is None or refresh:
        _secret = _read_secret(refresh=refresh)
    return {
        "user": _secret["username"],
        "password": _secret["password"],
        "host": _secret.get("host") or os.environ["DB_HOST"],
        "port": int(_secret.get("port") or 5432),
    }


def connect(database, **overrides):
    """Abre una conexión nueva a `database`. Si la autenticación falla (p. ej. la contraseña
    se rotó en Secrets Manager), vuelve a leer el secreto y reintenta una vez."""
    for attempt in range(2):
        params = {**db_credentials(refresh=attempt > 0), "ssl_context": _ssl, **overrides}
        try:
            return pg8000.native.Connection(database=database, **params)
        except pg8000.exceptions.DatabaseError as exc:
            # 28P01 = invalid_password; solo tiene sentido reintentar si hay secreto
            code = exc.args[0].get("C") if exc.args and isinstance(exc.args[0], dict) else None
            if attempt or code != "28P01" or not os.environ.get("DB_SECRET_ARN"):
                raise


def get_conn():
    global _conn
    if _conn is None:
        _conn = connect(os.environ["DB_NAME"])
    return _conn


def tenant_conn(schema: str):
    """Devuelve una conexión con search_path apuntando al schema del tenant.

    El schema SIEMPRE viene del contexto del authorizer, nunca del body o query.
    """
    if not _SCHEMA_RE.match(schema or ""):
        raise PermissionError("schema de tenant inválido")
    conn = get_conn()
    conn.run(f"SET search_path TO {schema}")
    return conn


def ensure_database():
    """Crea la base lógica del microservicio (DB_NAME) si aún no existe."""
    admin = connect("postgres")
    name = os.environ["DB_NAME"]
    if not admin.run("SELECT 1 FROM pg_database WHERE datname = :n", n=name):
        admin.run(f"CREATE DATABASE {name}")
    admin.close()
