# Catálogo de integraciones — mIA

Documento para que IT revise y apruebe las conexiones externas de mIA, con permisos solicitados, datos que viajan y protección aplicada. Fuente: `docs/auditoria_arquitectura_mia.md` y las auditorías detalladas en `docs/auditoria_detalle/`. Toda afirmación tiene respaldo en el código (citas fichero:línea en las auditorías de detalle); lo no verificable desde el repositorio se marca explícitamente como pendiente de confirmar en el tenant.

Leyenda: ✅ Implementado · 🔵 Planificado · ❌ No existe.

---

## 1. Mapa de integraciones

```
                    ┌─────────────────────────────────────────────────┐
                    │        TENANT / SUSCRIPCIÓN DEL CLIENTE           │
                    │                                                    │
   Usuario ──HTTPS──▶  Frontend (Vite) ──HTTPS──▶  API mIA (Container App) │
  (navegador)        │                                    │              │
                    │                                    │ Key Vault    │
                    │                          Managed Identity │        │
                    │                                    │              │
                    │   PostgreSQL Flexible Server ◀──────┤              │
                    │   (interno, TLS)                    │              │
                    └────────────────────────────────────┼──────────────┘
                                                            │
                     ────────────────────────────────────────────────────
                                FRONTERA DE LA ORGANIZACIÓN
                     ────────────────────────────────────────────────────
                                                            │
        ┌──────────────────┬──────────────┬────────────────┼───────────────┐
        ▼                   ▼              ▼                ▼               ▼
  login.microsoft-   graph.microsoft   *.sharepoint      api.openai.com /  api.elevenlabs.io
  online.com (Entra)  .com (Correo)     .com (RRHH)       azure OpenAI      (Voz)
  Dato: identidad/    Dato: correo      Dato: empleados,  Dato: prompt      Dato: texto de
  token (sin PII      RRHH (personal)  turnos, nóminas    conversación,     respuesta (tras
  de negocio)                          (personal,         documentos       Presidio,
                                        especialmente                      importes
                                        sensible)                          filtrados)
```

Código de sensibilidad del dato por flujo: **personal** (nóminas, documentos, empleados) · **identidad** (tokens, sin contenido de negocio) · **conversación** (texto generado por el usuario/LLM, ya pasado por Presidio si el gateway está activo).

Todos los servicios de la derecha son de **terceros fuera del tenant** (Microsoft 365/Entra ID es del propio cliente, por eso aparece dentro de la frontera organizativa junto con Azure).

---

## 2. Fichas por integración

### 2.1 SharePoint Online (RRHH) — ✅ Implementado

| | |
|---|---|
| **Propósito** | Fuente de datos de RRHH: empleados, turnos, vacaciones, nóminas (metadatos), documentos firmados, CVs, trabajo temporal. |
| **Protocolo** | HTTPS/REST (SharePoint REST clásico, `_api/web/...`), puerto 443. |
| **Autenticación** | Certificado de aplicación vía MSAL (OAuth2 client-credentials), **no** API key ni secreto de cliente. |
| **Permisos solicitados** | Scope `.default` — reclama todos los permisos de aplicación concedidos en el registro de Entra ID. **El repositorio no declara ni fija cuáles son exactamente** (`Sites.Selected` vs. `Sites.Read.All`/`ReadWrite.All`). |
| **Permiso mínimo recomendado** | `Sites.Selected`, acotado al sitio de RRHH y al portal corporativo — **pendiente de confirmar en el tenant**. |
| **Datos que viajan** | Empleados (incluye DNI/NIE), turnos, vacaciones, nóminas (metadatos + contenido bajo permiso), documentos firmados, CVs, trabajo temporal. |
| **Protección previa** | DNI/NIE y rutas de biblioteca con identidad se seudonimizan (HMAC) **antes** de persistir en PostgreSQL. |
| **Cifrado en tránsito** | TLS validado (sin `verify=False` en ningún cliente HTTP del repositorio). |
| **Registro** | `structlog` con redacción automática de claves sensibles; se registra `item_id` y mensajes de error truncados, no PII en claro. |
| **Comportamiento ante fallo** | Reintentos con backoff exponencial + jitter, respeto de `Retry-After`; fallo de una fuente no detiene la sincronización de las demás; sin circuit breaker (aceptable para un job en background). |
| **Credencial — dónde vive** | Certificado PFX en Key Vault (Azure), inyectado vía Managed Identity. |

### 2.2 Microsoft Graph — Correo (buzón RRHH) — ✅ Implementado

| | |
|---|---|
| **Propósito** | Leer, buscar y (si está habilitado) enviar correo desde el buzón compartido de RRHH. |
| **Protocolo** | HTTPS/REST, Microsoft Graph v1.0. |
| **Autenticación** | **Mismo certificado de aplicación que SharePoint** (ver hallazgo de credencial compartida más abajo). |
| **Permisos solicitados** | `Mail.Read`/`Mail.ReadWrite`/`Mail.Send` de aplicación (vía `.default`, no declarado exacto en código). |
| **⚠️ Hallazgo crítico (pendiente de verificar en el tenant)** | El propio repositorio (`docs/arquitectura.md`) reconoce que el permiso de aplicación de Graph para correo da acceso a **todos los buzones del tenant** salvo que exista una **Application Access Policy de Exchange Online** que lo acote al buzón compartido de RRHH. No hay evidencia en el repositorio de que esa política ya exista (no está en la infraestructura como código, no hay script de Exchange Online). **Acción requerida de IT**: confirmar en Exchange Online si esa política está creada; si no, crearla antes de producción. |
| **Datos que viajan** | Correo del buzón de RRHH (contenido potencialmente personal: candidaturas, consultas de empleados). |
| **Envío real** | Desactivado por defecto (`MIA_MAIL__SEND_ENABLED=false`); si se activa, exige además confirmación humana explícita en la conversación (ver `docs/mIA_guia_instalacion_operacion.md`). |
| **Comportamiento ante fallo** | Cada herramienta captura el error de Graph y devuelve un mensaje de negocio al usuario, nunca una excepción sin control. |
| **Credencial — dónde vive** | Compartida con SharePoint (mismo certificado en Key Vault). |

### 2.3 Microsoft Entra ID — validación de identidad — ✅ Implementado

| | |
|---|---|
| **Propósito** | Login de usuarios (frontend, vía MSAL) y validación de tokens de acceso (backend). |
| **Protocolo** | HTTPS — `login.microsoftonline.com` (OAuth2/OIDC) y JWKS del tenant para validar firma. |
| **Autenticación** | App registration de mIA en Entra ID; el backend valida firma RS256, audiencia, issuer, expiración de cada token recibido. |
| **Permisos** | Ninguno de Graph aquí — es solo autenticación de usuario (login), no acceso a datos. mIA lee el claim `roles` (App Roles asignados explícitamente), nunca `groups`. |
| **Datos que viajan** | Identidad del usuario (nombre, email, oid, roles asignados) — sin datos de negocio. |
| **Comportamiento ante fallo** | Sin reintento ante fallo de red al refrescar JWKS (mitigado por caché de 24h); login falla de forma controlada, no silenciosa. |
| **Nota de despliegue** | El modo de validación JWT propia (`entra`) está implementado y probado, pero no conectado hoy en la infraestructura Azure; la vía de producción configurada actualmente es Easy Auth (gestionado por la plataforma). |

### 2.4 LLM — OpenAI / Azure OpenAI — ✅ Implementado

| | |
|---|---|
| **Propósito** | Motor conversacional: generación de respuestas, razonamiento con herramientas, búsqueda web. |
| **Protocolo** | HTTPS a `api.openai.com` o al recurso Azure OpenAI configurado (`MIA_LLM__PROVIDER`/`MIA_LLM__BASE_URL`). |
| **Autenticación** | API key (`Authorization: Bearer` u `api-key` en modo Azure), clave en Key Vault. |
| **Datos que viajan** | Instrucciones del sistema, historial de conversación (8 turnos), resultados de herramientas (correos, documentos, datos de RRHH) — **pasados por el Privacy Gateway antes de salir, si está activo** (ver más abajo). |
| **Protección previa** | Privacy Gateway: tokenización de PII reversible, envoltura de "dato no confiable" para resultados de herramientas. **Solo si `MIA_PRIVACY_GATEWAY__ENABLED=true`** — obligatorio por validador en producción, no garantizado en otros entornos mal etiquetados. |
| **Retención / no entrenamiento** | Depende de las condiciones contractuales con el proveedor (DPA) — **pendiente de confirmar por IT/legal**, no verificable desde el código. |
| **Comportamiento ante fallo** | Reintentos con backoff en 429/5xx, tope 3 intentos; fallo se traduce en respuesta de negocio genérica, nunca un stack trace al usuario. |
| **Límites** | 1200 tokens de salida por defecto, 120s de presupuesto por turno, 8 rondas de herramientas máximo. **Sin límite de coste ni de tasa por usuario** (hallazgo). |

### 2.5 Voz — ElevenLabs — ✅ Implementado

| | |
|---|---|
| **Propósito** | Síntesis de voz de las respuestas del asistente. |
| **Protocolo** | HTTPS a `api.elevenlabs.io`, streaming de audio. |
| **Autenticación** | API key en cabecera `xi-api-key`, clave en Key Vault. |
| **Datos que viajan** | Texto de la respuesta del asistente — **con los tokens de Presidio ya restaurados a su valor real** (Presidio protege el tránsito hacia el LLM, no hacia la voz). Filtro específico: nunca se envían importes monetarios (regla nacida de un incidente real). **No se filtra PII general** (nombres, DNI, email, datos médicos) antes de enviarse a este proveedor externo. |
| **Retención** | Caché local solo de frases cortas repetidas (saludos); respuestas largas/variables con datos reales no se cachean. |
| **Comportamiento ante fallo** | 503 al frontend, sin excepción sin control. |

### 2.6 Conectia / A3 (fichajes) — 🔵 Planificado

No existe ningún conector de red real: solo una interfaz abstracta (`TimeClockConnector`) que lanza `NotImplementedError`, con advertencia explícita en el propio código de que no debe usarse todavía. Lo único operativo hoy es un **importador manual de ficheros Excel** exportados a mano desde Conectia — no es una integración con un sistema externo (no abre conexión de red, no hay autenticación).

### 2.7 Búsqueda web — ✅ Implementado (indirecto)

mIA no hace peticiones HTTP a sitios web arbitrarios: delega la búsqueda en la herramienta nativa del proveedor LLM. El egress de red de mIA para esta función se limita al endpoint del proveedor LLM; el tráfico real a los sitios citados lo hace la infraestructura de OpenAI/Azure, no el proceso de mIA. Sin lista blanca/negra de dominios aplicada por mIA sobre los resultados — responsabilidad delegada al proveedor.

### 2.8 Azure AI Search / Azure ML — 🔵 Planificado, ❌ sin código real

Ambos tienen solo un contrato de interfaz vacío (`NotImplementedError`), sin SDK ni credencial en el repositorio, sin referencia en la infraestructura como código. No hay ninguna conexión real que auditar hoy.

### 2.9 Webhooks entrantes / SMTP directo — ❌ No existen

Búsqueda exhaustiva sin resultados. Todo el correo sale vía Microsoft Graph (2.2), no hay servidor de webhooks entrante.

---

## 3. Matriz de datos hacia terceros

| Categoría de dato | SharePoint | Correo (Graph) | LLM (OpenAI/Azure) | ElevenLabs (voz) |
|---|---|---|---|---|
| Nómina — **importes** | — (fuente) | — | ❌ Nunca se envía como cifra (lectura puntual con permiso propio, auditada, no persistida salvo indexación explícita) | ❌ **Nunca se dice en voz alta** (filtro explícito) |
| Nómina — metadatos (existencia, periodo) | ✅ Origen | — | ✅ Con permiso, seudonimizado si aplica | ✅ (texto sin cifras) |
| Vacaciones / turnos / empleados | ✅ Origen | — | ✅ Vía Privacy Gateway (si activo) | ✅ (nombres sin filtrar — ver hallazgo) |
| Documentos — contenido general | ✅ Origen | — | ✅ Con permiso `DOCUMENTOS_CONTENIDO`, vía Privacy Gateway | ✅ (si el asistente lo lee en voz) |
| Documentos — contenido médico | ✅ Origen | — | ✅ Solo con `DOCUMENTOS_CONTENIDO_MEDICO` adicional | ✅ (sin filtro específico adicional) |
| Firmas | ✅ Origen (solo existencia expuesta) | — | 🟡 Solo instrucción de prompt impide mostrar contenido, sin puerta de código verificada | — |
| CVs / candidaturas | ✅ Origen | ✅ (si llegan por correo) | ✅ Embeddings anonimizados (irreversible) | — |
| Correo / contenido de buzón | — | ✅ Origen | ✅ Vía Privacy Gateway (si activo) | — |
| DNI/NIE | ✅ Origen (seudonimizado antes de persistir) | Posible si aparece en correo | ✅ Tokenizado por Presidio (reversible), si gateway activo | ❌ No filtrado específicamente — riesgo si aparece en texto hablado |
| Texto de conversación del usuario | — | — | ✅ Siempre (es el canal) | ✅ (respuesta generada) |

**Lo que nunca sale según el diseño verificado**: importes de nómina (ni al LLM como cifra persistida fuera de lectura puntual auditada, ni nunca por voz).
**Lo que sale sin protección adicional de PII**: el texto enviado a ElevenLabs, más allá del filtro de importes — ver hallazgo 2.5.

---

## 4. Permisos solicitados vs. mínimos necesarios

| Integración | Permiso usado hoy (código) | Mínimo recomendado | Verificable desde el repo |
|---|---|---|---|
| SharePoint | `.default` (todo lo concedido en Entra ID) | `Sites.Selected`, acotado a 2 sitios | ❌ No — requiere revisión en el tenant |
| Correo (Graph) | `.default` (probablemente `Mail.Read`/`Send` de aplicación) | `Mail.Read`/`Send` de aplicación **+ Application Access Policy de Exchange Online** acotando al buzón de RRHH | ❌ No — requiere revisión en Exchange Online |
| Entra ID (login) | Claims `roles` únicamente, nunca `groups` | Igual (ya es mínimo privilegio) | ✅ Sí — confirmado en código |
| LLM / Voz | Claves de API de cuenta de proveedor, sin alcance granular propio del proveedor | Mismo (limitado por lo que el proveedor permite) | ✅ Sí |

**Esto es lo que IT debe aprobar con consentimiento de administrador**: el alcance real de los permisos de aplicación de SharePoint y Graph Mail no puede confirmarse desde el código — requiere una revisión directa del App Registration en el Portal de Azure/Entra ID antes de dar luz verde a producción.

---

## 5. Resiliencia y degradación

| Servicio | Si cae | Límite de cuota/coste conocido |
|---|---|---|
| SharePoint | Sincronización de esa fuente falla aislada; resto continúa; datos ya sincronizados siguen disponibles | `max_retries=5`, `concurrency=4`, paginación de 2000 |
| Correo (Graph) | Herramienta devuelve mensaje de negocio, no excepción | Reintento con backoff, tope ~30s |
| LLM | Respuesta de error genérica de la persona, nunca stack trace | 1200 tokens salida, 120s por turno, 8 rondas de herramientas — **sin límite agregado por usuario** |
| Voz | 503 al frontend | 600 caracteres máx. por síntesis — **sin límite agregado por usuario** |
| Entra ID / JWKS | Login falla controladamente; caché de 24h amortigua caídas puntuales | — |

---

## 6. Gestión de credenciales por conexión

| Credencial | Dónde vive | Quién puede leerla | Rotación | Impacto de una fuga |
|---|---|---|---|---|
| Certificado SharePoint/Correo (compartido) | Key Vault (Azure) | Managed Identity del Container App (rol `Key Vault Secrets User`, solo lectura) | No automatizada (manual) | **Alto** — afecta a ambas integraciones simultáneamente (SharePoint + Correo) |
| API key LLM | Key Vault | Igual | No automatizada | Alto — acceso a facturación/datos del proveedor |
| API key ElevenLabs | Key Vault | Igual | No automatizada | Medio — coste y posible abuso del servicio de voz |
| Clave de seudonimización (HMAC) | Key Vault | Igual | **No debe rotarse** (invalidaría los seudónimos ya generados) | Alto si se filtra combinada con los datos ya seudonimizados |
| Clave del Token Vault (Fernet) | Key Vault | Igual | No automatizada | Medio — solo protege datos en tránsito de la operación actual (TTL 900s) |

**Recomendación**: separar el certificado de SharePoint y Correo en dos credenciales distintas reduciría el radio de impacto de una fuga a una sola integración.
