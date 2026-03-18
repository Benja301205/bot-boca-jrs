"""
core/bot_instance.py
Clase BotInstance: flujo completo de un bot individual.
Cada instancia corre en su propio proceso con proxy y cuenta distintos.
"""

import logging
import os
import time
import random
import threading
from datetime import datetime
from typing import Any

from selenium.webdriver.common.by import By

from config.settings import (
    AccountConfig,
    BotSettings,
    URL_MATCHES,
    SEL_GENERALS_BTN,
    SEL_PLATEAS_BTN,
)
from utils.browser import (
    create_stealth_browser,
    login,
    extract_tokens,
    take_screenshot,
    close_browser,
)
from utils.api import ApiSession, InvalidQueueError
from utils.svg import (
    wait_for_svg_map,
    scan_popular_sectors,
    click_sector_by_js,
    get_section_nid_from_api_response,
)
from utils.cart import (
    navigate_to_seats,
    click_continue_button,
    add_to_cart_via_ui,
    advance_to_confirmation,
    manual_payment_pause,
)
from utils.human import random_delay, short_delay, smooth_scroll, human_click


logger = logging.getLogger(__name__)


class BotInstance:
    """
    Instancia individual del bot. Ejecuta el flujo completo:
    Login → Monitoreo apertura → Deteccion disponibilidad → Seleccion sector → Carrito → Pausa manual.
    """

    def __init__(self, account: AccountConfig, settings: BotSettings, headless: bool = False):
        self.account = account
        self.settings = settings
        self.headless = headless
        self.bot_id = account.bot_id
        self.prefix = f"[BOT-{self.bot_id}][PROXY-{self._extract_proxy_ip()}]"
        self.driver = None
        self.api_session: ApiSession | None = None
        self.auth_token: str | None = None
        self.refresh_token: str | None = None
        self.sector_found: str | None = None
        self.section_nid: int | None = None

    def _extract_proxy_ip(self) -> str:
        """Extrae la IP del proxy para logging."""
        proxy = self.account.proxy
        if not proxy:
            return "direct"
        try:
            # http://user:pass@host:port -> host
            parts = proxy.split("@")
            if len(parts) > 1:
                return parts[1].split(":")[0]
            return proxy.split("//")[1].split(":")[0]
        except Exception:
            return proxy[:20]

    def run(self) -> dict:
        """
        Flujo principal del bot. Ejecuta todos los pasos secuencialmente.
        Retorna dict con resultado: { success, sector, error, bot_id }
        """
        result = {"success": False, "sector": None, "error": None, "bot_id": self.bot_id}

        try:
            # --- PASO 1: SETUP ---
            logger.info(f"{self.prefix} === INICIO BOT ===")
            logger.info(f"{self.prefix} Cuenta: {self.account.user}")
            logger.info(f"{self.prefix} Match ID: {self.settings.match_id}")
            logger.info(f"{self.prefix} Tipo entrada: {self.settings.entrada_tipo}")

            self.driver = create_stealth_browser(self.account, headless=self.headless)
            take_screenshot(self.driver, self.bot_id, "browser_created")

            # --- PASO 2: LOGIN ---
            logger.info(f"{self.prefix} === LOGIN ===")
            if not login(self.driver, self.account):
                raise Exception("Login fallido")

            tokens = extract_tokens(self.driver, self.bot_id)
            if not tokens:
                raise Exception("No se pudieron extraer tokens post-login")

            self.auth_token = tokens["authToken"]
            self.refresh_token = tokens.get("refreshToken")
            take_screenshot(self.driver, self.bot_id, "login_success")

            # Crear sesion de API con los tokens
            self.api_session = ApiSession(
                bot_id=self.bot_id,
                auth_token=self.auth_token,
                refresh_token=self.refresh_token,
                proxy=self.account.proxy,
                settings=self.settings,
            )

            # --- PASO 3: MONITOREO DE APERTURA ---
            logger.info(f"{self.prefix} === MONITOREO DE APERTURA ===")
            self._wait_for_sale_open()

            # --- PASO 4: NAVEGAR A MATCHES Y CLICKEAR BOTON ---
            logger.info(f"{self.prefix} === CLICKEAR BOTON DE ENTRADA ===")
            self._navigate_and_click_entry_button()

            # --- PASO 5: DETECCION DE DISPONIBILIDAD (API + SVG en paralelo) ---
            logger.info(f"{self.prefix} === DETECCION DE DISPONIBILIDAD ===")
            sector_data = self._detect_availability()

            if not sector_data:
                raise Exception("No se encontro sector disponible en tiempo limite")

            self.sector_found = sector_data["sector_id"]
            self.section_nid = sector_data.get("nid")

            take_screenshot(self.driver, self.bot_id, f"sector_{self.sector_found}")

            # --- PASO 6: SELECCIONAR SECTOR Y AGREGAR AL CARRITO ---
            logger.info(f"{self.prefix} === CARRITO ===")
            self._add_sector_to_cart(sector_data)

            # --- PASO 7: AVANZAR HACIA CONFIRMACION ---
            logger.info(f"{self.prefix} === AVANZANDO AL PAGO ===")
            advance_to_confirmation(self.driver, self.bot_id, self.settings.match_id)

            # --- PASO 8: PAUSA MANUAL OBLIGATORIA ---
            logger.info(f"{self.prefix} === PAUSA MANUAL ===")
            paid = manual_payment_pause(
                self.driver, self.bot_id, self.sector_found, self.settings
            )

            result["success"] = True
            result["sector"] = self.sector_found
            result["paid"] = paid

            logger.info(f"{self.prefix} === FIN EXITOSO === Sector: {self.sector_found}")

        except InvalidQueueError:
            logger.error(f"{self.prefix} invalidQueueId — necesita reinicio con nuevo proxy")
            result["error"] = "invalidQueueId"
            take_screenshot(self.driver, self.bot_id, "error_invalid_queue")

        except Exception as e:
            logger.error(f"{self.prefix} Error fatal: {e}", exc_info=True)
            result["error"] = str(e)
            if self.driver:
                take_screenshot(self.driver, self.bot_id, "error_fatal")

        finally:
            # No cerrar el browser inmediatamente si encontro sector (para revision manual)
            if not result["success"] and self.driver:
                close_browser(self.driver, self.bot_id)

        return result

    # ---------------------------------------------------------------
    # PASO 3: Esperar apertura de venta
    # ---------------------------------------------------------------

    def _wait_for_sale_open(self) -> None:
        """
        Monitorea la fecha de apertura para adherentes.
        Duerme inteligentemente hasta 5 minutos antes, luego polling cada 10 seg.
        """
        opening_time = self.api_session.get_adherente_opening_time()

        if opening_time:
            now = datetime.now(opening_time.tzinfo) if opening_time.tzinfo else datetime.now()
            diff = (opening_time - now).total_seconds()

            if diff > 0:
                logger.info(f"{self.prefix} Apertura en {diff:.0f} segundos ({opening_time})")

                # Si faltan mas de 5 minutos, dormir hasta 5 min antes
                if diff > 300:
                    sleep_time = diff - 300
                    logger.info(f"{self.prefix} Durmiendo {sleep_time:.0f}s hasta 5 min antes de apertura")
                    time.sleep(sleep_time)

                # Ultimos 5 minutos: polling cada 10 segundos
                logger.info(f"{self.prefix} Entrando en modo polling pre-apertura")
                while True:
                    now = datetime.now(opening_time.tzinfo) if opening_time.tzinfo else datetime.now()
                    remaining = (opening_time - now).total_seconds()
                    if remaining <= 0:
                        logger.info(f"{self.prefix} APERTURA! Hora actual >= hora de apertura")
                        break
                    logger.debug(f"{self.prefix} Faltan {remaining:.0f}s para apertura")
                    time.sleep(min(10, remaining))
            else:
                logger.info(f"{self.prefix} La venta ya abrio (apertura fue {opening_time})")
        else:
            logger.warning(f"{self.prefix} No se pudo obtener fecha de apertura. Continuando igualmente.")
            random_delay(2.0, 4.0)

    # ---------------------------------------------------------------
    # PASO 4: Navegar y clickear boton de entrada
    # ---------------------------------------------------------------

    def _navigate_and_click_entry_button(self) -> None:
        """
        Navega a /matches, encuentra el partido, y clickea el boton de generales o plateas.
        Espera hasta que el boton deje de estar disabled.
        """
        # Navegar a la lista de partidos
        self.driver.get(URL_MATCHES)
        random_delay(2.0, 4.0)
        smooth_scroll(self.driver, 200)

        # Determinar selector segun tipo de entrada
        if self.settings.entrada_tipo == "generals":
            btn_selector = SEL_GENERALS_BTN
            btn_name = "generals-continue"
        else:
            btn_selector = SEL_PLATEAS_BTN
            btn_name = "plateas-continue"

        logger.info(f"{self.prefix} Buscando boton: {btn_selector}")

        # Polling hasta que el boton este habilitado
        max_wait = 600  # 10 minutos max
        start = time.time()

        while time.time() - start < max_wait:
            try:
                buttons = self.driver.find_elements(By.CSS_SELECTOR, btn_selector)

                for btn in buttons:
                    if btn.is_displayed():
                        text = btn.text.strip()
                        is_disabled = btn.get_attribute("aria-disabled") == "true" or not btn.is_enabled()

                        logger.debug(f"{self.prefix} Boton encontrado: texto='{text}' disabled={is_disabled}")

                        if not is_disabled and text.lower() != "próximamente":
                            logger.info(f"{self.prefix} Boton HABILITADO: '{text}' — clickeando!")
                            take_screenshot(self.driver, self.bot_id, "button_enabled")

                            # Click con comportamiento humano
                            human_click(self.driver, btn)
                            random_delay(1.5, 3.0)

                            logger.info(f"{self.prefix} Boton clickeado. URL actual: {self.driver.current_url}")
                            return

                        elif "próximamente" in text.lower() or is_disabled:
                            logger.debug(f"{self.prefix} Boton aun deshabilitado. Texto: '{text}'")

            except Exception as e:
                logger.debug(f"{self.prefix} Error buscando boton: {e}")

            # Esperar antes de reintentar
            time.sleep(10 + random.uniform(-2, 2))
            # Refrescar la pagina cada 2 minutos
            if int(time.time() - start) % 120 < 12:
                self.driver.refresh()
                random_delay(2.0, 4.0)

        raise Exception(f"Timeout esperando boton {btn_name} habilitado ({max_wait}s)")

    # ---------------------------------------------------------------
    # PASO 5: Detectar disponibilidad (API + SVG)
    # ---------------------------------------------------------------

    def _detect_availability(self) -> dict | None:
        """
        Detecta disponibilidad de sectores Popular via API y SVG en paralelo.
        La API tiene prioridad (mas rapida que el render del SVG).

        Returns:
            dict con sector_id, nid y element si disponible
        """
        max_wait = 300  # 5 minutos
        start = time.time()
        poll_interval = self.settings.poll_interval_sec

        # Resultado compartido entre threads (error tambien se propaga)
        result: dict[str, Any] = {"found": False, "data": None, "error": None}

        def api_poll():
            """Thread de polling via API."""
            while not result["found"] and time.time() - start < max_wait:
                try:
                    available = self.api_session.find_available_popular_sectors()
                    if available:
                        best = available[0]
                        logger.info(
                            f"{self.prefix} [API] Sector disponible: "
                            f"{best['codigo']} (nid={best.get('nid')})"
                        )
                        result["data"] = {
                            "sector_id": best["codigo"],
                            "nid": best.get("nid"),
                            "source": "api",
                        }
                        result["found"] = True
                        return
                except InvalidQueueError as e:
                    # Guardar el error para que el thread principal lo propague
                    result["error"] = e
                    return
                except Exception as e:
                    logger.debug(f"{self.prefix} [API] Error polling: {e}")

                time.sleep(poll_interval + random.uniform(-0.05, 0.1))

        # Iniciar polling API en thread separado
        api_thread = threading.Thread(target=api_poll, daemon=True)
        api_thread.start()

        # Mientras tanto, monitorear SVG en el thread principal
        logger.info(f"{self.prefix} Monitoreando disponibilidad (API + SVG)...")

        # Esperar a que el mapa SVG este cargado
        svg_ready = wait_for_svg_map(self.driver, self.bot_id, timeout=20)

        while not result["found"] and time.time() - start < max_wait:
            # Chequear si el thread de API encontro un error critico
            if result["error"] is not None:
                raise result["error"]

            # Chequear SVG
            if svg_ready:
                try:
                    sectors = scan_popular_sectors(self.driver, self.bot_id)
                    if sectors:
                        best_svg = sectors[0]
                        logger.info(
                            f"{self.prefix} [SVG] Sector disponible: "
                            f"{best_svg['sector_id']} (fill={best_svg['color']})"
                        )

                        # Si la API no encontro nada aun, usar resultado del SVG
                        if not result["found"]:
                            # Intentar obtener nid de la API
                            nid = None
                            try:
                                api_sections = self.api_session.poll_section_availability()
                                if api_sections:
                                    nid = get_section_nid_from_api_response(
                                        api_sections, best_svg["sector_id"]
                                    )
                            except Exception:
                                pass

                            result["data"] = {
                                "sector_id": best_svg["sector_id"],
                                "nid": nid,
                                "element": best_svg["element"],
                                "source": "svg",
                            }
                            result["found"] = True
                            break
                except Exception as e:
                    logger.debug(f"{self.prefix} [SVG] Error scan: {e}")

            time.sleep(1.0 + random.uniform(-0.2, 0.3))

        api_thread.join(timeout=5)
        return result.get("data")

    # ---------------------------------------------------------------
    # PASO 6: Agregar sector al carrito
    # ---------------------------------------------------------------

    def _add_sector_to_cart(self, sector_data: dict) -> None:
        """
        Selecciona el sector en el SVG y agrega al carrito.
        Usa API + UI como fallback.
        """
        sector_id = sector_data["sector_id"]
        nid = sector_data.get("nid")
        element = sector_data.get("element")

        logger.info(f"{self.prefix} Agregando sector {sector_id} (nid={nid}) al carrito")

        # 1. Clickear sector en SVG si tenemos el elemento
        if element:
            try:
                human_click(self.driver, element)
                short_delay()
                take_screenshot(self.driver, self.bot_id, f"click_{sector_id}")
            except Exception:
                # Fallback: click JS
                click_sector_by_js(self.driver, self.bot_id, sector_id)
                short_delay()
        else:
            # Si no tenemos elemento, click via JS
            click_sector_by_js(self.driver, self.bot_id, sector_id)
            short_delay()

        random_delay(1.0, 2.0)

        # 2. Intentar agregar via API si tenemos nid
        api_success = False
        if nid and self.api_session:
            api_success = self.api_session.add_to_cart(nid)
            if api_success:
                logger.info(f"{self.prefix} Sector agregado al carrito via API!")

        # 3. Clickear Continuar en la UI para avanzar
        random_delay(1.0, 2.0)
        click_continue_button(self.driver, self.bot_id)
        random_delay(1.5, 2.5)

        # 4. Si la API no funciono, intentar via UI
        if not api_success:
            add_to_cart_via_ui(self.driver, self.bot_id)

        # 5. Navegar a la pagina de asientos si hay nid
        if nid:
            navigate_to_seats(self.driver, self.bot_id, self.settings.match_id, nid)

        take_screenshot(self.driver, self.bot_id, "cart_added")
        logger.info(f"{self.prefix} Sector {sector_id} en proceso de carrito")


def run_bot_process(bot_id: int, settings_dict: dict) -> dict:
    """
    Funcion entry-point para multiprocessing.
    Reconstruye settings y ejecuta el bot.
    Es una funcion top-level para ser pickleable.

    Args:
        bot_id: ID del bot (1-5)
        settings_dict: Settings serializados como dict

    Returns:
        dict con resultado del bot
    """
    # Configurar logging para este proceso
    _setup_process_logging(bot_id, settings_dict.get("log_level", "INFO"))

    try:
        # Reconstruir settings
        settings = BotSettings()
        settings.match_id = settings_dict.get("match_id", "834")
        settings.delay_min = settings_dict.get("delay_min", 0.8)
        settings.delay_max = settings_dict.get("delay_max", 3.2)
        settings.poll_interval_ms = settings_dict.get("poll_interval_ms", 400)
        settings.dry_run = settings_dict.get("dry_run", True)
        settings.log_level = settings_dict.get("log_level", "INFO")
        settings.socio_tipo = settings_dict.get("socio_tipo", "adherente")
        settings.entrada_tipo = settings_dict.get("entrada_tipo", "generals")

        account = AccountConfig(
            user=settings_dict["accounts"][bot_id - 1]["user"],
            password=settings_dict["accounts"][bot_id - 1]["password"],
            proxy=settings_dict["accounts"][bot_id - 1]["proxy"],
            bot_id=bot_id,
        )

        headless = settings_dict.get("headless", False)
        bot = BotInstance(account, settings, headless=headless)
        return bot.run()

    except Exception as e:
        logger.error(f"[BOT-{bot_id}] Error fatal en proceso: {e}", exc_info=True)
        return {"success": False, "sector": None, "error": str(e), "bot_id": bot_id}


def _setup_process_logging(bot_id: int, log_level: str) -> None:
    """Configura logging individual para el proceso del bot."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, f"bot_{bot_id}_{timestamp}.log")

    # Handler de archivo
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    ))

    # Handler de consola
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        f"[BOT-{bot_id}] %(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S"
    ))

    # Configurar root logger del proceso
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logger.info(f"[BOT-{bot_id}] Logging iniciado: {log_file}")
