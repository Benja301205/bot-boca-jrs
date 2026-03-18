"""
utils/browser.py
Creacion de browser stealth con undetected_chromedriver + selenium-wire.
Login automatico y extraccion de tokens desde localStorage.
"""

import json
import logging
import random
import time

import seleniumwire.undetected_chromedriver as uc

from config.settings import (
    AUTH_STORAGE_KEY,
    URL_HOME,
    USER_AGENTS,
    AccountConfig,
)
from utils.human import human_type, random_delay, short_delay

logger = logging.getLogger(__name__)


def create_stealth_browser(account: AccountConfig, headless: bool = False):
    """
    Crea un browser con undetected_chromedriver + selenium-wire.
    Configura proxy, fingerprint argentino, anti-deteccion.

    Args:
        account: Configuracion de cuenta con proxy
        headless: Si ejecutar sin ventana visible

    Returns:
        driver: Instancia de webdriver configurada
    """
    logger.info(f"[BOT-{account.bot_id}] Creando browser stealth con proxy={account.proxy}")

    # Opciones de selenium-wire para proxy
    sw_options = {}
    if account.proxy:
        sw_options["proxy"] = {
            "http": account.proxy,
            "https": account.proxy,
            "no_proxy": "localhost,127.0.0.1",
        }

    # Opciones de Chrome
    chrome_options = uc.ChromeOptions()

    # User-Agent argentino aleatorio
    ua = random.choice(USER_AGENTS)
    chrome_options.add_argument(f"--user-agent={ua}")

    # Configuracion de idioma/locale argentino
    chrome_options.add_argument("--lang=es-AR")
    chrome_options.add_argument("--accept-lang=es-AR,es;q=0.9")

    # Timezone Argentina
    chrome_options.add_argument("--timezone=America/Argentina/Buenos_Aires")

    # Anti-deteccion adicional
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    chrome_options.add_argument("--disable-popup-blocking")

    # Ventana con tamano realista
    width = random.randint(1280, 1920)
    height = random.randint(800, 1080)
    chrome_options.add_argument(f"--window-size={width},{height}")

    if headless:
        chrome_options.add_argument("--headless=new")

    # Crear driver con undetected_chromedriver + selenium-wire integrado
    # uc.Chrome de seleniumwire.undetected_chromedriver combina ambos
    driver = uc.Chrome(
        seleniumwire_options=sw_options,
        options=chrome_options,
    )

    # Inyectar spoofing de Canvas, WebGL, fonts y timezone via CDP
    _inject_fingerprint_spoofing(driver, account.bot_id)

    logger.info(f"[BOT-{account.bot_id}] Browser creado. UA={ua[:60]}... Ventana={width}x{height}")
    return driver


def _inject_fingerprint_spoofing(driver, bot_id: int) -> None:
    """Inyecta scripts de spoofing para Canvas, WebGL, fonts y timezone."""

    spoofing_js = """
    // Spoofing de Canvas — agrega ruido imperceptible al canvas
    const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {
        const ctx = this.getContext('2d');
        if (ctx) {
            const imageData = ctx.getImageData(0, 0, this.width, this.height);
            for (let i = 0; i < imageData.data.length; i += 4) {
                imageData.data[i] += (Math.random() * 2 - 1) | 0;     // R
                imageData.data[i+1] += (Math.random() * 2 - 1) | 0;   // G
                imageData.data[i+2] += (Math.random() * 2 - 1) | 0;   // B
            }
            ctx.putImageData(imageData, 0, 0);
        }
        return originalToDataURL.apply(this, arguments);
    };

    // Spoofing de WebGL — alterar renderer info
    const getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return 'Google Inc. (Intel)';
        if (param === 37446) return 'ANGLE (Intel, Mesa Intel(R) UHD Graphics, OpenGL 4.6)';
        return getParam.apply(this, arguments);
    };

    // Timezone override — Argentina UTC-3
    const origDateTZ = Intl.DateTimeFormat.prototype.resolvedOptions;
    Intl.DateTimeFormat.prototype.resolvedOptions = function() {
        const result = origDateTZ.apply(this, arguments);
        result.timeZone = 'America/Argentina/Buenos_Aires';
        return result;
    };

    // Navigator overrides
    Object.defineProperty(navigator, 'languages', { get: () => ['es-AR', 'es'] });
    Object.defineProperty(navigator, 'language', { get: () => 'es-AR' });
    Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
    """

    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": spoofing_js})
        logger.debug(f"[BOT-{bot_id}] Fingerprint spoofing inyectado")
    except Exception as e:
        logger.warning(f"[BOT-{bot_id}] No se pudo inyectar spoofing CDP: {e}")
        # Fallback: ejecutar directamente
        try:
            driver.execute_script(spoofing_js)
        except Exception:
            pass


def login(driver, account: AccountConfig) -> bool:
    """
    Realiza login en bocasocios.bocajuniors.com.ar.

    Args:
        driver: Browser driver
        account: Credenciales de la cuenta

    Returns:
        True si el login fue exitoso
    """
    logger.info(f"[BOT-{account.bot_id}] Iniciando login con {account.user}")

    try:
        driver.get(URL_HOME)
        random_delay(2.0, 4.0)

        # Buscar boton de login / iniciar sesion
        # El sitio usa React Native Web, los selectores pueden variar
        login_btn = _find_login_button(driver)
        if login_btn:
            login_btn.click()
            short_delay()

        # Buscar campos de email y password
        # Intentar multiples selectores ya que el framework genera clases dinamicas
        email_input = _find_input(driver, "email")
        if not email_input:
            logger.error(f"[BOT-{account.bot_id}] No se encontro campo de email")
            return False

        password_input = _find_input(driver, "password")
        if not password_input:
            logger.error(f"[BOT-{account.bot_id}] No se encontro campo de password")
            return False

        # Limpiar y escribir con delays humanos
        email_input.clear()
        human_type(email_input, account.user)
        short_delay()

        password_input.clear()
        human_type(password_input, account.password)
        random_delay(0.5, 1.5)

        # Buscar y clickear boton de submit
        submit_btn = _find_submit_button(driver)
        if submit_btn:
            submit_btn.click()
        else:
            # Fallback: Enter en el campo de password
            from selenium.webdriver.common.keys import Keys
            password_input.send_keys(Keys.RETURN)

        # Esperar a que el login se complete (redireccion o cambio de DOM)
        random_delay(3.0, 5.0)

        # Verificar que el login fue exitoso chequeando tokens en localStorage
        tokens = extract_tokens(driver, account.bot_id)
        if tokens:
            logger.info(f"[BOT-{account.bot_id}] Login exitoso! authToken obtenido.")
            return True
        else:
            logger.error(f"[BOT-{account.bot_id}] Login fallido — no se encontraron tokens.")
            return False

    except Exception as e:
        logger.error(f"[BOT-{account.bot_id}] Error durante login: {e}")
        return False


def _find_login_button(driver):
    """Busca el boton de login/iniciar sesion en la pagina principal."""
    selectors = [
        'button[aria-label*="iniciar"]',
        'button[aria-label*="Iniciar"]',
        'a[href*="login"]',
        'a[href*="signin"]',
    ]
    for sel in selectors:
        try:
            elements = driver.find_elements("css selector", sel)
            if elements:
                return elements[0]
        except Exception:
            continue

    # Buscar por texto visible
    try:
        buttons = driver.find_elements("tag name", "button")
        for btn in buttons:
            text = btn.text.lower()
            if "iniciar" in text or "ingresar" in text or "login" in text:
                return btn
    except Exception:
        pass

    return None


def _find_input(driver, input_type: str):
    """Busca un campo input por tipo (email o password)."""
    selectors = [
        f'input[type="{input_type}"]',
        f'input[name="{input_type}"]',
        f'input[autocomplete="{input_type}"]',
        f'input[placeholder*="{input_type}"]',
    ]
    if input_type == "email":
        selectors.extend([
            'input[type="text"][name*="user"]',
            'input[type="text"][name*="email"]',
            'input[placeholder*="mail"]',
            'input[placeholder*="usuario"]',
            'input[autocomplete="username"]',
        ])

    for sel in selectors:
        try:
            elements = driver.find_elements("css selector", sel)
            if elements:
                return elements[0]
        except Exception:
            continue
    return None


def _find_submit_button(driver):
    """Busca el boton de submit del formulario de login."""
    selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
    ]
    for sel in selectors:
        try:
            elements = driver.find_elements("css selector", sel)
            if elements:
                return elements[0]
        except Exception:
            continue

    # Buscar por texto
    try:
        buttons = driver.find_elements("tag name", "button")
        for btn in buttons:
            text = btn.text.lower()
            if any(w in text for w in ["ingresar", "iniciar", "entrar", "login", "enviar"]):
                return btn
    except Exception:
        pass

    return None


def extract_tokens(driver, bot_id: int) -> dict | None:
    """
    Extrae authToken y refreshToken de localStorage.
    Key: boca-secure-storage\\authStore

    Returns:
        dict con 'authToken' y 'refreshToken', o None si no se encuentran
    """
    try:
        # La key en localStorage tiene un backslash literal: boca-secure-storage\authStore
        # En JS, '\a' no es un escape reconocido y se interpreta como 'a' (pierde el \).
        # Hay que escapar el backslash para JS: \\
        js_safe_key = AUTH_STORAGE_KEY.replace("\\", "\\\\")
        raw = driver.execute_script(
            f'return localStorage.getItem("{js_safe_key}");'
        )
        if not raw:
            # Fallback: iterar todas las keys buscando la que contenga "authStore"
            raw = driver.execute_script("""
                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    if (key && key.includes('authStore')) {
                        return localStorage.getItem(key);
                    }
                }
                return null;
            """)

        if not raw:
            logger.warning(f"[BOT-{bot_id}] No se encontro authStore en localStorage")
            return None

        data = json.loads(raw)

        # El store de Zustand guarda state.authToken y state.refreshToken
        # La estructura puede ser { state: { authToken, refreshToken } } o directamente { authToken, refreshToken }
        auth_token = None
        refresh_token = None

        if isinstance(data, dict):
            if "state" in data:
                state = data["state"]
                auth_token = state.get("authToken") or state.get("token")
                refresh_token = state.get("refreshToken")
            else:
                auth_token = data.get("authToken") or data.get("token")
                refresh_token = data.get("refreshToken")

        if auth_token:
            logger.info(f"[BOT-{bot_id}] Tokens extraidos: auth={auth_token[:20]}...")
            return {
                "authToken": auth_token,
                "refreshToken": refresh_token,
            }
        else:
            logger.warning(f"[BOT-{bot_id}] authToken no encontrado en el store. Keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
            return None

    except json.JSONDecodeError as e:
        logger.error(f"[BOT-{bot_id}] Error parseando authStore JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"[BOT-{bot_id}] Error extrayendo tokens: {e}")
        return None


def take_screenshot(driver, bot_id: int, name: str) -> str:
    """Guarda screenshot con timestamp. Retorna el path del archivo."""
    import os
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"screenshots/bot_{bot_id}_{name}_{timestamp}.png"
    filepath = os.path.join(os.path.dirname(__file__), "..", filename)

    try:
        driver.save_screenshot(filepath)
        logger.info(f"[BOT-{bot_id}] Screenshot guardado: {filename}")
        return filepath
    except Exception as e:
        logger.error(f"[BOT-{bot_id}] Error guardando screenshot: {e}")
        return ""


def close_browser(driver, bot_id: int) -> None:
    """Cierra el browser de forma segura."""
    try:
        driver.quit()
        logger.info(f"[BOT-{bot_id}] Browser cerrado.")
    except Exception as e:
        logger.warning(f"[BOT-{bot_id}] Error cerrando browser: {e}")
