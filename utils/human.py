"""
utils/human.py
Simulacion de comportamiento humano: mouse bezier, delays aleatorios, scroll suave.
Reduce la probabilidad de deteccion como bot.
"""

import random
import time
from selenium.webdriver.common.action_chains import ActionChains


def random_delay(min_sec: float = 0.8, max_sec: float = 3.2) -> None:
    """Espera un tiempo aleatorio entre min y max segundos."""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)


def short_delay() -> None:
    """Delay corto entre acciones rapidas (300-800ms)."""
    time.sleep(random.uniform(0.3, 0.8))


def micro_delay() -> None:
    """Micro delay para parecer humano (50-200ms)."""
    time.sleep(random.uniform(0.05, 0.2))


def bezier_point(t: float, p0: tuple, p1: tuple, p2: tuple, p3: tuple) -> tuple:
    """Calcula un punto en una curva de Bezier cubica."""
    x = (
        (1 - t) ** 3 * p0[0]
        + 3 * (1 - t) ** 2 * t * p1[0]
        + 3 * (1 - t) * t ** 2 * p2[0]
        + t ** 3 * p3[0]
    )
    y = (
        (1 - t) ** 3 * p0[1]
        + 3 * (1 - t) ** 2 * t * p1[1]
        + 3 * (1 - t) * t ** 2 * p2[1]
        + t ** 3 * p3[1]
    )
    return (int(x), int(y))


def human_move_to_element(driver, element, steps: int = 0) -> None:
    """
    Mueve el mouse hacia un elemento con curva de Bezier.
    Simula movimiento humano no-lineal.
    """
    if steps == 0:
        steps = random.randint(15, 35)

    # Obtener posicion actual del viewport y del elemento destino
    elem_rect = element.rect
    target_x = elem_rect["x"] + elem_rect["width"] // 2
    target_y = elem_rect["y"] + elem_rect["height"] // 2

    # Punto de inicio aleatorio (simula que el mouse viene de otro lado)
    start_x = random.randint(100, 800)
    start_y = random.randint(100, 600)

    # Puntos de control aleatorios para la curva Bezier
    ctrl1 = (
        start_x + random.randint(-200, 200),
        start_y + random.randint(-150, 150),
    )
    ctrl2 = (
        target_x + random.randint(-100, 100),
        target_y + random.randint(-80, 80),
    )

    actions = ActionChains(driver)

    # Mover por la curva Bezier
    prev_point = (start_x, start_y)
    for i in range(1, steps + 1):
        t = i / steps
        point = bezier_point(t, (start_x, start_y), ctrl1, ctrl2, (target_x, target_y))
        offset_x = point[0] - prev_point[0]
        offset_y = point[1] - prev_point[1]
        if offset_x != 0 or offset_y != 0:
            actions.move_by_offset(offset_x, offset_y)
            actions.pause(random.uniform(0.005, 0.025))
        prev_point = point

    # Finalmente mover al elemento exacto y hacer click
    actions.move_to_element(element)
    actions.pause(random.uniform(0.05, 0.15))
    actions.perform()


def human_click(driver, element) -> None:
    """Click en un elemento con movimiento humano previo."""
    human_move_to_element(driver, element)
    micro_delay()
    element.click()


def smooth_scroll(driver, pixels: int = 300, direction: str = "down") -> None:
    """Scroll suave simulando rueda del mouse."""
    scroll_amount = pixels if direction == "down" else -pixels
    steps = random.randint(3, 8)
    per_step = scroll_amount // steps

    for _ in range(steps):
        driver.execute_script(f"window.scrollBy(0, {per_step})")
        time.sleep(random.uniform(0.05, 0.15))


def random_scroll(driver) -> None:
    """Scroll aleatorio para simular lectura humana."""
    direction = random.choice(["down", "up"])
    pixels = random.randint(100, 500)
    smooth_scroll(driver, pixels, direction)


def human_type(element, text: str) -> None:
    """Escribe texto caracter por caracter con delays humanos."""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.18))


def jitter(base_seconds: float, factor: float = 0.3) -> float:
    """Agrega jitter aleatorio a un tiempo base. Retorna el nuevo valor."""
    jit = base_seconds * random.uniform(-factor, factor)
    return max(0.1, base_seconds + jit)
