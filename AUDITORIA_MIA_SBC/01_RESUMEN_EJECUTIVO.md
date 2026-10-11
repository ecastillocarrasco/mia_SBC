# 01 - Resumen Ejecutivo

**Proyecto:** mIA SBC — Sunset Beach Club  
**Fecha de auditoría:** 2026-10-06  
**Auditor:** Claude Sonnet 4.6 (automatizado)  
**Directorio:** `c:\Users\enriq\Desktop\Proyectos\Sunset\mIA`

---

## Situación Global

mIA SBC es una plataforma de IA conversacional para Recursos Humanos hoteleros. El backend es FastAPI + asyncio con streaming SSE; el frontend es Vite/JS con avatar 2D y 3D. La base de datos es PostgreSQL (SQLite en tests). Las fuentes de datos son SharePoint (listas HR) + Microsoft Graph (correo).

**Estado general estimado:** Proyecto maduro en dominio RRHH con cobertura funcional alta. No apto para producción sin configuración de infraestructura (SharePoint real, LLM API key, auth Entra ID), pero la arquitectura es sólida y lista para conectar esa infraestructura.

---

## Fortalezas

1. Arquitectura modular y limpia: cada dominio en su propio paquete con `register()` bien delimitado.
2. Sistema de permisos tipado (Permission enum) aplicado en cada herramienta.
3. Pista de auditoría en AuditEvent para accesos a datos sensibles.
4. Presentación separada del LLM: el frontend recibe objetos `presentation` tipados que el LLM no reescribe.
5. Guard determinista que elimina en código promesas imposibles e importes de voz.
6. Parser de nóminas capaz de extraer devengado, líquido, IRPF, conceptos y SS-empresa.
7. Cobertura de tests amplia: 30+ ficheros de test incluyendo dominios E2E, consultas cruzadas y reportes.
8. Reglas de negocio explícitas: NOM-002/004, SEL-001, NOM-003 documentadas y aplicadas en código.
9. Módulo finanzas ya registrado como placeholder con vocabulario de enrutado: el orquestador no necesita cambiar cuando lleguen datos.
10. Historial conversacional persistido en BD (12 turnos).

---

## Debilidades

1. Finanzas completamente vacía: ninguna herramienta activa (0 tools registradas).
2. Modelo Employee sin campos: género, hire_date, contract_type, jornada. Afecta ~8 preguntas del CSV.
3. Correo 100% condicional a Graph API + mailbox configurado: en demo/dev no funciona.
4. Nóminas con importes requieren content_enabled=True + SharePoint real + permiso NOMINAS_IMPORTES.
5. Sin sistema de fichajes: las preguntas de control de presencia real no pueden responderse.
6. Sin módulos de evaluación de desempeño, formación (catálogo), calendario laboral ni salud laboral.
7. Frontend hologram world tiene un fichero `main - copia.js` (artefacto de desarrollo).
8. History a 12 turnos es limitado para conversaciones largas.
9. La BD es SQLite local (`mia_local.db` en raíz) lo que sugiere que en producción se necesita PostgreSQL configurado.
10. El módulo predictivo (`src/mia/analytics/`) existe en el árbol pero no está conectado al conversacional.

---

## Cobertura Estimada de Preguntas (CSV base)

| Estado       | Cantidad | % |
|---|---|---|
| ✅ SOPORTADA  | 226      | 61.8% |
| 🟡 PARCIALMENTE | 46    | 12.6% |
| 🔴 NO SOPORTADA | 93    | 25.4% |

**De las 🔴 no soportadas:**
- 11 por módulo Finanzas vacío (no hay datos)
- 8 por campos faltantes en modelo Employee (género, hire_date, contract_type)
- 5 por falta de módulos enteros (evaluación, formación, calendario laboral, salud laboral)
- 4 por ausencia de sistema de fichajes
- 3 restricciones de negocio explícitas (SEL-001, escritura prohibida)
- Resto por funcionalidades genuinamente complejas aún no implementadas

---

## Principales Riesgos

1. Sin SharePoint configurado, el 80% del valor no está disponible.
2. Auth en modo DEV en producción — bloqueado por validación en settings.py.
3. Sin certificado PFX configurado, SharePoint no se conecta.
4. mia_local.db en raíz del proyecto (no versionado) puede perderse o corromperse.
5. Módulo analytics/ (predictivo) no conectado al conversacional todavía.

---

## Preparación para Producción

| Criterio | Estado |
|---|---|
| Arquitectura backend | LISTA |
| Tests unitarios/integración | BUENOS |
| Auth Entra ID | IMPLEMENTADA (requiere config) |
| SharePoint connector | IMPLEMENTADO (requiere cert+URL) |
| LLM connector | IMPLEMENTADO (requiere API key) |
| Finanzas | NO LISTA (sin datos) |
| Frontend avatar 3D | FUNCIONAL |
| Informes PDF/Excel/PPTX | FUNCIONALES |
| Auditoría de accesos | IMPLEMENTADA |

**Veredicto:** Lista para demo/preproducción con datos reales de SharePoint. No lista para producción autónoma sin configuración de infraestructura y sin la jornada de hardening de seguridad (CORS origins, auth mode=entra, pseudonym key desde Key Vault).
