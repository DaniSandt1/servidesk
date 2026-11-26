"""Logs legibles en CloudWatch: una línea por acción, con etiqueta y campos clave.

    [FALLA CREADA] 201 · POST /incidents · tenant=andina rol=agent usuario=8b3d4d78 · key=INC-010009 priority=P2 · 245 ms

Nunca se registran contraseñas, tokens ni el body completo: solo campos de una lista blanca.
"""
import functools
import json
import time

# Etiqueta por ruta (routeKey de API Gateway HTTP API)
LABELS = {
    "POST /auth/login": "LOGIN",
    "GET /auth/me": "SESIÓN",
    "GET /users": "USUARIOS · LISTA",
    "GET /users/{id}": "USUARIO · DETALLE",
    "POST /users": "USUARIO CREADO",
    "PATCH /users/{id}": "USUARIO ACTUALIZADO",
    "GET /teams": "EQUIPOS · LISTA",
    "GET /notifications": "NOTIFICACIONES · BANDEJA",
    "POST /notifications/read": "NOTIFICACIONES LEÍDAS",
    "GET /cis": "CMDB · LISTA",
    "POST /cis": "CI CREADO",
    "GET /cis/{id}": "CI · DETALLE",
    "PATCH /cis/{id}": "CI ACTUALIZADO",
    "PUT /cis/{id}/status": "CI CAMBIA DE ESTADO",
    "DELETE /cis/{id}": "CI RETIRADO",
    "GET /cis/{id}/relations": "CI · RELACIONES",
    "GET /ci-types": "CMDB · TIPOS",
    "GET /incidents": "FALLAS · LISTA",
    "POST /incidents": "FALLA CREADA",
    "GET /incidents/{id}": "FALLA · DETALLE",
    "PATCH /incidents/{id}": "FALLA ACTUALIZADA",
    "PUT /incidents/{id}/status": "FALLA CAMBIA DE ESTADO",
    "GET /incidents/{id}/comments": "FALLA · COMENTARIOS",
    "POST /incidents/{id}/comments": "COMENTARIO AGREGADO",
    "GET /problems": "PROBLEMAS · LISTA",
    "POST /problems": "PROBLEMA CREADO",
    "GET /problems/{id}": "PROBLEMA · DETALLE",
    "PATCH /problems/{id}": "PROBLEMA ACTUALIZADO",
    "PUT /problems/{id}/status": "PROBLEMA CAMBIA DE ESTADO",
    "POST /problems/{id}/known-error": "ERROR CONOCIDO PUBLICADO",
    "POST /problems/{id}/incidents": "INCIDENTES VINCULADOS AL PROBLEMA",
    "GET /changes": "CAMBIOS · LISTA",
    "POST /changes": "CAMBIO CREADO",
    "GET /changes/{id}": "CAMBIO · DETALLE",
    "PATCH /changes/{id}": "CAMBIO ACTUALIZADO",
    "PUT /changes/{id}/status": "CAMBIO CAMBIA DE ESTADO",
    "POST /changes/{id}/approve": "CAMBIO APROBADO (CAB)",
    "POST /changes/{id}/reject": "CAMBIO RECHAZADO (CAB)",
    "GET /catalog": "CATÁLOGO",
    "GET /requests": "PEDIDOS · LISTA",
    "POST /requests": "PEDIDO CREADO",
    "GET /requests/{id}": "PEDIDO · DETALLE",
    "PATCH /requests/{id}": "PEDIDO ACTUALIZADO",
    "PUT /requests/{id}/status": "PEDIDO CAMBIA DE ESTADO",
}

# Campos de la respuesta que se pueden mostrar (lista blanca)
SAFE_FIELDS = ("key", "name", "title", "status", "priority", "impact", "urgency", "channel",
               "type", "risk", "environment", "role", "email", "full_name")


def _fmt(value):
    text = str(value).replace("\n", " ")
    if len(text) > 70:
        text = text[:67] + "…"
    return f'"{text}"' if (" " in text or not text) else text


def log(tag, *parts, **fields):
    """Imprime `[TAG] parte · parte · k=v k=v`. Los campos None o vacíos se omiten."""
    chunks = [str(p) for p in parts if p not in (None, "")]
    kv = " ".join(f"{k}={_fmt(v)}" for k, v in fields.items() if v not in (None, "", [], {}))
    if kv:
        chunks.append(kv)
    print(f"[{tag}] " + " · ".join(chunks), flush=True)


def _pick(data):
    return {k: data[k] for k in SAFE_FIELDS
            if isinstance(data.get(k), (str, int, float, bool)) and data.get(k) != ""}


def _log_http(event, response, ms, fn_name):
    route = event.get("routeKey") or ""
    if not route:
        http = (event.get("requestContext") or {}).get("http") or {}
        route = f"{http.get('method', '')} {event.get('rawPath', '')}".strip() or fn_name
    tag = LABELS.get(route, route)

    ctx = ((event.get("requestContext") or {}).get("authorizer") or {}).get("lambda") or {}
    who = {"tenant": ctx.get("tenant_id"), "rol": ctx.get("role"),
           "usuario": (str(ctx.get("user_id") or "")[:8] or None)}

    status = response.get("statusCode") if isinstance(response, dict) else None
    try:
        body = json.loads(response.get("body") or "{}") if isinstance(response, dict) else {}
    except (TypeError, ValueError):
        body = {}

    info = {}
    if status is not None and status < 400:
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, dict):
            user = data.get("user") if isinstance(data.get("user"), dict) else None
            if user:  # login: quién entró (el token nunca se registra)
                tenant = user.get("tenant") if isinstance(user.get("tenant"), dict) else {}
                who["tenant"] = who["tenant"] or tenant.get("id")
                info = {"email": user.get("email"), "rol": user.get("role"),
                        "nombre": user.get("full_name"), "organizacion": tenant.get("name")}
            else:
                info = _pick(data)
        elif isinstance(data, list):
            meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
            info = {"resultados": len(data), "total": meta.get("total")}
        if route == "POST /auth/login":
            tag = "LOGIN OK"
    else:
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            info = {"error": err.get("code"), "detalle": err.get("message")}
        elif err:
            info = {"error": err}
        if route == "POST /auth/login":
            tag = "LOGIN FALLIDO"
            try:  # se registra a quién intentó entrar, nunca la contraseña
                req = json.loads(event.get("body") or "{}")
                info.update({"tenant": req.get("tenant_code"), "email": req.get("email")})
            except (TypeError, ValueError, AttributeError):
                pass

    fields = {**who, **{k: v for k, v in info.items() if v not in (None, "")}}
    log(tag, status, route, f"{ms:.0f} ms", **fields)


def http_logged(fn):
    """Decorador para handlers HTTP: registra ruta, estado, tenant, rol y campos clave."""
    @functools.wraps(fn)
    def wrapper(event, context):
        start = time.perf_counter()
        try:
            response = fn(event, context)
        except Exception as exc:
            log("ERROR", (event or {}).get("routeKey") or fn.__name__, type(exc).__name__, str(exc)[:200])
            raise
        try:
            _log_http(event or {}, response, (time.perf_counter() - start) * 1000, fn.__name__)
        except Exception:  # noqa: BLE001 - el log nunca debe romper la respuesta
            pass
        return response
    return wrapper
