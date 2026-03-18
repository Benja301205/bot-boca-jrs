#!/usr/bin/env python3
"""
main.py — Orquestador principal del Bot Boca Socios
Lanza 5 procesos paralelos con multiprocessing, cada uno con proxy y cuenta distintos.
Coordina los resultados y maneja errores globales.

Uso:
    python main.py                          # Usa config de .env (MATCH_ID, etc.)
    python main.py --match-id 834           # Override match ID
    python main.py --bots 3                 # Lanzar solo 3 bots
    python main.py --entrada plateas        # Buscar plateas en vez de generales
    python main.py --headless               # Sin ventana de browser
    python main.py --dry-run                # Modo simulacion (por defecto)
"""

import argparse
import logging
import multiprocessing
import os
import sys
import time
from datetime import datetime

# Agregar raiz del proyecto al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import load_settings
from core.bot_instance import run_bot_process


def main():
    """Entry point del orquestador."""
    args = parse_args()

    # Configurar logging del orquestador
    setup_orchestrator_logging(args.log_level)
    logger = logging.getLogger("orchestrator")

    print_banner()

    # Cargar configuracion
    settings = load_settings()

    # Aplicar overrides de CLI
    if args.match_id:
        settings.match_id = args.match_id
    if args.entrada:
        settings.entrada_tipo = args.entrada
    if args.socio_tipo:
        settings.socio_tipo = args.socio_tipo
    if args.dry_run is not None:
        settings.dry_run = args.dry_run

    num_bots = min(args.bots, len(settings.accounts))
    if num_bots == 0:
        logger.error("No hay cuentas configuradas en .env. Revisa el archivo.")
        sys.exit(1)

    logger.info(f"Lanzando {num_bots} bots para partido {settings.match_id}")
    logger.info(f"Tipo entrada: {settings.entrada_tipo} | Socio: {settings.socio_tipo}")
    logger.info(f"DRY_RUN: {settings.dry_run}")
    logger.info(f"Poll interval: {settings.poll_interval_ms}ms")

    # Serializar settings para pasar a los procesos hijos
    settings_dict = {
        "match_id": settings.match_id,
        "api_base": settings.api_base,
        "delay_min": settings.delay_min,
        "delay_max": settings.delay_max,
        "poll_interval_ms": settings.poll_interval_ms,
        "dry_run": settings.dry_run,
        "log_level": settings.log_level,
        "socio_tipo": settings.socio_tipo,
        "entrada_tipo": settings.entrada_tipo,
        "headless": args.headless,
        "accounts": [
            {"user": acc.user, "password": acc.password, "proxy": acc.proxy}
            for acc in settings.accounts[:num_bots]
        ],
    }

    # --- LANZAR PROCESOS ---
    logger.info("=" * 60)
    logger.info("LANZANDO BOTS EN PARALELO")
    logger.info("=" * 60)

    start_time = time.time()
    results = []

    # Usar multiprocessing.Pool para procesos aislados
    # Cada bot en su propio proceso = aislamiento total (1 falla != todos mueren)
    try:
        with multiprocessing.Pool(processes=num_bots) as pool:
            # Lanzar todos los bots en paralelo
            async_results = []
            for bot_id in range(1, num_bots + 1):
                logger.info(f"Lanzando BOT-{bot_id} (cuenta: {settings_dict['accounts'][bot_id - 1]['user']})")
                ar = pool.apply_async(run_bot_process, args=(bot_id, settings_dict))
                async_results.append((bot_id, ar))

            # Esperar resultados con timeout global (30 minutos)
            timeout_global = 1800
            for bot_id, ar in async_results:
                try:
                    result = ar.get(timeout=timeout_global)
                    results.append(result)
                    _log_bot_result(logger, result)
                except multiprocessing.TimeoutError:
                    logger.error(f"[BOT-{bot_id}] TIMEOUT ({timeout_global}s)")
                    results.append({
                        "success": False,
                        "sector": None,
                        "error": "timeout",
                        "bot_id": bot_id,
                    })
                except Exception as e:
                    logger.error(f"[BOT-{bot_id}] Error obteniendo resultado: {e}")
                    results.append({
                        "success": False,
                        "sector": None,
                        "error": str(e),
                        "bot_id": bot_id,
                    })

    except KeyboardInterrupt:
        logger.warning("Interrupcion por usuario (Ctrl+C). Cerrando bots...")
        print("\n[ORCHESTRATOR] Cerrando procesos... (puede tardar unos segundos)")

    elapsed = time.time() - start_time

    # --- RESUMEN ---
    print_summary(results, elapsed)

    # Retornar codigo de salida
    successes = sum(1 for r in results if r.get("success"))
    return 0 if successes > 0 else 1


def parse_args() -> argparse.Namespace:
    """Parsea argumentos de linea de comandos."""
    parser = argparse.ArgumentParser(
        description="Bot Boca Socios — Compra automatizada de entradas populares/generales",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--match-id", type=str, default=None,
        help="ID del partido (default: .env MATCH_ID)"
    )
    parser.add_argument(
        "--bots", type=int, default=5,
        help="Cantidad de bots a lanzar (default: 5)"
    )
    parser.add_argument(
        "--entrada", type=str, choices=["generals", "plateas"], default=None,
        help="Tipo de entrada a buscar (default: .env ENTRADA_TIPO)"
    )
    parser.add_argument(
        "--socio-tipo", type=str, choices=["adherente", "pleno", "activo"], default=None,
        help="Tipo de socio (default: .env SOCIO_TIPO)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=None,
        help="Modo simulacion (no pagar)"
    )
    parser.add_argument(
        "--no-dry-run", action="store_true", default=False,
        help="Desactivar modo simulacion (PELIGRO: puede pagar)"
    )
    parser.add_argument(
        "--headless", action="store_true", default=False,
        help="Ejecutar browsers sin ventana visible"
    )
    parser.add_argument(
        "--log-level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Nivel de logging"
    )

    args = parser.parse_args()

    # Si --no-dry-run, forzar dry_run=False
    if args.no_dry_run:
        args.dry_run = False

    return args


def setup_orchestrator_logging(log_level: str) -> None:
    """Configura logging para el proceso orquestador."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, f"orchestrator_{timestamp}.log")

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [ORCHESTRATOR] %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    logging.getLogger("orchestrator").info(f"Log del orquestador: {log_file}")


def _log_bot_result(logger, result: dict) -> None:
    """Loguea el resultado de un bot."""
    bot_id = result.get("bot_id", "?")
    if result.get("success"):
        sector = result.get("sector", "desconocido")
        logger.info(f"[BOT-{bot_id}] EXITO! Sector: {sector}")
    else:
        error = result.get("error", "desconocido")
        logger.error(f"[BOT-{bot_id}] FALLO. Error: {error}")


def print_banner():
    """Imprime banner de inicio."""
    print()
    print("=" * 60)
    print("   BOT BOCA SOCIOS — Entradas Populares/Generales")
    print("   Socio Adherente | 5 instancias paralelas")
    print("=" * 60)
    print()


def print_summary(results: list[dict], elapsed: float):
    """Imprime resumen final de todos los bots."""
    print()
    print("=" * 60)
    print("   RESUMEN FINAL")
    print("=" * 60)

    successes = 0
    for r in results:
        bot_id = r.get("bot_id", "?")
        if r.get("success"):
            successes += 1
            sector = r.get("sector", "?")
            paid = r.get("paid", False)
            status = "PAGADO" if paid else "EN CARRITO (sin pagar)"
            print(f"   BOT-{bot_id}: EXITO — Sector {sector} — {status}")
        else:
            error = r.get("error", "desconocido")
            print(f"   BOT-{bot_id}: FALLO — {error}")

    print()
    print(f"   Exitosos: {successes}/{len(results)}")
    print(f"   Tiempo total: {elapsed:.1f} segundos")
    print("=" * 60)
    print()


if __name__ == "__main__":
    # Necesario para multiprocessing en macOS
    multiprocessing.set_start_method("spawn", force=True)
    sys.exit(main())
