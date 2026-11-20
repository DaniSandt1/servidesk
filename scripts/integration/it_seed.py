"""Prueba local del seed: migra los 6 servicios, carga seed/out con la misma función que la Lambda
seedLoader (COPY por SSL) y verifica conteos y que la API lea los datos generados.

Uso: python seed/generate.py && python scripts/integration/it_seed.py
Requiere el contenedor de scripts/integration/README.md (IT_PG_PORT, 55432 por defecto).
"""
import gzip
import importlib
import json
import os
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PORT = int(os.environ.get("IT_PG_PORT", "55432"))
OUT = REPO / "seed" / "out"
sys.path.insert(0, str(REPO / "infra" / "layers" / "common" / "python"))
os.environ.update({"DB_HOST": "localhost", "DB_USER": "servidesk_admin", "DB_PASSWORD": "localpass123",
                   "JWT_SECRET": "seed-secret-0123456789-abcdefghijklmnop"})

import pg8000.native  # noqa: E402

_Orig = pg8000.native.Connection


class _Conn(_Orig):
    def __init__(self, *a, **kw):
        kw["port"] = PORT
        super().__init__(*a, **kw)


pg8000.native.Connection = _Conn
events = types.ModuleType("common.events")
events.publish = lambda **kw: None
sys.modules["common.events"] = events
import common  # noqa: E402,F401

SERVICES = ["identity", "cmdb", "requests", "incidents", "problems", "changes"]
MODULES = {}


def load_service(name, module_names):
    for key in [k for k in sys.modules if k == "handlers" or k.startswith("handlers.") or k == "common.db"]:
        del sys.modules[key]
    sys.path.insert(0, str(REPO / "services" / name))
    try:
        MODULES[name] = {m: importlib.import_module(f"handlers.{m}") for m in module_names}
    finally:
        sys.path.pop(0)


def call(service, fn, *args):
    os.environ["DB_NAME"] = f"db_{service}"
    return fn(*args)


load_service("identity", ["login", "users", "migrate"])
load_service("cmdb", ["cis", "migrate"])
load_service("requests", ["requests", "migrate"])
load_service("incidents", ["incidents", "migrate"])
load_service("problems", ["problems", "migrate"])
load_service("changes", ["changes", "migrate"])

spec = importlib.util.spec_from_file_location("seed_loader", REPO / "infra" / "seed_loader" / "handler.py")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)
authz_spec = importlib.util.spec_from_file_location("authz", REPO / "infra" / "authorizer" / "handler.py")
authz = importlib.util.module_from_spec(authz_spec)
authz_spec.loader.exec_module(authz)

FAILS = []


def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FAIL ") + name + ("" if cond else f"  -> {str(extra)[:300]}"))
    if not cond:
        FAILS.append(name)


class Ctx:
    aws_request_id = "seed"


def res(r):
    return r["statusCode"], (json.loads(r["body"]) if r.get("body") else None)


admin = _Orig(user="servidesk_admin", password="localpass123", host="localhost", port=PORT, database="postgres")
for svc in SERVICES:
    admin.run(f"DROP DATABASE IF EXISTS db_{svc} WITH (FORCE)")
admin.close()

print("== Migraciones")
for svc in SERVICES:
    call(svc, MODULES[svc]["migrate"].handle, {}, None)
check("6 servicios migrados", True)

print("== Carga con seedLoader.load_tenant (COPY por SSL)")
for svc in SERVICES:
    conn = loader.connect(svc, port=PORT, host="localhost")
    for tenant in loader.TENANTS:
        folder = OUT / svc / tenant
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        result = loader.load_tenant(conn, svc, tenant, manifest, lambda f, d=folder: gzip.open(d / f, "rb"))
        expected = {t["table"]: t["rows"] for t in manifest["tables"]}
        check(f"{svc:9} {tenant:8} {sum(result['loaded'].values()):>7,} filas en {result['seconds']} s",
              result["loaded"] == expected, (result, expected))
    conn.close()

print("== Recarga (idempotente)")
conn = loader.connect("incidents", port=PORT, host="localhost")
folder = OUT / "incidents" / "andina"
manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
loader.load_tenant(conn, "incidents", "andina", manifest, lambda f: gzip.open(folder / f, "rb"))
counts = loader.count(conn, "incidents")
check("recargar no duplica", counts["andina"]["incidents"] == 10_000, counts)
check("sla_policy_id resuelto por prioridad",
      conn.run("SELECT COUNT(*) FROM tenant_andina.incidents WHERE sla_policy_id IS NULL")[0][0] == 0)
conn.close()

print("== Conteos (tabla principal = 10 000 por tenant)")
MAIN = {"identity": "users", "cmdb": "configuration_items", "requests": "service_requests",
        "incidents": "incidents", "problems": "problems", "changes": "changes"}
for svc in SERVICES:
    conn = loader.connect(svc, port=PORT, host="localhost")
    counts = loader.count(conn, svc)
    conn.close()
    main = [counts[t][MAIN[svc]] for t in loader.TENANTS]
    check(f"{svc:9} {MAIN[svc]:20} {main} = {sum(main):,}", all(m == 10_000 for m in main), counts)

print("== La API lee los datos generados")
s, b = res(call("identity", MODULES["identity"]["login"].login, {"body": json.dumps(
    {"tenant_code": "andina", "email": "lucia.paredes@andina.pe", "password": "Andina#2026"})}, Ctx()))
check("login cuenta demo", s == 200, b)
token = b["data"]["access_token"]
ctx = authz.handle({"headers": {"authorization": f"Bearer {token}"}}, None)["context"]


def ev(query=None, path=None):
    return {"requestContext": {"authorizer": {"lambda": ctx}}, "body": None, "queryStringParameters": query,
            "pathParameters": path}


s, b = res(call("identity", MODULES["identity"]["users"].listUsers, ev({"role": "customer", "limit": "1"}), Ctx()))
check("GET /users customers", s == 200 and b["meta"]["total"] > 8000, b)
bulk_email = None
if s == 200:
    bulk_email = b["data"][0]["email"]
    s2, b2 = res(call("identity", MODULES["identity"]["login"].login, {"body": json.dumps(
        {"tenant_code": "andina", "email": bulk_email, "password": "Andina#2026"})}, Ctx()))
    check(f"login usuario generado ({bulk_email})", s2 == 200, b2)

s, b = res(call("incidents", MODULES["incidents"]["incidents"].listIncidents,
                ev({"status": "new,in_progress", "sort_by": "priority", "limit": "5"}), Ctx()))
check("GET /incidents abiertos", s == 200 and b["meta"]["total"] > 0, b)
s, b = res(call("incidents", MODULES["incidents"]["incidents"].listIncidents, ev({"sla_breached": "true"}), Ctx()))
check("GET /incidents?sla_breached=true", s == 200, b)

conn = loader.connect("problems", port=PORT, host="localhost")
pid = str(conn.run("SELECT p.id FROM tenant_andina.problems p JOIN tenant_andina.problem_incidents pi "
                   "ON pi.problem_id = p.id JOIN tenant_andina.known_errors k ON k.problem_id = p.id LIMIT 1")[0][0])
conn.close()
s, b = res(call("problems", MODULES["problems"]["problems"].getProblem, ev(path={"id": pid}), Ctx()))
check("GET /problems/{id} con incidentes y error conocido",
      s == 200 and b["data"]["incident_ids"] and b["data"]["known_error"], b)

s, b = res(call("cmdb", MODULES["cmdb"]["cis"].listCis, ev({"status": "down", "environment": "prod"}), Ctx()))
check("GET /cis down prod", s == 200 and b["meta"]["total"] > 0, b)
ci = b["data"][0]["id"] if s == 200 and b["data"] else None
s, b = res(call("cmdb", MODULES["cmdb"]["cis"].getCi, ev(path={"id": ci}), Ctx()))
check("GET /cis/{id} con attributes", s == 200 and isinstance(b["data"]["attributes"], dict), b)

s, b = res(call("changes", MODULES["changes"]["changes"].listChanges,
                ev({"planned_from": "2026-11-01T00:00:00Z", "planned_to": "2026-12-31T00:00:00Z"}), Ctx()))
check("GET /changes calendario", s == 200 and b["meta"]["total"] > 0, b)
cid = b["data"][0]["id"] if s == 200 and b["data"] else None
s, b = res(call("changes", MODULES["changes"]["changes"].getChange, ev(path={"id": cid}), Ctx()))
check("GET /changes/{id} con CIs", s == 200 and b["data"]["cis"], b)

s, b = res(call("requests", MODULES["requests"]["requests"].listCatalog, ev(), Ctx()))
check("GET /catalog 12 ítems", s == 200 and len(b["data"]) == 12, b)
s, b = res(call("requests", MODULES["requests"]["requests"].listRequests, ev({"status": "pending_approval"}), Ctx()))
check("GET /requests pendientes", s == 200 and b["meta"]["total"] > 0, b)
rid = b["data"][0]["id"] if s == 200 and b["data"] else None
s, b = res(call("requests", MODULES["requests"]["requests"].getRequest, ev(path={"id": rid}), Ctx()))
check("GET /requests/{id}", s == 200, b)

print("\nRESULTADO:", "TODO OK" if not FAILS else f"{len(FAILS)} FALLAS: {FAILS}")
sys.exit(1 if FAILS else 0)
