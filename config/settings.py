"""
config/settings.py
Carga de variables de entorno, constantes y timeouts del bot.
"""

import os
import sys
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Cargar .env desde la raiz del proyecto
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


# --- Constantes del sitio ---
SITE_BASE = "https://bocasocios.bocajuniors.com.ar"
API_BASE = os.getenv("API_BASE", f"{SITE_BASE}/api")
SVG_STADIUM_URL = "https://pgscdn.obs.la-south-2.myhuaweicloud.com/app/portal/MapStadium.svg"

# --- URLs del flujo ---
URL_HOME = f"{SITE_BASE}/home"
URL_MATCHES = f"{SITE_BASE}/matches"
URL_ASSIST = f"{SITE_BASE}/matches/{{match_id}}/assist?backUrl=/matches"
URL_PLATEAS = f"{SITE_BASE}/matches/{{match_id}}/plateas"
URL_GENERALS = f"{SITE_BASE}/matches/{{match_id}}/generals"
URL_SEATS = f"{SITE_BASE}/matches/{{match_id}}/plateas/seats/{{section_nid}}"
URL_CONFIRMATION = f"{SITE_BASE}/matches/{{match_id}}/confirmation"

# --- Endpoints API ---
EP_MATCHES_PLUS = "/event/matches/plus"
EP_SECTION_AVAILABILITY = "/event/{match_id}/seat/section/availability"
EP_SHOPPING_CART = "/member/shoppingCart"
EP_SHOPPING_CART_ITEM = "/member/shoppingCart/item"

# --- Selectores CSS ---
SEL_GENERALS_BTN = 'button[data-testid$="-generals-continue"]'
SEL_PLATEAS_BTN = 'button[data-testid$="-plateas-continue"]'
SEL_SVG_MAP = ".stadium-map"
SEL_SVG_SECTOR_POP = '.stadium-map [id^="seccion-POP"]'

# --- Colores SVG ---
COLOR_DISPONIBLE = "#3FBF74"
COLOR_NO_DISPONIBLE = "#DAE0EB"
COLOR_SELECCIONADO = "#E8A81C"

# --- Prioridad de sectores Popular ---
SECTOR_PRIORITY = [
    "POP2S_1_",
    "POPSN_1_",
    "POP2N_1_",
    "POP3S_1_",
    "POP3N",
    "POPSS_1_",
]

# --- Auth storage key en localStorage ---
AUTH_STORAGE_KEY = r"boca-secure-storage\authStore"

# --- User-Agents argentinos recientes (Chrome en Windows/Mac) ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]


@dataclass
class AccountConfig:
    """Configuracion de una cuenta de socio."""
    user: str
    password: str
    proxy: str
    bot_id: int


@dataclass
class BotSettings:
    """Configuracion global del bot."""
    match_id: str = os.getenv("MATCH_ID", "834")
    api_base: str = API_BASE
    delay_min: float = float(os.getenv("DELAY_MIN", "0.8"))
    delay_max: float = float(os.getenv("DELAY_MAX", "3.2"))
    poll_interval_ms: int = int(os.getenv("POLL_INTERVAL_MS", "400"))
    dry_run: bool = os.getenv("DRY_RUN", "true").lower() == "true"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    socio_tipo: str = os.getenv("SOCIO_TIPO", "adherente")
    entrada_tipo: str = os.getenv("ENTRADA_TIPO", "generals")
    num_bots: int = 5
    accounts: list[AccountConfig] = field(default_factory=list)

    def __post_init__(self):
        """Cargar las 5 cuentas y proxies desde .env."""
        for i in range(1, self.num_bots + 1):
            user = os.getenv(f"ACCOUNT_{i}_USER", "")
            password = os.getenv(f"ACCOUNT_{i}_PASS", "")
            proxy = os.getenv(f"PROXY_{i}", "")
            if user and password:
                self.accounts.append(AccountConfig(
                    user=user,
                    password=password,
                    proxy=proxy,
                    bot_id=i,
                ))

    @property
    def poll_interval_sec(self) -> float:
        """Intervalo de polling en segundos."""
        return self.poll_interval_ms / 1000.0

    def get_account(self, bot_id: int) -> AccountConfig:
        """Obtener la configuracion de cuenta para un bot especifico."""
        for acc in self.accounts:
            if acc.bot_id == bot_id:
                return acc
        raise ValueError(f"No se encontro cuenta para bot_id={bot_id}")


def load_settings() -> BotSettings:
    """Carga y valida la configuracion. Sale con error si faltan datos criticos."""
    settings = BotSettings()

    if not settings.accounts:
        print("[ERROR] No se encontraron cuentas en .env. Copia .env.example a .env y completa.")
        sys.exit(1)

    if settings.dry_run:
        print("[INFO] Modo DRY_RUN activado. No se completara ningun pago.")

    print(f"[INFO] Match ID: {settings.match_id}")
    print(f"[INFO] Tipo socio: {settings.socio_tipo}")
    print(f"[INFO] Tipo entrada: {settings.entrada_tipo}")
    print(f"[INFO] Cuentas cargadas: {len(settings.accounts)}")
    print(f"[INFO] Polling interval: {settings.poll_interval_ms}ms")

    return settings
