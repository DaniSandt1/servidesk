"""Sube seed/out a S3 y lo carga en RDS con la Lambda seedLoader (F5).

    python seed/load.py upload   # sube seed/out/**  ->  s3://servidesk-seed-<stage>-<cuenta>/seed/
    python seed/load.py load     # invoca seedLoader por servicio y tenant (reemplaza los datos)
    python seed/load.py count    # SELECT COUNT(*) por servicio, tenant y tabla (captura para el informe)
    python seed/load.py all      # upload + load + count

Opciones: --stage dev · --region us-east-1 · --service <uno> (solo ese servicio)
"""

import argparse
import json
import sys
import time
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "seed" / "out"
ORDER = ["identity", "cmdb", "requests", "incidents", "problems", "changes"]
TENANTS = ["andina", "pacifico", "unitec"]
MAIN = {"identity": "users", "cmdb": "configuration_items", "requests": "service_requests",
        "incidents": "incidents", "problems": "problems", "changes": "changes"}


def session(region):
    s = boto3.Session(region_name=region)
    try:
        s.client("sts").get_caller_identity()
    except (NoCredentialsError, ClientError, BotoCoreError) as exc:
        sys.exit(f"Sin credenciales válidas de AWS ({exc}). Copia las del Learner Lab a ~/.aws/credentials.")
    return s


def seed_bucket(s, stage):
    outputs = s.client("cloudformation").describe_stacks(StackName=f"servidesk-infra-{stage}")["Stacks"][0]["Outputs"]
    return next(o["OutputValue"] for o in outputs if o["OutputKey"] == "SeedBucketName")


def invoke(s, stage, payload):
    client = s.client("lambda", config=Config(read_timeout=910, retries={"max_attempts": 0}))
    resp = client.invoke(FunctionName=f"servidesk-infra-{stage}-seedLoader", Payload=json.dumps(payload).encode())
    body = json.loads(resp["Payload"].read() or b"null")
    if "FunctionError" in resp:
        raise RuntimeError(f"{payload}: {body.get('errorType')}: {body.get('errorMessage')}")
    return body


def cmd_upload(s, args, services):
    if not OUT.exists():
        sys.exit("No existe seed/out: ejecuta primero  python seed/generate.py")
    bucket = seed_bucket(s, args.stage)
    s3 = s.client("s3")
    files = [f for svc in services for f in sorted((OUT / svc).rglob("*")) if f.is_file()]
    total = sum(f.stat().st_size for f in files)
    print(f"== Subiendo {len(files)} archivos ({total / 1e6:.1f} MB) a s3://{bucket}/seed/")
    for f in files:
        key = "seed/" + f.relative_to(OUT).as_posix()
        s3.upload_file(str(f), bucket, key)
    print("  OK")


def cmd_load(s, args, services):
    print("== Cargando con seedLoader (TRUNCATE + COPY por servicio y tenant)")
    for svc in services:
        for tenant in TENANTS:
            t0 = time.time()
            result = invoke(s, args.stage, {"action": "load", "service": svc, "tenant": tenant})
            rows = sum(result["loaded"].values())
            print(f"  {svc:9} {tenant:8} {rows:>7,} filas  (COPY {result['seconds']:>4} s, total {time.time() - t0:4.1f} s)")


def cmd_count(s, args, services):
    print("== Registros en RDS (SELECT COUNT(*) por schema)")
    print(f"  {'servicio':10} {'tabla principal':20} {'andina':>8} {'pacifico':>9} {'unitec':>8} {'total':>8}")
    ok = True
    details = {}
    for svc in services:
        counts = invoke(s, args.stage, {"action": "count", "service": svc})["counts"]
        details[svc] = counts
        main = [counts[t][MAIN[svc]] for t in TENANTS]
        ok &= sum(main) >= 30_000
        print(f"  {svc:10} {MAIN[svc]:20} {main[0]:>8,} {main[1]:>9,} {main[2]:>8,} {sum(main):>8,}")
    print("\n  Tablas relacionadas (suma de los 3 tenants):")
    for svc, counts in details.items():
        tables = [t for t in counts["andina"] if t != MAIN[svc]]
        print(f"  {svc:10} " + ", ".join(f"{t}={sum(counts[x][t] for x in TENANTS):,}" for t in tables))
    print("\nRESULTADO:", "OK: 30 000 o más registros por microservicio" if ok else "FALTAN REGISTROS")
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["upload", "load", "count", "all"])
    parser.add_argument("--stage", default="dev")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--service", choices=ORDER)
    args = parser.parse_args()
    services = [args.service] if args.service else ORDER

    s = session(args.region)
    if args.command in ("upload", "all"):
        cmd_upload(s, args, services)
    if args.command in ("load", "all"):
        cmd_load(s, args, services)
    if args.command in ("count", "all"):
        if not cmd_count(s, args, services):
            sys.exit(1)


if __name__ == "__main__":
    main()
