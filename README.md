# mIA

Asistente conversacional de Recursos Humanos de Sunset Beach Club. mIA es un
personaje: conversación natural, voz en todas las respuestas y tiempos de
respuesta mínimos.

Este repositorio sustituye por completo al sistema anterior (monolito v10.42 +
capas v11/v12 + gateway v4). Ver [docs/arquitectura.md](docs/arquitectura.md)
y [docs/migracion.md](docs/migracion.md).

## Estado

**Fase 2 · capa de datos** — lista para probar contra SharePoint real.

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Estructura, API, motor conversacional, personaje, voz, identidad preparada, base de datos, observabilidad, batería de paridad, infraestructura Azure | ✅ |
| 2 | Capa de datos: cliente SharePoint y sincronización incremental a PostgreSQL | 🧪 |
| 3 | Dominios de más uso: turnos, empleados, vacaciones | ⏳ |
| 4 | Resto de dominios, informes y correo | ⏳ |
| 5 | Modo sombra frente al sistema anterior y corte | ⏳ |
| 6 | Modelo predictivo | ⏳ |
| — | Autenticación Entra ID (MSAL) | Fase posterior; el hueco ya existe |

## Arranque local (Windows / PowerShell)

Requisitos: Python 3.12 y Docker Desktop (para PostgreSQL).

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env          # y edita los valores

docker compose up -d db         # PostgreSQL local
alembic upgrade head            # crea el esquema
python -m mia                   # API en http://127.0.0.1:5001 (y 5002 si MIA_COMPAT_PORT=5002)
```

Sin clave de LLM funciona con `MIA_LLM__PROVIDER=fake` (respuestas de prueba).
La documentación interactiva de la API está en `http://127.0.0.1:5001/docs`.

### Frontend actual

No se ha modificado. Para usarlo con el backend nuevo:

- `MIA_COMPAT_PORT=5002` hace que el mismo proceso atienda también el puerto
  donde el frontend espera el gateway, así que Vite y sus proxies siguen igual.
- Opcionalmente, `MIA_FRONTEND__LEGACY_HTML` y `MIA_FRONTEND__ASSETS_DIR` sirven
  `mia.html` y `/mia-assets` desde la carpeta del proyecto anterior, sin copiarlos.

## Calidad

```powershell
ruff check src tests tools migrations    # estilo y errores
ruff format src tests tools migrations   # formato
mypy                                     # tipos (modo estricto)
pytest --cov=mia                         # tests
```

La integración continua (`.github/workflows/ci.yml`) ejecuta lo mismo en cada cambio.

## Batería de paridad

```powershell
python tools/extract_parity_corpus.py C:\ruta\proyecto-anterior\mia_runtime.sqlite3
```

Genera en `tests/parity/corpus/` las conversaciones reales del sistema anterior.
**Contiene datos personales**: está excluido de git y no debe salir del equipo.

## Sincronización con SharePoint

```powershell
python -m mia.sync --check       # probar el acceso a cada lista (no escribe nada)
python -m mia.sync --list        # fuentes y estado
python -m mia.sync --full        # primera carga completa
python -m mia.sync               # incremental (o completa si toca)
python -m mia.sync --loop 300    # en local, repetir cada 5 minutos
```

Fuentes: empleados, departamentos, turnos, vacaciones y saldo de vacaciones del
año en curso. La incremental usa el registro de cambios de SharePoint (altas,
modificaciones y borrados) y solo descarga lo que ha cambiado; una vez al día se
hace una completa. En Azure la ejecuta un Container Apps Job cada 10 minutos.

Los DNI/NIE nunca se guardan: se sustituyen por un seudónimo HMAC al leerlos.

## Evaluación conversacional

```powershell
python tools/eval_conversation.py
```

Con mIA arrancada y el LLM real, comprueba casos de comportamiento del personaje
(no afirmar capacidades que no tiene, no inventar datos, longitud de la voz…).
Cada fallo real que detectemos se añade como caso.

## Despliegue en Azure

```powershell
az group create -n rg-mia-dev -l spaincentral
$env:MIA_PG_ADMIN_PASSWORD="..."; $env:MIA_LLM_API_KEY="..."
az deployment group create -g rg-mia-dev -f infra/main.bicep -p infra/main.dev.bicepparam
```

Crea: Container Apps, PostgreSQL Flexible Server, Key Vault (todos los secretos),
identidad administrada, Container Registry, Blob Storage, Log Analytics y
Application Insights. Producción exige Easy Auth (`easyAuthClientId`); sin él la
aplicación se niega a arrancar.

## Estructura

```
src/mia/
  api/            rutas HTTP, streaming SSE y alias de compatibilidad
  auth/           identidad del usuario y permisos por rol
  conversation/   motor, personaje, herramientas y voz incremental
  domains/        dominios funcionales (un paquete por dominio)
  data/           modelo operativo, repositorios y conexión
  llm/            proveedores LLM (OpenAI, Azure OpenAI, falso para tests)
  voice/          proveedores de voz (ElevenLabs) y caché de frases
  rules/          catálogo de reglas de negocio
  observability/  logs estructurados, correlación y telemetría
migrations/       migraciones de esquema (Alembic)
infra/            infraestructura como código (Bicep)
tools/            utilidades (batería de paridad)
tests/
```

Convenciones: código e identificadores en inglés; textos al usuario, reglas,
herramientas del LLM y documentación en castellano. Ningún fichero ni símbolo
lleva sufijo de versión: la versión es la del paquete y la historia la guarda git.
