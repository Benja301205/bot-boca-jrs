"""
utils/cart.py
Gestion del carrito de compras: agregar sector, avanzar pasos, y PAUSA manual obligatoria.
NUNCA completa el pago automaticamente.
"""

import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from config.settings import (
    URL_SEATS,
    BotSettings,
)
from utils.human import random_delay, short_delay, human_click
from utils.browser import take_screenshot

logger = logging.getLogger(__name__)


def navigate_to_seats(driver, bot_id: int, match_id: str, section_nid: int) -> bool:
    """
    Navega a la pantalla de seleccion de asientos del sector.
    URL: /matches/{matchId}/plateas/seats/{sectionNid}
    """
    url = URL_SEATS.format(match_id=match_id, section_nid=section_nid)
    logger.info(f"[BOT-{bot_id}] Navegando a asientos: {url}")

    try:
        driver.get(url)
        random_delay(2.0, 3.5)

        # Verificar que la pagina cargo
        WebDriverWait(driver, 15).until(
            lambda d: "seats" in d.current_url or "generals" in d.current_url or "plateas" in d.current_url
        )

        take_screenshot(driver, bot_id, "seats_loaded")
        logger.info(f"[BOT-{bot_id}] Pantalla de asientos cargada")
        return True

    except Exception as e:
        logger.error(f"[BOT-{bot_id}] Error navegando a asientos: {e}")
        return False


def click_continue_button(driver, bot_id: int) -> bool:
    """
    Clickea el boton "Continuar" para avanzar en el wizard de compra.
    Busca multiples selectores posibles.
    """
    selectors = [
        'button[data-testid$="-generals-continue"]',
        'button[data-testid$="-plateas-continue"]',
        'button[data-testid$="-continue"]',
    ]

    for sel in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            for elem in elements:
                if elem.is_displayed() and elem.is_enabled():
                    text = elem.text.strip().lower()
                    # Solo clickear si el boton dice "continuar" o "obtener"
                    if text and ("continuar" in text or "obtener" in text or "continue" in text):
                        logger.info(f"[BOT-{bot_id}] Clickeando boton: '{elem.text}' ({sel})")
                        human_click(driver, elem)
                        short_delay()
                        return True
        except Exception:
            continue

    # Fallback: buscar por texto visible "Continuar"
    try:
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            if btn.is_displayed() and btn.is_enabled():
                text = btn.text.strip().lower()
                if "continuar" in text or "obtener" in text:
                    logger.info(f"[BOT-{bot_id}] Clickeando boton (texto): '{btn.text}'")
                    human_click(driver, btn)
                    short_delay()
                    return True
    except Exception:
        pass

    logger.warning(f"[BOT-{bot_id}] No se encontro boton Continuar")
    return False


def add_to_cart_via_ui(driver, bot_id: int) -> bool:
    """
    Agrega al carrito via interaccion con la UI (click en botones).
    Usado como complemento/fallback de la API.
    """
    try:
        # Buscar boton de agregar al carrito
        add_selectors = [
            'button[data-testid*="add"]',
            'button[data-testid*="cart"]',
            'button[aria-label*="agregar"]',
        ]

        for sel in add_selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            for elem in elements:
                if elem.is_displayed() and elem.is_enabled():
                    human_click(driver, elem)
                    short_delay()
                    logger.info(f"[BOT-{bot_id}] Item agregado al carrito via UI")
                    return True

        # Fallback: buscar boton por texto
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            text = btn.text.strip().lower()
            if btn.is_displayed() and btn.is_enabled():
                if any(w in text for w in ["agregar", "add", "seleccionar", "elegir"]):
                    human_click(driver, btn)
                    short_delay()
                    logger.info(f"[BOT-{bot_id}] Carrito via UI (texto): '{btn.text}'")
                    return True

        logger.warning(f"[BOT-{bot_id}] No se encontro boton de agregar al carrito en UI")
        return False

    except Exception as e:
        logger.error(f"[BOT-{bot_id}] Error agregando al carrito via UI: {e}")
        return False


def advance_to_confirmation(driver, bot_id: int, match_id: str, max_steps: int = 5) -> bool:
    """
    Avanza por los pasos del wizard hasta llegar a la pantalla de confirmacion/pago.
    Hace click en "Continuar" hasta max_steps veces.
    """
    logger.info(f"[BOT-{bot_id}] Avanzando hacia confirmacion (max {max_steps} pasos)")

    for step in range(max_steps):
        current_url = driver.current_url

        # Si ya estamos en confirmacion, parar
        if "confirmation" in current_url:
            logger.info(f"[BOT-{bot_id}] Llegamos a pantalla de confirmacion!")
            return True

        # Intentar clickear Continuar
        clicked = click_continue_button(driver, bot_id)
        if not clicked:
            # Tal vez ya estamos en el ultimo paso
            logger.info(f"[BOT-{bot_id}] No hay boton Continuar en paso {step + 1}. URL: {current_url}")
            break

        random_delay(1.5, 3.0)

        # Verificar si la URL cambio (avanzamos)
        new_url = driver.current_url
        if new_url == current_url:
            logger.warning(f"[BOT-{bot_id}] URL no cambio despues de click en paso {step + 1}")
            # Intentar una vez mas con delay
            random_delay(1.0, 2.0)

    take_screenshot(driver, bot_id, "pre_confirmation")
    return "confirmation" in driver.current_url


def manual_payment_pause(driver, bot_id: int, sector_id: str, settings: BotSettings) -> bool:
    """
    PAUSA OBLIGATORIA antes del pago.
    Muestra info al usuario y espera confirmacion manual via input().

    NUNCA se salta este paso. dry_run=True impide el pago incluso si el usuario dice 'y'.

    Returns:
        True si el usuario confirmo y dry_run=False
    """
    # Screenshot previo al pago
    take_screenshot(driver, bot_id, "pre_payment")

    print("\n" + "=" * 70)
    print(f"  BOT-{bot_id} | SECTOR CONSEGUIDO: {sector_id}")
    print(f"  URL actual: {driver.current_url}")
    print(f"  DRY_RUN: {settings.dry_run}")
    print("=" * 70)

    if settings.dry_run:
        print(f"  [DRY_RUN] Modo simulacion. NO se completara el pago.")
        print(f"  Para pagar de verdad, setear DRY_RUN=false en .env")
        print("=" * 70 + "\n")
        logger.info(f"[BOT-{bot_id}] DRY_RUN activo. Pago NO completado. Sector: {sector_id}")
        return False

    # Pedir confirmacion manual — ESTO ES OBLIGATORIO
    print(f"\n  ATENCION: Vas a pagar con la cuenta del BOT-{bot_id}")
    print(f"  Revisa la pantalla del browser antes de confirmar.\n")

    try:
        respuesta = input(f"  BOT-{bot_id} | Confirmar y pagar? (y/n): ").strip().lower()
    except EOFError:
        # Si no hay stdin (ej: ejecutando en background)
        logger.warning(f"[BOT-{bot_id}] Sin stdin disponible. Pago NO completado.")
        return False

    if respuesta == "y":
        logger.info(f"[BOT-{bot_id}] Usuario confirmo pago para sector {sector_id}")
        take_screenshot(driver, bot_id, "payment_confirmed")
        return True
    else:
        logger.info(f"[BOT-{bot_id}] Usuario cancelo pago. Sector {sector_id} en carrito.")
        print(f"  Pago cancelado. El sector queda en el carrito.")
        return False


def verify_cart_has_items(driver, bot_id: int) -> bool:
    """Verifica que el carrito tenga al menos un item."""
    try:
        # Buscar indicador de carrito con items
        # El boton Continuar esta habilitado solo si hay items
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            text = btn.text.strip().lower()
            if "continuar" in text and btn.is_enabled():
                return True

        # Verificar via JS si hay items en el DOM del carrito
        has_items = driver.execute_script("""
            const cartItems = document.querySelectorAll('[data-testid*="cart-item"], [class*="cart-item"]');
            return cartItems.length > 0;
        """)
        return bool(has_items)

    except Exception:
        return False
