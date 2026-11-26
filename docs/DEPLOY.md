# Desplegar ServiDesk en tu propia cuenta de AWS Academy

Guía para levantar el proyecto completo (backend, datos y frontend) desde cero en **tu** Learner Lab.
Tiempo total: unos 30–40 minutos, de los cuales ~15 son de espera mientras se crea RDS.

Al terminar tendrás en tu cuenta: 6 microservicios (API Gateway + Lambda), RDS PostgreSQL con
30 000 registros por microservicio en 3 tenants, SNS + 7 colas SQS (cada una con su DLQ), 3 buckets S3 y el frontend en Amplify.

> Los comandos están para **PowerShell** (Windows). En Mac/Linux usa la columna o el bloque marcado
> como *bash* y cambia `python` por `python3`.

---

## 0. Requisitos (una sola vez)

| Herramienta | Versión | Comprobar |
| --- | --- | --- |
| Git | cualquiera | `git --version` |
| Node.js | **22 LTS** o superior (mínimo 20.19, lo exige Vite 8) | `node --version` |
| Python | 3.11 o superior, con pip | `python --version` |

No hace falta instalar AWS CLI ni Serverless de forma global: el proyecto los trae como dependencias.
Docker solo se usa para las pruebas de integración locales (opcional).

## 1. Clonar el repositorio e instalar dependencias

```powershell
git clone https://github.com/al3xi3w/servidesk.git
cd servidesk
npm install                         # Serverless Framework v3 + compose
cd frontend; npm ci; cd ..          # React + Vite
python -m pip install --user boto3 faker
```

*bash*: `cd frontend && npm ci && cd ..` y `python3 -m pip install --user boto3 faker`.
Si en Mac pip responde `externally-managed-environment`, crea un entorno virtual:
`python3 -m venv .venv && source .venv/bin/activate && pip install boto3 faker` (y actívalo en cada terminal).

## 2. Credenciales de tu Learner Lab

1. Canvas → **Learner Lab** → **Start Lab**. Espera a que el círculo esté verde.
2. **AWS Details** → **AWS CLI: Show** → copia el bloque completo (`[default]` y sus 3 líneas,
   incluida `aws_session_token`).
3. Pégalo en el archivo de credenciales:

   ```powershell
   New-Item -ItemType Directory -Force "$env:USERPROFILE\.aws" | Out-Null
   notepad "$env:USERPROFILE\.aws\credentials"
   Set-Content "$env:USERPROFILE\.aws\config" "[default]`nregion = us-east-1" -Encoding ascii
   ```

   ⚠️ Notepad puede guardarlo como `credentials.txt`. Si pasa, renómbralo:
   `Rename-Item "$env:USERPROFILE\.aws\credentials.txt" credentials`

   *bash*: `mkdir -p ~/.aws && nano ~/.aws/credentials` y `printf "[default]\nregion = us-east-1\n" > ~/.aws/config`.

4. Comprueba:

   ```powershell
   python -c "import boto3; print(boto3.client('sts').get_caller_identity()['Arn'])"
   ```

   Debe mostrar un ARN con `voclabs`.

## 3. Secretos (no hace falta `.env`)

Los dos secretos del backend los genera CloudFormation en **AWS Secrets Manager** durante el deploy;
ninguno se escribe en archivos ni en variables de entorno de las Lambdas:

| Secreto | Contenido | Lo usan |
| --- | --- | --- |
| *DbSecret* | `username`, `password`, `host`, `port` de RDS (la contraseña maestra de RDS sale de aquí) | Lambdas de los 6 servicios y `seedLoader` (`DB_SECRET_ARN`) |
| *JwtSecret* | clave HS256 de los JWT | `login` de ms-identity (firma) y el Lambda Authorizer (valida) (`JWT_SECRET_ARN`) |

Para verlos: consola → Secrets Manager → secretos del stack `servidesk-infra-dev`.

## 4. Desplegar el backend (~15–20 min)

```powershell
npm run deploy
```

Instala la capa común (pg8000, PyJWT) para Lambda, despliega `infra` (RDS, SNS, S3, authorizer,
seedLoader; RDS tarda 10–15 min) y luego los 6 servicios en paralelo. Termina con 7 líneas `✔ … deployed`.

> **Red:** RDS es **privada**: vive en 2 subredes privadas propias (172.31.200.0/24 y 172.31.201.0/24
> dentro de la VPC por defecto, sin ruta a internet), `PubliclyAccessible: false` y el puerto 5432 solo
> acepta al security group de las Lambdas. Las Lambdas que usan la BD corren en esas mismas subredes y,
> como no hay NAT, salen a Secrets Manager y SNS por endpoints de VPC *interface* y a S3 por un endpoint
> *gateway*. Desde tu computadora ya no puedes conectarte a la BD directamente:
> usa las funciones `migrate` y `seedLoader`.

## 5. Migraciones, URLs y prueba de humo (~2 min)

```powershell
python scripts/aws_check.py all
```

Hace tres cosas:

1. **urls**: busca las 6 URLs de API Gateway y genera `frontend/.env.local`.
2. **migrate**: crea las tablas en los 3 schemas (identity primero: tenants y cuentas demo).
3. **smoke**: login en 2 tenants, CRUD en cada servicio, eventos reales por SNS → SQS
   (CI caído → incidente automático, notificación al aprobar un cambio) y aislamiento entre tenants.

Debe terminar en `RESULTADO: TODO OK`.

## 6. Cargar los datos ficticios (~1 min)

```powershell
python seed/generate.py      # genera seed/out (~25 MB, 15 s)
python seed/load.py all      # sube a S3, carga con la Lambda seedLoader (COPY) y cuenta
```

Debe terminar en `OK: 30 000 o más registros por microservicio`.
`python seed/load.py count` vuelve a mostrar la tabla de conteos (sirve como captura).

## 7. Publicar el frontend en Amplify (~1 min)

```powershell
python scripts/deploy_frontend.py
```

Compila el frontend con las URLs de tu cuenta, lo sube a Amplify (despliegue manual, sin conectar
GitHub) y muestra la URL: `https://main.<id>.amplifyapp.com`.

Opcional: `python scripts/frontend_contract.py` valida que las respuestas reales coincidan con lo que
espera el frontend (debe dar `TODO OK`).

## 8. Probar

Abre la URL de Amplify. En el login aparecen las cuentas demo (todas con la contraseña de su tenant):

| Tenant | Administrador | Agente | Cliente | Contraseña |
| --- | --- | --- | --- | --- |
| `andina` | carla.mendoza@andina.pe | lucia.paredes@andina.pe | jorge.huaman@andina.pe | `Andina#2026` |
| `pacifico` | ricardo.vega@pacifico.pe | ana.quispe@pacifico.pe | marta.salazar@pacifico.pe | `Pacifico#2026` |
| `unitec` | diego.torres@unitec.edu.pe | sofia.ramos@unitec.edu.pe | pablo.chavez@unitec.edu.pe | `Unitec#2026` |

Para la demo de eventos: entra como agente o admin a `/demo/plataforma` y usa **Simular CI caído** o
**3 incidentes en un CI**; en ~15 s aparecen el incidente / problema automático y la notificación.

---

## Al volver otro día

1. **Start Lab** y vuelve a copiar las credenciales (paso 2). Caducan cada ~4 h.
2. `python scripts/aws_check.py smoke` para comprobar que todo responde. Al empezar **reactiva las colas
   SQS → Lambda**: el Learner Lab desactiva los *event source mappings* al cerrar la sesión y, sin esto, los
   eventos quedan esperando en las colas (no se pierden). Solo reactivar: `python scripts/aws_check.py enable`.
3. Si falla la conexión a la base: consola de AWS → **RDS** → `servidesk-db-dev`. Si está *Stopped*:
   **Acciones → Iniciar** (~5 min).

No hace falta volver a desplegar. Solo si cambias código:

| Cambiaste… | Comando |
| --- | --- |
| Un servicio | `npx serverless <servicio>:deploy` (p. ej. `incidents:deploy`) |
| Todo | `npm run deploy` |
| El frontend | `python scripts/deploy_frontend.py` |

## Problemas frecuentes

| Síntoma | Solución |
| --- | --- |
| `Unable to locate credentials` | El archivo quedó como `credentials.txt` o en otra carpeta (paso 2). |
| `security token … invalid / expired` | Credenciales vencidas: vuelve a copiarlas. |
| `Can not combine '--user' and '--target'` | Ya está resuelto en `npm run layer` (usa `PIP_USER=0`); actualiza el repo. |
| `… is in ROLLBACK_COMPLETE state` | `npx serverless <servicio>:remove` y luego `npx serverless <servicio>:deploy`. |
| Un servicio falló y los demás no | `npx serverless <servicio>:deploy` solo de ese. |
| Ver el error real de un stack | Consola → CloudFormation → el stack → pestaña **Events**. |
| Ver logs de una Lambda | `npx serverless incidents:logs --function createIncident --startTime 15m` |
| La web carga muy lento | Probablemente tu red (DNS/TLS). Prueba otra red o el hotspot del celular. |
| La web abre pero el login falla (500) | RDS detenida o el lab apagado: inicia el lab y RDS (paso anterior). |
| No aparecen incidentes automáticos ni notificaciones | Colas desactivadas por el lab: `python scripts/aws_check.py enable`. |

## Borrar todo al final del curso

⚠️ No lo hagas antes de la exposición: se pierden los datos.

1. Vacía los buckets primero (CloudFormation no borra buckets con archivos y el de seed los tiene):

   ```powershell
   python -c "import boto3; [boto3.resource('s3').Bucket(b['Name']).objects.all().delete() for b in boto3.client('s3').list_buckets()['Buckets'] if b['Name'].startswith('servidesk-')]"
   ```

2. Borra los stacks (Lambdas, API Gateway, RDS y sus datos, SNS, SQS, buckets):

   ```powershell
   npm run remove
   ```

3. Borra la app **servidesk** en la consola de Amplify (no es parte de los stacks).
