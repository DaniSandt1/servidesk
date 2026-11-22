"""Herramientas post-deploy de ServiDesk en AWS (usa las credenciales de ~/.aws/credentials).

    python scripts/aws_check.py urls      # URLs de las 6 APIs + genera frontend/.env.local
    python scripts/aws_check.py migrate   # ejecuta migrate en los 6 servicios (identity primero)
    python scripts/aws_check.py smoke     # prueba de humo con 2 tenants (HTTP real + eventos SNS/SQS)
    python scripts/aws_check.py enable    # reactiva las colas SQS -> Lambda (el Learner Lab las desactiva
                                          # al cerrar la sesión; smoke lo hace solo antes de probar)
    python scripts/aws_check.py all       # urls + migrate + smoke, en orden

Opciones: --stage dev (por defecto) · --region us-east-1 (por defecto)
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ["identity", "cmdb", "incidents", "problems", "changes", "requests"]  # identity primero
ENV_LOCAL = ROOT / "frontend" / ".env.local"

FAILS = []


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + ("" if cond else f"\n         -> {str(extra)[:400]}"))
    if not cond:
        FAILS.append(name)
    return cond


def session(args):
    s = boto3.Session(region_name=args.region)
    try:
        arn = s.client("sts").get_caller_identity()["Arn"]
    except (NoCredentialsError, ClientError, BotoCoreError) as exc:
        sys.exit(f"Sin credenciales válidas de AWS ({exc}).\n"
                 "Copia el bloque de AWS Details -> AWS CLI del Learner Lab a ~/.aws/credentials.")
    print(f"Cuenta: {arn}\n")
    return s


# ------------------------------------------------------------------ urls


def find_urls(s, stage):
    client = s.client("apigatewayv2")
    apis = {}
    for page in client.get_paginator("get_apis").paginate():
        for api in page["Items"]:
            apis[api["Name"]] = api["ApiEndpoint"]
    return {svc: apis.get(f"{stage}-servidesk-{svc}") for svc in SERVICES}


def cmd_urls(s, args):
    print("== URLs de API Gateway")
    urls = find_urls(s, args.stage)
    for svc, url in urls.items():
        check(f"{svc:10} {url or '(no desplegado)'}", bool(url))
    if all(urls.values()):
        lines = [f"VITE_API_{svc.upper()}_URL={url}" for svc, url in urls.items()]
        ENV_LOCAL.write_text("# Generado por scripts/aws_check.py urls\n" + "\n".join(lines) +
                             "\nVITE_USE_MOCKS=false\nVITE_SHOW_DEMO_ACCOUNTS=true\n", encoding="utf-8")
        print(f"\n  -> {ENV_LOCAL.relative_to(ROOT)} actualizado (no se versiona)")
    return urls


# ------------------------------------------------------------------ migrate


def cmd_migrate(s, args):
    print("== Migraciones (identity primero: crea public.tenants y las cuentas demo)")
    client = s.client("lambda", config=Config(read_timeout=320, retries={"max_attempts": 0}))
    for svc in SERVICES:
        name = f"servidesk-{svc}-{args.stage}-migrate"
        try:
            resp = client.invoke(FunctionName=name, InvocationType="RequestResponse")
            payload = json.loads(resp["Payload"].read() or b"null")
            ok = "FunctionError" not in resp and isinstance(payload, dict) and payload.get("ok")
            check(f"{svc:10} {json.dumps(payload.get('schemas') if ok else payload, ensure_ascii=False)[:150]}",
                  ok, payload)
        except ClientError as exc:
            check(f"{svc:10} invocar {name}", False, exc)


# ------------------------------------------------------------------ smoke


def http(method, url, token=None, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else None
        except ValueError:
            return e.code, raw.decode("utf-8", "replace")


def wait_for(fn, seconds=45, step=3):
    """Reintenta fn() hasta que devuelva algo verdadero (los eventos SQS son asíncronos)."""
    deadline = time.time() + seconds
    while True:
        result = fn()
        if result or time.time() > deadline:
            return result
        time.sleep(step)


def cmd_enable(s, args):
    """El Learner Lab desactiva los event source mappings (SQS -> Lambda) al terminar la sesión: los
    eventos quedan esperando en las colas. Reactiva solo los de ServiDesk."""
    print("== Colas SQS -> Lambda consumidoras (event source mappings)")
    lam = s.client("lambda")
    mappings = [m for m in lam.get_paginator("list_event_source_mappings").paginate().build_full_result()
                ["EventSourceMappings"] if f":function:servidesk-" in m["FunctionArn"]
                and f"-{args.stage}-" in m["FunctionArn"]]
    for m in mappings:
        if m["State"] in ("Disabled", "Disabling"):
            lam.update_event_source_mapping(UUID=m["UUID"], Enabled=True)
    states = {}
    for _ in range(30):
        states = {m["FunctionArn"].rsplit(":", 1)[1]: lam.get_event_source_mapping(UUID=m["UUID"])["State"]
                  for m in mappings}
        if all(st == "Enabled" for st in states.values()):
            break
        time.sleep(3)
    for fn, st in sorted(states.items()):
        check(f"{fn:50} {st}", st == "Enabled", st)
    print()


def cmd_smoke(s, args):
    cmd_enable(s, args)
    urls = find_urls(s, args.stage)
    if not all(urls.values()):
        sys.exit("Faltan APIs desplegadas; ejecuta primero el deploy.")
    U = urls
    tag = f"[smoke {time.strftime('%H:%M')}]"

    def login(tenant, email, password):
        st, b = http("POST", f"{U['identity']}/auth/login",
                     body={"tenant_code": tenant, "email": email, "password": password})
        check(f"login {tenant} {email.split('@')[0]}", st == 200, (st, b))
        return (b or {}).get("data", {}).get("access_token") if st == 200 else None

    print("== 1. Autenticación")
    agent = login("andina", "lucia.paredes@andina.pe", "Andina#2026")
    admin = login("andina", "carla.mendoza@andina.pe", "Andina#2026")
    pac = login("pacifico", "ana.quispe@pacifico.pe", "Pacifico#2026")
    st, b = http("POST", f"{U['identity']}/auth/login",
                 body={"tenant_code": "andina", "email": "lucia.paredes@andina.pe", "password": "Incorrecta#1"})
    check("contraseña incorrecta -> 401", st == 401, (st, b))
    st, _ = http("GET", f"{U['incidents']}/incidents")
    check("sin token -> 401", st == 401, st)
    st, _ = http("GET", f"{U['incidents']}/incidents", token="token.falso.x")
    check("token inválido -> 403", st == 403, st)
    if not (agent and admin and pac):
        return

    print("== 2. Lecturas por servicio")
    for svc, path in (("identity", "/auth/me"), ("identity", "/users?limit=5"), ("identity", "/teams"),
                      ("cmdb", "/ci-types"), ("cmdb", "/cis?limit=5"), ("incidents", "/incidents?limit=5"),
                      ("problems", "/problems?limit=5"), ("changes", "/changes?limit=5"),
                      ("requests", "/catalog"), ("requests", "/requests?limit=5")):
        st, b = http("GET", U[svc] + path, agent)
        total = (b or {}).get("meta", {}).get("total") if isinstance(b, dict) else None
        check(f"GET {svc}{path}" + (f"  (total={total})" if total is not None else ""), st == 200, (st, b))

    print("== 3. CMDB: CI cae -> incidente automático (CIStatusChanged por SNS -> incidents-ci-q)")
    st, b = http("POST", f"{U['cmdb']}/cis", agent, {"type_id": 3, "name": f"pos-smoke-{uuid.uuid4().hex[:6]}",
                                                       "environment": "prod", "version": "1.0.0"})
    check("POST /cis", st == 201, (st, b))
    ci_id = (b or {}).get("data", {}).get("id")
    if ci_id:
        st, b = http("PUT", f"{U['cmdb']}/cis/{ci_id}/status", agent, {"status": "down"})
        check("PUT /cis/{id}/status down", st == 200, (st, b))
        found = wait_for(lambda: (http("GET", f"{U['incidents']}/incidents?ci_id={ci_id}&channel=auto", agent)[1]
                                  or {}).get("data"))
        check("incidente automático creado por el evento (<= 45 s)", bool(found), found)

    print("== 4. Incidentes: crear -> cambiar estado -> comentar")
    st, b = http("POST", f"{U['incidents']}/incidents", agent,
                 {"title": f"{tag} No carga el sistema de ventas", "description": "Prueba de humo",
                  "impact": "medium", "urgency": "high", **({"ci_id": ci_id} if ci_id else {})})
    check("POST /incidents", st == 201, (st, b))
    inc_id = (b or {}).get("data", {}).get("id")
    if inc_id:
        st, b = http("PUT", f"{U['incidents']}/incidents/{inc_id}/status", agent, {"status": "in_progress"})
        check("PUT /incidents/{id}/status in_progress", st == 200, (st, b))
        st, b = http("POST", f"{U['incidents']}/incidents/{inc_id}/comments", agent, {"body": "Revisando"})
        check("POST /incidents/{id}/comments", st == 201, (st, b))

    print("== 5. Cambios: crear -> enviar -> aprobar (CAB, admin)")
    st, b = http("POST", f"{U['changes']}/changes", agent, {
        "title": f"{tag} Parche del POS", "type": "normal", "risk": "low", "rollback_plan": "Revertir",
        "planned_start": "2026-12-01T03:00:00Z", "planned_end": "2026-12-01T04:00:00Z"})
    check("POST /changes", st == 201, (st, b))
    ch_id = (b or {}).get("data", {}).get("id")
    if ch_id:
        st, b = http("PUT", f"{U['changes']}/changes/{ch_id}/status", agent, {"status": "submitted"})
        check("PUT /changes/{id}/status submitted", st == 200, (st, b))
        st, b = http("POST", f"{U['changes']}/changes/{ch_id}/approve", admin, {"comment": "OK"})
        check("POST /changes/{id}/approve (admin)", st == 200 and b["data"]["status"] == "approved", (st, b))
        st, b = http("POST", f"{U['changes']}/changes/{ch_id}/approve", agent, {"comment": "OK"})
        check("agente no puede aprobar -> 403", st == 403, (st, b))

    print("== 6. Notificaciones (identity-notify-q)")
    notes = wait_for(lambda: [n for n in (http("GET", f"{U['identity']}/notifications?limit=20", admin)[1] or {})
                              .get("data", []) if "espera tu aprobación" in n["title"]])
    check("admin recibió 'actualización espera tu aprobación' (<= 45 s)", bool(notes), notes)

    print("== 7. Aislamiento entre tenants (token de pacifico)")
    for svc, path in (("incidents", f"/incidents/{inc_id}"), ("cmdb", f"/cis/{ci_id}"),
                      ("changes", f"/changes/{ch_id}")):
        if path.endswith("None"):
            continue
        st, _ = http("GET", U[svc] + path, pac)
        check(f"pacifico GET {svc} de andina -> 404", st == 404, st)
    st, b = http("GET", f"{U['incidents']}/incidents?search=smoke", pac)
    check("pacifico no ve incidentes [smoke] de andina", st == 200 and b["meta"]["total"] == 0, (st, b))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["urls", "migrate", "smoke", "enable", "all"])
    parser.add_argument("--stage", default="dev")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    s = session(args)
    if args.command in ("urls", "all"):
        cmd_urls(s, args)
        print()
    if args.command in ("migrate", "all"):
        cmd_migrate(s, args)
        print()
    if args.command == "enable":
        cmd_enable(s, args)
    if args.command in ("smoke", "all"):
        cmd_smoke(s, args)

    print("\nRESULTADO:", "TODO OK" if not FAILS else f"{len(FAILS)} FALLAS")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
