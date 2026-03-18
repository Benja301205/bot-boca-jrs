"""
utils/svg.py
Deteccion y manipulacion del mapa SVG del estadio.
Detecta colores de fill, identifica sectores POP disponibles, y clickea con prioridad.
"""

import logging
import time
import random
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from config.settings import (
    COLOR_DISPONIBLE,
    SEL_SVG_MAP,
    SECTOR_PRIORITY,
)
from utils.human import human_click, short_delay

logger = logging.getLogger(__name__)


def wait_for_svg_map(driver, bot_id: int, timeout: int = 30) -> bool:
    """
    Espera a que el mapa SVG del estadio se cargue en el DOM.

    Returns:
        True si el mapa se cargo correctamente
    """
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, SEL_SVG_MAP))
        )
        logger.info(f"[BOT-{bot_id}] Mapa SVG cargado")
        # Esperar un poco mas para que los estilos se apliquen
        short_delay()
        return True
    except Exception as e:
        logger.error(f"[BOT-{bot_id}] Timeout esperando mapa SVG: {e}")
        return False


def get_sector_fill_color(driver, sector_id: str) -> str | None:
    """
    Obtiene el color fill del primer path de un sector SVG.

    Args:
        driver: Browser driver
        sector_id: ID del sector sin prefijo 'seccion-' (ej: 'POP2S_1_')

    Returns:
        Color hex del fill (ej: '#3FBF74') o None si no se encuentra
    """
    try:
        # Buscar el grupo SVG del sector
        selector = f'[id^="seccion-{sector_id}"] path:first-child'
        elements = driver.find_elements(By.CSS_SELECTOR, selector)

        if not elements:
            # Intentar con el grupo completo
            selector = f'#seccion-{sector_id} path'
            elements = driver.find_elements(By.CSS_SELECTOR, selector)

        if elements:
            # Obtener fill del primer path
            fill = elements[0].get_attribute("fill")
            if not fill:
                # Intentar via computed style
                fill = driver.execute_script(
                    "return window.getComputedStyle(arguments[0]).fill;",
                    elements[0]
                )
                # Convertir rgb() a hex si es necesario
                if fill and fill.startswith("rgb"):
                    fill = _rgb_to_hex(fill)
            return fill

        return None
    except Exception as e:
        logger.debug(f"Error obteniendo fill de {sector_id}: {e}")
        return None


def scan_popular_sectors(driver, bot_id: int) -> list[dict]:
    """
    Escanea todos los sectores POP del mapa SVG y retorna los disponibles.

    Returns:
        Lista de dicts: [{ 'sector_id': 'POP2S_1_', 'color': '#3FBF74', 'element': WebElement }]
    """
    available = []

    for sector_id in SECTOR_PRIORITY:
        color = get_sector_fill_color(driver, sector_id)
        if color:
            is_available = _is_color_available(color)
            logger.debug(f"[BOT-{bot_id}] Sector {sector_id}: fill={color} disponible={is_available}")

            if is_available:
                # Buscar el elemento clickeable
                element = _find_sector_element(driver, sector_id)
                if element:
                    available.append({
                        "sector_id": sector_id,
                        "color": color,
                        "element": element,
                    })

    # Tambien escanear sectores POP que no esten en la lista de prioridad
    try:
        all_pop = driver.find_elements(By.CSS_SELECTOR, '[id^="seccion-POP"]')
        known_ids = set(SECTOR_PRIORITY)
        for elem in all_pop:
            elem_id = elem.get_attribute("id") or ""
            sector_id = elem_id.replace("seccion-", "")
            if sector_id and sector_id not in known_ids:
                color = get_sector_fill_color(driver, sector_id)
                if color and _is_color_available(color):
                    available.append({
                        "sector_id": sector_id,
                        "color": color,
                        "element": elem,
                    })
    except Exception:
        pass

    if available:
        logger.info(f"[BOT-{bot_id}] Sectores POP disponibles: {[s['sector_id'] for s in available]}")
    else:
        logger.debug(f"[BOT-{bot_id}] Ningun sector POP disponible en el SVG")

    return available


def click_best_sector(driver, bot_id: int, available_sectors: list[dict]) -> str | None:
    """
    Clickea el mejor sector disponible segun prioridad.

    Args:
        available_sectors: Lista ordenada de sectores disponibles

    Returns:
        sector_id del sector clickeado, o None si fallo
    """
    if not available_sectors:
        return None

    best = available_sectors[0]
    sector_id = best["sector_id"]
    element = best["element"]

    logger.info(f"[BOT-{bot_id}] Clickeando sector: {sector_id} (color={best['color']})")

    try:
        # Intentar click humano primero
        try:
            human_click(driver, element)
        except Exception:
            # Fallback: click via JavaScript (mas confiable en SVG)
            driver.execute_script("arguments[0].click();", element)

        short_delay()
        logger.info(f"[BOT-{bot_id}] Sector {sector_id} clickeado exitosamente!")
        return sector_id

    except Exception as e:
        logger.error(f"[BOT-{bot_id}] Error clickeando sector {sector_id}: {e}")

        # Intentar con el siguiente sector disponible
        if len(available_sectors) > 1:
            logger.info(f"[BOT-{bot_id}] Intentando con siguiente sector...")
            return click_best_sector(driver, bot_id, available_sectors[1:])

        return None


def click_sector_by_js(driver, bot_id: int, sector_id: str) -> bool:
    """
    Click en un sector SVG via JavaScript puro (fallback).
    Dispara el evento click en el grupo del sector.
    """
    try:
        js_code = f"""
        const sector = document.querySelector('#seccion-{sector_id}');
        if (sector) {{
            const event = new MouseEvent('click', {{
                bubbles: true,
                cancelable: true,
                view: window
            }});
            sector.dispatchEvent(event);
            return true;
        }}
        return false;
        """
        result = driver.execute_script(js_code)
        if result:
            logger.info(f"[BOT-{bot_id}] Click JS en sector {sector_id} exitoso")
        else:
            logger.warning(f"[BOT-{bot_id}] Sector {sector_id} no encontrado en DOM para click JS")
        return bool(result)
    except Exception as e:
        logger.error(f"[BOT-{bot_id}] Error click JS sector {sector_id}: {e}")
        return False


def get_section_nid_from_api_response(sections: list[dict], sector_id: str) -> int | None:
    """
    Busca el nid de un sector en la respuesta de la API de availability.

    Args:
        sections: Lista de secciones de la API
        sector_id: Codigo del sector (ej: 'POP2S_1_')

    Returns:
        nid numerico del sector, o None
    """
    for sec in sections:
        if sec.get("codigo") == sector_id:
            return sec.get("nid")
    return None


def monitor_svg_availability(driver, bot_id: int, timeout: int = 300, poll_sec: float = 1.0) -> dict | None:
    """
    Monitorea el mapa SVG hasta encontrar un sector POP disponible.
    Loop de polling con timeout.

    Returns:
        Dict del primer sector disponible, o None si timeout
    """
    start = time.time()
    logger.info(f"[BOT-{bot_id}] Iniciando monitoreo SVG (timeout={timeout}s)")

    while time.time() - start < timeout:
        sectors = scan_popular_sectors(driver, bot_id)
        if sectors:
            return sectors[0]

        time.sleep(poll_sec + random.uniform(-0.2, 0.2))

    logger.warning(f"[BOT-{bot_id}] Timeout monitoreando SVG ({timeout}s)")
    return None


# ---------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------

def _is_color_available(color: str) -> bool:
    """Determina si un color de fill indica disponibilidad."""
    if not color:
        return False
    color = color.upper().strip()
    # Verde = disponible
    if color == COLOR_DISPONIBLE.upper():
        return True
    # Tambien aceptar variantes de verde
    if color.startswith("#3F") or color.startswith("#40"):
        return True
    return False


def _find_sector_element(driver, sector_id: str):
    """Encuentra el elemento clickeable de un sector SVG."""
    selectors = [
        f"#seccion-{sector_id}",
        f'[id="seccion-{sector_id}"]',
        f'g[id="seccion-{sector_id}"]',
    ]
    for sel in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            if elements:
                return elements[0]
        except Exception:
            continue
    return None


def _rgb_to_hex(rgb_str: str) -> str:
    """Convierte 'rgb(63, 191, 116)' a '#3FBF74'."""
    try:
        rgb_str = rgb_str.strip()
        if rgb_str.startswith("rgb"):
            nums = rgb_str.split("(")[1].split(")")[0]
            r, g, b = [int(x.strip()) for x in nums.split(",")]
            return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        pass
    return rgb_str
