# 18 - Funcionalidades Ocultas

Código implementado y funcional que el usuario no puede invocar actualmente desde el chat, bien porque requiere configuración no activa, porque el usuario no conoce la tool, o porque no hay un camino conversacional obvio para llegar a ella.

---

## 🔵 Funcionalidades implementadas pero no accesibles actualmente

### 1. Estadísticas salariales con percentiles 25 y 75

**Tool:** `estadisticas_salariales` en `nominas/estadisticas.py`  
**Qué hace:** Calcula suma, media, mediana, mínimo, máximo, percentil_25 y percentil_75 del líquido de un grupo.  
**Por qué no se usa:** Requiere `content_enabled=True` + SharePoint configurado + permiso `NOMINAS_IMPORTES`.  
**Cómo activar:** Configurar SharePoint con datos reales y asignar rol `mia.rrhh`.

---

### 2. Desglose de conceptos salariales de una nómina

**Tool:** `nomina_importes` → `parse_concepts()` en `nominas/parser.py`  
**Qué hace:** Extrae todos los conceptos salariales (salario base, pluses, complementos) y deducciones de una nómina PDF.  
**Por qué no se usa:** Requiere content_enabled + SharePoint + NOMINAS_IMPORTES.  
**Cómo activar:** Igual que estadísticas.  
**Nota:** El CSV marcaba esto como 🔴 NO SOPORTADA (preguntas 161-162), pero el código ya existe y funciona.

---

### 3. Aportación de la empresa a la SS (coste total empresa)

**Tool:** `nomina_importes` → `parse_employer_ss()` en `nominas/parser.py`  
**Qué hace:** Extrae desglose de SS-empresa (contingencias comunes, AT, desempleo, FOGASA) y calcula el coste total empresa = devengado + SS-empresa.  
**Por qué no se usa:** Idem.  
**Nota:** El CSV marcaba esto como 🔴 NO SOPORTADA, pero el código existe.

---

### 4. Empleados próximos a jubilación

**Tool:** `proximos_jubilacion` en `analitica/tools.py`  
**Qué hace:** Lista empleados activos que se jubilarán en los próximos N años (por defecto 5), con edad actual y año de jubilación aproximado.  
**Por qué puede no usarse:** Tool nueva. El CSV la marcaba como 🔴 NO SOPORTADA (pregunta 284), pero ya está implementada.  
**Cómo invocar:** "¿Qué empleados están próximos a jubilarse?" o "¿Quién se jubila antes de 2030?"

---

### 5. Detección de anomalías en nóminas

**Tool:** `anomalias_nominas` en `nominas/tools.py`  
**Qué hace:** Detecta duplicados, faltantes y huérfanos en un periodo de nóminas.  
**Por qué puede no usarse:** Tool nueva. El CSV la marcaba como 🔴 NO SOPORTADA (pregunta 170), pero ya está implementada.  
**Cómo invocar:** "¿Hay alguna anomalía en las nóminas de octubre?" o "¿Hay nóminas duplicadas este mes?"

---

### 6. Boletines ETT faltantes

**Tool:** `boletines_faltantes_tt` en `trabajo_temporal/tools.py`  
**Qué hace:** Lista trabajadores ETT visibles sin ningún boletín en el periodo (por defecto el mes en curso).  
**Por qué puede no usarse:** Tool nueva. El CSV la marcaba como 🟡 PARCIALMENTE (pregunta 322), pero ya está completamente implementada.  
**Cómo invocar:** "¿Hay trabajadores de ETT sin boletín este mes?"

---

### 7. Variación de coste ETT entre periodos

**Tool:** `variacion_coste_tt` en `trabajo_temporal/tools.py`  
**Qué hace:** Compara coste, horas y boletines de ETT entre el mes actual y el anterior (o periodos customizados).  
**Por qué puede no usarse:** Tool nueva. El CSV la marcaba como 🟡 PARCIALMENTE (pregunta 323), pero ya está completamente implementada.  
**Cómo invocar:** "¿Cuánto ha variado el coste de ETT respecto al mes pasado?"

---

### 8. Conflictos de vacaciones en el departamento

**Tool:** `conflictos_vacaciones` en `vacaciones/tools.py`  
**Qué hace:** Para una persona y periodo, muestra quién de su departamento está ausente y si hay solapamiento. También muestra el saldo de la persona.  
**Por qué puede no usarse:** Tool nueva. El CSV la marcaba como 🟡 PARCIALMENTE (pregunta 135), pero ya está completamente implementada.  
**Cómo invocar:** "¿Puede Ana Torres coger vacaciones la semana que viene sin solapamientos?" o "¿Hay conflictos si Pedro García se va de vacaciones del 15 al 22?"

---

### 9. Evolución interanual de nóminas con comparación

**Tool:** `evolucion_nominas` con `comparar_con_anio_anterior=True`  
**Qué hace:** Muestra la evolución mensual de importes de una persona en un año y, si se pide, compara con el año anterior calculando la variación en euros y porcentaje.  
**Por qué puede no usarse:** El parámetro `comparar_con_anio_anterior` no es obvio en la invocación natural. El usuario puede preguntar "¿cuánto ha subido el sueldo de Ana Torres?" y mIA debería activarlo automáticamente con ese parámetro.  
**Requiere:** content_enabled + SharePoint + NOMINAS_IMPORTES.

---

### 10. Voz con ElevenLabs

**Módulo:** `voice/` + `conversation/speech.py`  
**Qué hace:** Sintetiza voz de las respuestas de mIA en MP3, excluyendo importes y promesas.  
**Por qué no se usa:** `VoiceProviderName.NONE` en configuración por defecto.  
**Cómo activar:** Configurar `MIA_VOICE__PROVIDER=elevenlabs`, `MIA_VOICE__API_KEY` y `MIA_VOICE__VOICE_ID`.

---

### 11. Calidad de datos (admin only)

**Tool:** `calidad_datos` / `calidad` en `analitica/tools.py`  
**Qué hace:** Analiza la calidad de los datos en el sistema (empleados sin email, sin puesto, nóminas huérfanas, etc.).  
**Por qué no se usa:** Requiere permiso `ADMINISTRAR` — solo para el rol `mia.admin`.  
**Cómo invocar con permisos:** "¿Hay algún problema de calidad de datos en el sistema?"

---

### 12. Módulo predictivo (analytics/)

**Directorio:** `src/mia/analytics/`  
**Qué hay:** Infraestructura básica (directorios, posiblemente contratos de tipos).  
**Por qué no se usa:** No conectado al motor de conversación.  
**Potencial:** Forecasting de plantilla, predicción de bajas, análisis de correlaciones, scoring de riesgo.
