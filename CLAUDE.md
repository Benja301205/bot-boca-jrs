# Bot Boca Socios - Adherente Popular (Marzo 2026)

## Objetivo
Bot Python 3.11+ con **5 instancias paralelas** para socio **adherente** que compra entradas **populares/generales** en bocasocios.bocajuniors.com.ar. Detecta apertura de venta, selecciona sector Popular en mapa SVG, agrega al carrito y **para antes del pago** (confirmación manual).

---

## Stack Tecnológico
- **Python 3.11+** (preferir 3.12+ si disponible)
- **Core:** `undetected_chromedriver`, `selenium-wire`, `requests`, `httpx` (async)
- **Concurrencia:** `multiprocessing` (5 procesos aislados) + `asyncio` dentro de cada proceso para I/O
- **Herramientas modernas:** `uv` (package manager), `ruff` (linter), `pyright` (types)
- **Testing:** `pytest`, `pytest-asyncio`, `pytest-mock`

---

## Agentes Disponibles y Su Rol en el Bot

### 1. `browser-stealth-agent`
**Cuándo usarlo:** Para toda automatización de navegador con anti-detección.
- Login automático con stealth config completa
- Extracción de tokens desde localStorage
- Simulación humana (mouse Bezier, delays random)
- Configuración de fingerprint argentino (timezone, locale, canvas, WebGL)
- Gestión de proxies residenciales AR por instancia
**Herramientas:** Todas las disponibles.

### 2. `api-polling-agent`
**Cuándo usarlo:** Para detección ultra-rápida de disponibilidad vía API directa.
- Polling agresivo (300-500ms) a `/event/{matchId}/seat/section/availability`
- Lectura de fechas de apertura desde `/event/matches/plus`
- Campos clave: `fechaPlateaAdherente`, `fechaGeneralesAdherente`
- Detección de `hayDisponibilidad: true` en sectores POP antes que la UI
**Se lanza desde:** `orchestrator-agent` cuando hay credenciales y matchId.

### 3. `svg-map-agent`
**Cuándo usarlo:** SOLO después de que `api-polling-agent` confirme disponibilidad.
- Analiza el mapa SVG del estadio (`#seccion-POP*`)
- Detecta fill colors: `#3FBF74` (verde/disponible) vs `#DAE0EB` (gris/no disponible)
- Prioridad de click: `POP2S_1_` → `POPSN_1_` → otros POP disponibles
- Extrae `sectionNid` para agregar al carrito
**Trigger:** Solo cuando ApiPollingAgent retorna `{available: true}`.

### 4. `orchestrator-agent`
**Cuándo usarlo:** Para coordinar los 5 bots en paralelo.
- Asigna proxy + cuenta distinta a cada instancia
- Calcula timer de wake-up según fecha de apertura adherente
- Lanza `browser-stealth-agent` + `api-polling-agent` por instancia
- Manejo global de errores (403 `invalidQueueId` → kill + relaunch con nuevo proxy)
- **Gate de confirmación manual** antes del pago (NUNCA pagar automáticamente)
**Herramientas:** Todas las disponibles.

### 5. `Explore` (subagent)
**Cuándo usarlo:** Para investigar la estructura del sitio, endpoints, SVG, etc.
- Búsqueda profunda en el codebase
- Análisis de patrones en archivos

### 6. `Plan` (subagent)
**Cuándo usarlo:** Para diseñar la estrategia de implementación paso a paso.
- Planificación arquitectónica antes de escribir código
- Identificar archivos críticos y trade-offs

---

## Skills Instaladas y Cómo Aplicarlas

### Automatización de Browser
| Skill | Aplicación en el Bot |
|-------|---------------------|
| **browser-automation** | Patrones de auto-wait, locators user-facing, aislamiento por instancia |
| **stealth-browser** | Chrome invisible vía CDP, AppleScript hide, LEARNED.md para quirks por dominio |
| **selenium** | Referencia para Selenium Wire + undetected_chromedriver |
| **web-scraper** | Estrategia multi-fase: CLARIFY → RECON → STRATEGY → EXTRACT → VALIDATE |

### API Polling y Async
| Skill | Aplicación en el Bot |
|-------|---------------------|
| **web-scraping** | Cascade de scraping, detección de poison pills (403, 429, CAPTCHA), respectful delays |
| **async-python-patterns** | `asyncio.gather()` para polling concurrente, `httpx` async para requests, timeouts |
| **python-patterns** | Regla de oro: I/O-bound → async, CPU-bound → multiprocessing |

### Performance y Multiprocessing
| Skill | Aplicación en el Bot |
|-------|---------------------|
| **python-performance-optimization** | Profiling con cProfile/py-spy, optimización de loops de polling |
| **python-pro** | `concurrent.futures.ProcessPoolExecutor`, tooling moderno (uv, ruff) |

### Error Handling y Debugging
| Skill | Aplicación en el Bot |
|-------|---------------------|
| **error-handling-patterns** | Retry exponential backoff, circuit breaker para proxies, graceful degradation |
| **systematic-debugging** | 4 fases: Root Cause → Pattern Analysis → Hypothesis → Implementation |
| **debugging-strategies** | Instrumentación en cada boundary, profiling, captura de environment |

### Testing
| Skill | Aplicación en el Bot |
|-------|---------------------|
| **python-testing-patterns** | Mock de Selenium/API calls, pytest-asyncio para tests de polling, fixtures |

### Infraestructura
| Skill | Aplicación en el Bot |
|-------|---------------------|
| **bash-pro** | Scripts de lanzamiento con `set -Eeuo pipefail`, cronjobs, log rotation |
| **fastapi-pro** | Si se necesita dashboard/API de control del bot |

---

## Estructura de Proyecto

```
Bot boca jrs/
├── CLAUDE.md                    # Este archivo
├── .env                         # Cuentas, proxies, MATCH_ID (NO commitear)
├── .env.example                 # Template sin datos reales
├── pyproject.toml               # Dependencias con uv
├── main.py                      # Orquestador: multiprocessing Pool de 5 bots
├── core/
│   └── bot_instance.py          # Clase BotInstance con flujo completo run()
├── utils/
│   ├── browser.py               # create_stealth_browser(proxy) + login + tokens
│   ├── api.py                   # ApiSession: polling, opening times, headers Bearer
│   ├── svg.py                   # Detección SVG: colores, click sector, prioridad POP
│   └── cart.py                  # Agregar al carrito + avanzar + PAUSA manual
├── config/
│   └── settings.py              # Carga .env, constantes, timeouts
├── logs/                        # Logs por instancia + timestamps
└── screenshots/                 # Capturas automáticas de éxito/fallo
```

---

## Reglas Estrictas (NUNCA ROMPER)

### Prioridad API > UI
- **SIEMPRE** priorizar polling de la API sobre interacción con UI
- La API responde antes que el SVG se renderice → ventaja de milisegundos
- Usar UI solo como fallback o para clicks que la API no resuelve (SVG)

### Seguridad de Pago
- **NUNCA** completar el pago automáticamente
- Flag `dry_run=True` por defecto en todo el código
- `input("¿Confirmar y pagar? (y/n): ")` obligatorio antes de `/confirmation`
- Guardar screenshot ANTES de la pantalla de pago

### Anti-Detección
- **undetected_chromedriver** como base obligatoria
- Cada instancia con proxy residencial AR distinto (5 proxies, 5 cuentas)
- User-Agent argentino reciente + spoofing Canvas/WebGL/fonts/timezone
- Mouse Bezier curves + delays aleatorios (0.8 - 3.2 seg)
- Nunca reusar sesión entre intentos fallidos

### Manejo de Errores
- **403 `invalidQueueId`:** Kill instancia → nuevo proxy → reiniciar browser
- **Sectores grises (`#DAE0EB`):** Normal, continuar polling
- **429 Rate Limit:** Backoff exponencial (1s → 2s → 4s → 8s) con jitter
- **Timeout de red:** Retry hasta 3 veces, luego escalar a orchestrator
- **1 bot falla ≠ 4 bots mueren:** Aislamiento total entre procesos

### Socio Adherente
- Usar SOLO campos de fechas adherente: `fechaPlateaAdherente`, `fechaGeneralesAdherente`
- Las fechas de activos son anteriores → ignorarlas
- La apertura adherente suele ser 1-2 días antes del partido, horario posterior al de activos

---

## Estrategia de Compra (Flujo Paso a Paso)

```
1. SETUP
   ├── Cargar .env (5 cuentas + 5 proxies + MATCH_ID)
   ├── Lanzar 5 procesos con multiprocessing
   └── Cada proceso: create_stealth_browser(proxy_n)

2. LOGIN
   ├── Navegar a bocasocios.bocajuniors.com.ar
   ├── Login con credenciales de la cuenta asignada
   └── Extraer authToken + refreshToken de localStorage["boca-secure-storage\authStore"]

3. MONITOREO DE APERTURA
   ├── GET /event/matches/plus → leer fechaGeneralesAdherente
   ├── Calcular segundos hasta apertura
   ├── Sleep inteligente (no polling hasta 5 min antes)
   └── Cuando faltan <5 min: polling cada 10 seg al botón generals-continue

4. APERTURA DETECTADA
   ├── Click en button[data-testid$="-generals-continue"] cuando isDisabled=false
   └── Navegar al mapa de sectores

5. DETECCIÓN DE DISPONIBILIDAD (paralelo)
   ├── API: GET /event/{matchId}/seat/section/availability cada 300-500ms
   ├── SVG: Monitorear #seccion-POP* por fill="#3FBF74"
   └── Primer señal positiva → continuar

6. SELECCIÓN DE SECTOR
   ├── Prioridad: POP2S_1_ → POPSN_1_ → cualquier POP verde
   ├── Click en SVG path del sector
   └── Extraer sectionNid

7. CARRITO
   ├── POST /member/shoppingCart/item con sectionNid
   ├── Avanzar con botones *-generals-continue / *-plateas-continue
   └── Screenshot automático

8. PAUSA MANUAL (OBLIGATORIA)
   ├── print("Sector conseguido: {sector}")
   ├── Screenshot final
   └── input("¿Confirmar y pagar? (y/n): ") ← HUMANO DECIDE
```

---

## Configuración .env Esperada

```env
# Cuentas adherentes (5)
ACCOUNT_1_USER=usuario1@email.com
ACCOUNT_1_PASS=password1
ACCOUNT_2_USER=usuario2@email.com
ACCOUNT_2_PASS=password2
ACCOUNT_3_USER=usuario3@email.com
ACCOUNT_3_PASS=password3
ACCOUNT_4_USER=usuario4@email.com
ACCOUNT_4_PASS=password4
ACCOUNT_5_USER=usuario5@email.com
ACCOUNT_5_PASS=password5

# Proxies residenciales AR (5)
PROXY_1=http://user:pass@ar-proxy1:port
PROXY_2=http://user:pass@ar-proxy2:port
PROXY_3=http://user:pass@ar-proxy3:port
PROXY_4=http://user:pass@ar-proxy4:port
PROXY_5=http://user:pass@ar-proxy5:port

# Partido
MATCH_ID=834
API_BASE=https://bocasocios.bocajuniors.com.ar/api

# Configuración
DELAY_MIN=0.8
DELAY_MAX=3.2
POLL_INTERVAL_MS=400
DRY_RUN=true
LOG_LEVEL=INFO
```

---

## Endpoints API Conocidos

| Método | Endpoint | Uso |
|--------|----------|-----|
| GET | `/event/matches/plus` | Fechas de apertura por tipo de socio |
| GET | `/event/{matchId}/seat/section/availability` | Disponibilidad de sectores (polling) |
| POST | `/member/shoppingCart/item` | Agregar sector al carrito |
| GET | `/member/shoppingCart` | Ver carrito actual |
| - | `localStorage["boca-secure-storage\authStore"]` | Tokens auth (post-login) |

---

## Logging y Evidencia
- Cada instancia loguea con prefijo `[BOT-{n}][PROXY-{ip}]`
- Timestamps ISO 8601 en cada línea
- Screenshots automáticos en: login exitoso, apertura detectada, sector clickeado, carrito, pre-pago
- Archivo de log por instancia: `logs/bot_{n}_{timestamp}.log`
- Log consolidado: `logs/orchestrator_{timestamp}.log`
