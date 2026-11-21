"""Verifica que las APIs desplegadas respondan lo que espera el frontend (F6).

Hace las mismas llamadas que las páginas de frontend/src/pages (con los parámetros serializados como
serializeParams: arrays unidos por comas) y compara cada respuesta con las interfaces de
frontend/src/types/api.ts: campos obligatorios presentes y null solo donde el tipo lo admite.

Uso: python scripts/frontend_contract.py      (lee las URLs de frontend/.env.local)
"""

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPES = (ROOT / "frontend" / "src" / "types" / "api.ts").read_text(encoding="utf-8")
ENV = dict(line.split("=", 1) for line in (ROOT / "frontend" / ".env.local").read_text(encoding="utf-8").splitlines()
           if "=" in line and not line.startswith("#"))
URL = {svc: ENV[f"VITE_API_{svc.upper()}_URL"] for svc in
       ("identity", "cmdb", "incidents", "problems", "changes", "requests")}

FAILS, WARNS = [], []


# ------------------------------------------------------------------ interfaces TypeScript


def parse_interfaces(src):
    out = {}
    for m in re.finditer(r"export interface (\w+)(?:<[^>]*>)?(?: extends ([\w, <>]+))?\s*\{(.*?)\n\}", src, re.S):
        name, parents, body = m.group(1), m.group(2), m.group(3)
        fields = {}
        for fm in re.finditer(r"^\s*(\w+)(\?)?:\s*([^;]+);", body, re.M):
            fields[fm.group(1)] = {"optional": bool(fm.group(2)), "nullable": "null" in fm.group(3)}
        out[name] = {"fields": fields, "parents": [p.strip() for p in (parents or "").split(",") if p.strip()]}
    return out


IFACES = parse_interfaces(TYPES)


def fields_of(name):
    iface = IFACES[name]
    merged = {}
    for parent in iface["parents"]:
        if parent in IFACES:
            merged.update(fields_of(parent))
    merged.update(iface["fields"])
    return merged


def validate(obj, iface, where):
    if not isinstance(obj, dict):
        FAILS.append(f"{where}: se esperaba objeto {iface}, llegó {type(obj).__name__}")
        return False
    ok = True
    for field, spec in fields_of(iface).items():
        if field not in obj:
            if not spec["optional"]:
                FAILS.append(f"{where}: falta {iface}.{field}")
                ok = False
        elif obj[field] is None and not spec["nullable"] and not spec["optional"]:
            WARNS.append(f"{where}: {iface}.{field} es null pero el tipo no admite null")
    return ok


# ------------------------------------------------------------------ HTTP


def qs(params):
    out = {}
    for k, v in (params or {}).items():
        if v in (None, "") or v == []:
            continue
        out[k] = ",".join(v) if isinstance(v, list) else ("true" if v is True else "false" if v is False else str(v))
    return ("?" + urllib.parse.urlencode(out)) if out else ""


def http(method, svc, path, token=None, params=None, body=None):
    req = urllib.request.Request(URL[svc] + path + qs(params), method=method,
                                 data=None if body is None else json.dumps(body).encode("utf-8"))
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else None)


def expect(label, method, svc, path, token, iface, kind="single", params=None, body=None, status=200):
    st, b = http(method, svc, path, token, params, body)
    where = f"{method} {svc}{path}{qs(params)}"
    if st != status:
        FAILS.append(f"{where}: HTTP {st} (esperado {status}) {json.dumps(b, ensure_ascii=False)[:250]}")
        print(f"  FAIL {label}")
        return None
    ok = True
    if kind == "paginated":
        ok = isinstance(b, dict) and isinstance(b.get("data"), list) and validate(b.get("meta"), "PaginationMeta", where)
        for row in (b.get("data") or [])[:5]:
            ok &= validate(row, iface, where)
        data = b.get("data")
    elif kind == "list":
        data = b.get("data") if isinstance(b, dict) else None
        ok = isinstance(data, list)
        for row in (data or [])[:5]:
            ok &= validate(row, iface, where)
    elif kind == "none":
        data = None
    else:
        data = b.get("data") if isinstance(b, dict) else None
        ok = validate(data, iface, where)
    print(f"  {'OK  ' if ok else 'FAIL'} {label}")
    return data


def login(tenant, email, password):
    st, b = http("POST", "identity", "/auth/login", body={"tenant_code": tenant, "email": email, "password": password})
    if st != 200:
        sys.exit(f"login {email}: {st} {b}")
    validate(b["data"], "LoginResponse", "login")
    validate(b["data"]["user"], "AuthUser", "login.user")
    return b["data"]["access_token"]


def main():
    print("== Sesión")
    admin = login("andina", "carla.mendoza@andina.pe", "Andina#2026")
    agent = login("andina", "lucia.paredes@andina.pe", "Andina#2026")
    customer = login("andina", "jorge.huaman@andina.pe", "Andina#2026")
    expect("authService.me", "GET", "identity", "/auth/me", agent, "AuthUser")
    OPEN = ["new", "in_progress", "on_hold"]

    print("== Dashboard")
    for params in ({"sort_by": "created_at", "limit": 5}, {"status": OPEN, "assignee_id": "me", "limit": 1},
                   {"status": OPEN, "priority": "P1", "limit": 1}, {"status": OPEN, "sla_breached": True, "limit": 1},
                   {"status": ["resolved", "closed"], "sla_breached": True, "limit": 1}):
        expect(f"incidentService.list {params}", "GET", "incidents", "/incidents", agent, "Incident", "paginated", params)
    expect("problemService.list investigating,known_error", "GET", "problems", "/problems", agent, "Problem",
           "paginated", {"status": ["investigating", "known_error"], "limit": 1})
    expect("changeService.list submitted", "GET", "changes", "/changes", agent, "Change", "paginated",
           {"status": "submitted", "limit": 1})
    expect("cmdbService.list down", "GET", "cmdb", "/cis", agent, "ConfigurationItem", "paginated",
           {"status": "down", "limit": 1})
    expect("requestService.list pending_approval", "GET", "requests", "/requests", admin, "ServiceRequest",
           "paginated", {"status": "pending_approval", "limit": 1})

    print("== Incidentes")
    rows = expect("IncidentList (por vencer)", "GET", "incidents", "/incidents", agent, "Incident", "paginated",
                  {"page": 1, "limit": 20, "status": OPEN, "sla_breached": False, "sort_by": "sla_due_at",
                   "sort_order": "asc"})
    expect("IncidentList (sin asignar + búsqueda)", "GET", "incidents", "/incidents", agent, "Incident", "paginated",
           {"page": 1, "limit": 20, "search": "acceso", "assignee_id": "none", "sort_by": "priority",
            "sort_order": "asc"})
    expect("IncidentList (cliente: solo los suyos)", "GET", "incidents", "/incidents", customer, "Incident",
           "paginated", {"limit": 20})
    inc = rows[0] if rows else None
    if inc:
        expect("incidentService.get", "GET", "incidents", f"/incidents/{inc['id']}", agent, "Incident")
        expect("incidentService.listComments", "GET", "incidents", f"/incidents/{inc['id']}/comments", agent,
               "IncidentComment", "paginated", {"limit": 100})

    print("== Problemas")
    rows = expect("ProblemList (mis problemas)", "GET", "problems", "/problems", agent, "Problem", "paginated",
                  {"page": 1, "limit": 20, "owner_id": "me", "sort_by": "priority", "sort_order": "asc"})
    rows = expect("ProblemList (known_error)", "GET", "problems", "/problems", agent, "Problem", "paginated",
                  {"status": "known_error", "limit": 5})
    if rows:
        p = expect("problemService.get", "GET", "problems", f"/problems/{rows[0]['id']}", agent, "ProblemDetail")
        if p and p.get("known_error"):
            validate(p["known_error"], "KnownError", "ProblemDetail.known_error")
        expect("ProblemDetail -> incidentes vinculados", "GET", "incidents", "/incidents", agent, "Incident",
               "paginated", {"problem_id": rows[0]["id"], "limit": 50, "sort_by": "created_at"})
        if p and p.get("ci_id"):
            expect("Platform: problemas abiertos del CI", "GET", "problems", "/problems", agent, "Problem", "paginated",
                   {"ci_id": p["ci_id"], "status": ["new", "investigating", "known_error"], "limit": 1})

    print("== Cambios")
    expect("ChangeList (mis cambios)", "GET", "changes", "/changes", agent, "Change", "paginated",
           {"page": 1, "limit": 20, "status": ["approved", "scheduled"], "type": "normal", "risk": ["low", "medium"],
            "requester_id": "me", "sort_by": "planned_start", "sort_order": "desc"})
    rows = expect("changeService.calendar", "GET", "changes", "/changes", agent, "Change", "paginated",
                  {"planned_from": "2026-11-01T00:00:00.000Z", "planned_to": "2026-12-31T23:59:59.000Z",
                   "status": ["approved", "scheduled", "implemented"], "sort_by": "planned_start",
                   "sort_order": "asc", "limit": 100})
    if rows:
        c = expect("changeService.get", "GET", "changes", f"/changes/{rows[0]['id']}", agent, "ChangeDetail")
        for ci in (c or {}).get("cis", [])[:2]:
            validate(ci, "ChangeCI", "ChangeDetail.cis")
        for ap in (c or {}).get("approvals", [])[:2]:
            validate(ap, "ChangeApproval", "ChangeDetail.approvals")

    print("== CMDB")
    expect("cmdbService.types", "GET", "cmdb", "/ci-types", agent, "CIType", "list")
    rows = expect("CiList", "GET", "cmdb", "/cis", agent, "ConfigurationItem", "paginated",
                  {"page": 1, "limit": 20, "search": "srv", "status": ["operational", "degraded"],
                   "environment": "prod", "type_id": 1, "sort_by": "name", "sort_order": "asc"})
    if rows:
        expect("cmdbService.get", "GET", "cmdb", f"/cis/{rows[0]['id']}", agent, "ConfigurationItem")
        expect("cmdbService.relations", "GET", "cmdb", f"/cis/{rows[0]['id']}/relations", agent, "CIRelationView",
               "list")
        expect("CiDetail -> incidentes del CI", "GET", "incidents", "/incidents", agent, "Incident", "paginated",
               {"ci_id": rows[0]["id"], "limit": 8, "sort_by": "created_at"})

    print("== Catálogo y solicitudes")
    expect("requestService.catalog (cliente)", "GET", "requests", "/catalog", customer, "CatalogItem", "list")
    rows = expect("RequestList", "GET", "requests", "/requests", agent, "ServiceRequest", "paginated",
                  {"page": 1, "limit": 20, "search": "REQ-00", "status": ["submitted", "in_fulfillment"],
                   "assignee_id": "me", "sort_by": "created_at", "sort_order": "desc"})
    rows = expect("RequestList (cliente)", "GET", "requests", "/requests", customer, "ServiceRequest", "paginated",
                  {"limit": 20})
    if rows:
        r = expect("requestService.get", "GET", "requests", f"/requests/{rows[0]['id']}", customer,
                   "ServiceRequestDetail")
        for ap in (r or {}).get("approvals", [])[:2]:
            validate(ap, "RequestApproval", "ServiceRequestDetail.approvals")

    print("== Usuarios y notificaciones")
    expect("Users (admin)", "GET", "identity", "/users", admin, "User", "paginated",
           {"page": 1, "limit": 20, "search": "mendoza", "role": ["admin", "agent"], "sort_by": "full_name",
            "sort_order": "asc"})
    expect("userService.listTeams", "GET", "identity", "/teams", agent, "Team", "paginated", {"limit": 100})
    st, b = http("GET", "identity", "/notifications", admin, {"limit": 20})
    ok = st == 200 and isinstance(b.get("data"), list) and isinstance(b.get("meta", {}).get("unread"), int)
    for n in (b or {}).get("data", [])[:5]:
        ok &= validate(n, "Notification", "GET /notifications")
    print(f"  {'OK  ' if ok else 'FAIL'} notificationService.list")
    if not ok:
        FAILS.append(f"GET /notifications: {st} {str(b)[:200]}")
    expect("notificationService.markRead", "POST", "identity", "/notifications/read", admin, None, "none",
           body={}, status=204)

    print("\nAvisos:" if WARNS else "", *sorted(set(WARNS))[:20], sep="\n  ")
    print("\nRESULTADO:", "TODO OK" if not FAILS else f"{len(FAILS)} FALLAS")
    for f in FAILS:
        print("  -", f)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
