"""Lectura de AWS Secrets Manager con caché por contenedor de Lambda.

Las Lambdas dentro de la VPC no tienen internet: usan el endpoint de VPC propio
(SECRETS_ENDPOINT_URL). Fuera de la VPC (authorizer) se usa el endpoint público.
"""
import os

_cache = {}


def get_secret(secret_id: str, refresh: bool = False) -> str:
    """SecretString del secreto; se lee una vez por contenedor salvo refresh=True."""
    if refresh or secret_id not in _cache:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "secretsmanager",
            endpoint_url=os.environ.get("SECRETS_ENDPOINT_URL") or None,
            config=Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 2}),
        )
        _cache[secret_id] = client.get_secret_value(SecretId=secret_id)["SecretString"]
    return _cache[secret_id]


def jwt_secret() -> str:
    """Clave HS256 de los JWT: de Secrets Manager (JWT_SECRET_ARN) o, en pruebas locales, de JWT_SECRET."""
    arn = os.environ.get("JWT_SECRET_ARN")
    return get_secret(arn) if arn else os.environ["JWT_SECRET"]
