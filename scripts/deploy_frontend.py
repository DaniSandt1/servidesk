"""Despliega el frontend en AWS Amplify Hosting (despliegue manual, sin conectar GitHub) (F6).

1. npm run build en frontend/ (Vite toma las URLs de frontend/.env.local; generarlas con
   `python scripts/aws_check.py urls`).
2. Empaqueta frontend/dist en un zip.
3. Crea (o reutiliza) la app "servidesk" y la rama "main" en Amplify, con la regla de
   reescritura de SPA (todas las rutas sin extensión -> /index.html).
4. Sube el zip con create_deployment + start_deployment y espera a que el job termine.

Uso: python scripts/deploy_frontend.py [--skip-build] [--app servidesk] [--branch main]
"""

import argparse
import io
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"
ENV_LOCAL = FRONTEND / ".env.local"

# Misma regla que amplify.yml: rutas de la SPA a index.html, archivos estáticos tal cual.
SPA_RULE = {
    "source": "</^[^.]+$|\\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|woff2|ttf|map|json|webp)$)([^.]+$)/>",
    "target": "/index.html",
    "status": "200",
}


def build():
    if not ENV_LOCAL.exists() or "execute-api" not in ENV_LOCAL.read_text(encoding="utf-8"):
        sys.exit("frontend/.env.local no tiene las URLs reales: ejecuta  python scripts/aws_check.py urls")
    print("== npm run build (frontend)")
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)


def zip_dist():
    if not (DIST / "index.html").exists():
        sys.exit("No existe frontend/dist/index.html")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(DIST.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(DIST).as_posix())
    return buf.getvalue()


def ensure_app(amplify, name, branch):
    app = next((a for a in amplify.list_apps(maxResults=100)["apps"] if a["name"] == name), None)
    if app is None:
        app = amplify.create_app(name=name, platform="WEB", customRules=[SPA_RULE],
                                 description="ServiDesk - portal ITSM multi-tenant (frontend React)")["app"]
        print(f"  app creada: {app['appId']}")
    else:
        amplify.update_app(appId=app["appId"], customRules=[SPA_RULE])
        print(f"  app existente: {app['appId']}")
    branches = [b["branchName"] for b in amplify.list_branches(appId=app["appId"])["branches"]]
    if branch not in branches:
        amplify.create_branch(appId=app["appId"], branchName=branch, stage="PRODUCTION")
        print(f"  rama creada: {branch}")
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--app", default="servidesk")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    if not args.skip_build:
        build()
    data = zip_dist()
    print(f"== Paquete: {len(data) / 1e6:.2f} MB")

    amplify = boto3.client("amplify", region_name=args.region)
    print("== Amplify")
    app = ensure_app(amplify, args.app, args.branch)
    app_id = app["appId"]

    deployment = amplify.create_deployment(appId=app_id, branchName=args.branch)
    req = urllib.request.Request(deployment["zipUploadUrl"], data=data, method="PUT")
    req.add_header("Content-Type", "application/zip")
    with urllib.request.urlopen(req, timeout=300) as r:
        if r.status not in (200, 204):
            sys.exit(f"Subida del zip falló: HTTP {r.status}")
    job_id = deployment["jobId"]
    amplify.start_deployment(appId=app_id, branchName=args.branch, jobId=job_id)
    print(f"  despliegue iniciado (job {job_id})")

    for _ in range(60):
        job = amplify.get_job(appId=app_id, branchName=args.branch, jobId=job_id)["job"]["summary"]
        if job["status"] in ("SUCCEED", "FAILED", "CANCELLED"):
            break
        time.sleep(5)
    url = f"https://{args.branch}.{app['defaultDomain']}"
    print(f"  estado: {job['status']}")
    if job["status"] != "SUCCEED":
        sys.exit(1)
    print(f"\nFrontend publicado: {url}")


if __name__ == "__main__":
    main()
