"""
utils/api.py
Sesion de API para polling de disponibilidad, fechas de apertura, y operaciones de carrito.
Usa requests (sync) con headers Bearer + Device:web.
"""

import logging
import time
from datetime import datetime
from typing import Any

import requests

from config.settings import (
    API_BASE,
    EP_MATCHES_PLUS,
    EP_SECTION_AVAILABILITY,
    EP_SHOPPING_CART,
    EP_SHOPPING_CART_ITEM,
    SECTOR_PRIORITY,
    BotSettings,
)
from utils.human import jitter

logger = logging.getLogger(__name__)


class ApiSession:
    """
    Sesion autenticada contra la API de Boca Socios.
    Maneja headers, tokens, retry y backoff.
    """

    def __init__(self, bot_id: int, auth_token: str, refresh_token: str | None = None,
                 proxy: str = "", settings: BotSettings | None = None):
        self.bot_id = bot_id
        self.auth_token = auth_token
        self.refresh_token = refresh_token
        self.proxy = proxy
        self.settings = settings or BotSettings()
        self.base_url = self.settings.api_base
        self.prefix = f"[BOT-{bot_id}][API]"

        # Crear sesion de requests con proxy
        self.session = requests.Session()
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}

        # Headers base (igual que el browser)
        self.session.headers.update({
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
            "Device": "web",
            "Accept": "application/json",
            "Accept-Language": "es-AR,es;q=0.9",
        })

        # Estado de backoff por rate limit
        self._backoff_sec = 0.0
        self._consecutive_errors = 0
        self.MAX_RETRIES = 3

    def update_token(self, new_token: str) -> None:
        """Actualiza el token de autorizacion."""
        self.auth_token = new_token
        self.session.headers["Authorization"] = f"Bearer {new_token}"
        logger.info(f"{self.prefix} Token actualizado")

    # ---------------------------------------------------------------
    # Fechas de apertura
    # ---------------------------------------------------------------

    def get_opening_dates(self) -> dict[str, Any] | None:
        """
        POST /event/matches/plus para obtener fechas de apertura.
        Retorna el dict del partido con campos de purchase, o None si falla.
        """
        url = f"{self.base_url}{EP_MATCHES_PLUS}"
        payload = {
            "abonado": False,
            "socioTipo": self.settings.socio_tipo,
            "familiarAbonado": False,
            "tieneAbonoDiscapacitado": False,
        }

        try:
            resp = self._post(url, json=payload)
            if resp and resp.status_code == 200:
                data = resp.json()
                # Buscar el partido por match_id
                matches = data if isinstance(data, list) else data.get("matches", data.get("data", []))
                if isinstance(matches, list):
                    for match in matches:
                        match_id = str(match.get("id", match.get("matchId", "")))
                        if match_id == self.settings.match_id:
                            logger.info(f"{self.prefix} Partido encontrado: {match.get('title', match_id)}")
                            return match
                # Si no es lista, puede ser el objeto directo
                return data
            else:
                logger.warning(f"{self.prefix} get_opening_dates status={resp.status_code if resp else 'None'}")
                return None
        except Exception as e:
            logger.error(f"{self.prefix} Error obteniendo fechas: {e}")
            return None

    def get_adherente_opening_time(self) -> datetime | None:
        """
        Obtiene la fecha de apertura para generales adherentes.
        Campos: fechaGeneralesAdherente o fechaPlateaAdherente segun entrada_tipo.
        """
        match_data = self.get_opening_dates()
        if not match_data:
            return None

        # Navegar a purchase.fechaGeneralesAdherente
        purchase = match_data.get("purchase", match_data)

        field_map = {
            "generals": "fechaGeneralesAdherente",
            "plateas": "fechaPlateaAdherente",
        }
        field_name = field_map.get(self.settings.entrada_tipo, "fechaGeneralesAdherente")
        fecha_str = purchase.get(field_name)

        if not fecha_str:
            # Intentar campo alternativo
            for key in ["fechaGeneralesAdherente", "fechaPlateaAdherente"]:
                fecha_str = purchase.get(key)
                if fecha_str:
                    break

        if fecha_str:
            try:
                # Parsear ISO 8601 (puede venir con o sin timezone)
                fecha_str = fecha_str.replace("Z", "+00:00")
                opening = datetime.fromisoformat(fecha_str)
                logger.info(f"{self.prefix} Apertura {field_name}: {opening}")
                return opening
            except ValueError as e:
                logger.error(f"{self.prefix} Error parseando fecha '{fecha_str}': {e}")

        logger.warning(f"{self.prefix} No se encontro fecha de apertura adherente")
        return None

    # ---------------------------------------------------------------
    # Polling de disponibilidad de sectores
    # ---------------------------------------------------------------

    def poll_section_availability(self) -> list[dict] | None:
        """
        GET /event/{matchId}/seat/section/availability
        Retorna lista de secciones con su disponibilidad.
        Cada seccion: { codigo, nid, activa, hayDisponibilidad, ... }
        """
        url = f"{self.base_url}{EP_SECTION_AVAILABILITY.format(match_id=self.settings.match_id)}"

        try:
            resp = self._get(url)
            if resp and resp.status_code == 200:
                data = resp.json()
                sections = data if isinstance(data, list) else data.get("secciones", data.get("sections", []))
                self._consecutive_errors = 0
                self._backoff_sec = 0.0
                return sections
            elif resp and resp.status_code == 403:
                error_data = resp.json() if resp.content else {}
                error_type = error_data.get("errorType", "")
                if "invalidQueueId" in str(error_type) or "invalidQueueId" in resp.text:
                    logger.error(f"{self.prefix} 403 invalidQueueId! Necesita nuevo proxy/sesion.")
                    raise InvalidQueueError("invalidQueueId detectado")
                logger.warning(f"{self.prefix} 403 Forbidden: {resp.text[:200]}")
                return None
            elif resp and resp.status_code == 429:
                self._handle_rate_limit()
                return None
            else:
                logger.warning(f"{self.prefix} poll_availability status={resp.status_code if resp else 'None'}")
                return None
        except InvalidQueueError:
            raise
        except Exception as e:
            logger.error(f"{self.prefix} Error polling availability: {e}")
            self._consecutive_errors += 1
            return None

    def find_available_popular_sectors(self) -> list[dict]:
        """
        Hace polling y filtra solo los sectores Popular disponibles.
        Los ordena segun SECTOR_PRIORITY.
        Retorna lista de { codigo, nid, hayDisponibilidad }.
        """
        sections = self.poll_section_availability()
        if not sections:
            return []

        # Filtrar POP con disponibilidad
        available = []
        for sec in sections:
            codigo = sec.get("codigo", "")
            if codigo.startswith("POP") and sec.get("hayDisponibilidad", False):
                available.append(sec)
                logger.info(f"{self.prefix} Sector disponible: {codigo} (nid={sec.get('nid')})")

        if not available:
            return []

        # Ordenar segun prioridad
        def priority_key(sec):
            codigo = sec.get("codigo", "")
            try:
                return SECTOR_PRIORITY.index(codigo)
            except ValueError:
                return len(SECTOR_PRIORITY)  # Al final si no esta en la lista

        available.sort(key=priority_key)
        return available

    # ---------------------------------------------------------------
    # Carrito
    # ---------------------------------------------------------------

    def add_to_cart(self, section_nid: int) -> bool:
        """
        POST /member/shoppingCart/item para agregar un sector al carrito.
        """
        url = f"{self.base_url}{EP_SHOPPING_CART_ITEM}"
        payload = {"sectionNid": section_nid}

        try:
            resp = self._post(url, json=payload)
            if resp and resp.status_code in (200, 201):
                logger.info(f"{self.prefix} Sector {section_nid} agregado al carrito!")
                return True
            else:
                logger.error(f"{self.prefix} Error agregando al carrito: status={resp.status_code if resp else 'None'}")
                return False
        except Exception as e:
            logger.error(f"{self.prefix} Error add_to_cart: {e}")
            return False

    def get_cart(self) -> dict | None:
        """GET /member/shoppingCart — obtener estado actual del carrito."""
        url = f"{self.base_url}{EP_SHOPPING_CART}"
        try:
            resp = self._get(url)
            if resp and resp.status_code == 200:
                return resp.json()
            return None
        except Exception as e:
            logger.error(f"{self.prefix} Error get_cart: {e}")
            return None

    # ---------------------------------------------------------------
    # Helpers HTTP con retry
    # ---------------------------------------------------------------

    def _get(self, url: str, **kwargs) -> requests.Response | None:
        """GET con retry y manejo de errores."""
        return self._request("GET", url, **kwargs)

    def _post(self, url: str, **kwargs) -> requests.Response | None:
        """POST con retry y manejo de errores."""
        return self._request("POST", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response | None:
        """Request generico con retry, backoff y manejo de errores."""
        if self._backoff_sec > 0:
            logger.debug(f"{self.prefix} Backoff {self._backoff_sec:.1f}s antes de request")
            time.sleep(self._backoff_sec)

        for attempt in range(self.MAX_RETRIES):
            try:
                resp = self.session.request(method, url, timeout=10, **kwargs)

                if resp.status_code == 429:
                    self._handle_rate_limit()
                    continue

                return resp

            except requests.exceptions.Timeout:
                logger.warning(f"{self.prefix} Timeout en {method} {url} (intento {attempt + 1})")
                time.sleep(jitter(1.0))
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"{self.prefix} ConnectionError: {e} (intento {attempt + 1})")
                time.sleep(jitter(2.0))
            except Exception as e:
                logger.error(f"{self.prefix} Error inesperado: {e}")
                break

        return None

    def _handle_rate_limit(self) -> None:
        """Backoff exponencial con jitter para 429 Rate Limit."""
        self._consecutive_errors += 1
        # 1s -> 2s -> 4s -> 8s con jitter
        base = min(2 ** self._consecutive_errors, 8)
        self._backoff_sec = jitter(base, factor=0.5)
        logger.warning(f"{self.prefix} Rate limit 429! Backoff {self._backoff_sec:.1f}s")
        time.sleep(self._backoff_sec)


class InvalidQueueError(Exception):
    """Error cuando el backend devuelve 403 invalidQueueId."""
    pass
