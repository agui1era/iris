from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import dotenv_values

from iris import __version__, config_store
from iris.config import ConfigurationError, config_mapping, load_config, sanitized_config

if TYPE_CHECKING:
    from iris.supervisor import MonitoringSupervisor


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="iris-monitor",
        description="Monitoreo semántico multi-cámara RTSP.",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Valida .env, imprime una vista sin secretos y termina.",
    )
    parser.add_argument(
        "--config-db",
        default=None,
        metavar="PATH",
        help=(
            "Ruta al archivo SQLite de configuración. Sobrescribe IRIS_CONFIG_DB "
            "y el valor por defecto data/config.db, tanto para ejecutar el "
            "servicio como para --migrate-env-to-sqlite."
        ),
    )
    parser.add_argument(
        "--dotenv-path",
        default=".env",
        metavar="PATH",
        help="Ruta al archivo .env a leer (por defecto .env).",
    )
    parser.add_argument(
        "--migrate-env-to-sqlite",
        action="store_true",
        help=(
            "Acción de mantenimiento: importa las variables de --dotenv-path al "
            "almacén SQLite de configuración y termina sin iniciar el servicio."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser.parse_args(argv)


def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        raise ConfigurationError(
            f"LOG_LEVEL inválido: {level_name}. Usa DEBUG, INFO, WARNING, ERROR o CRITICAL."
        )
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _install_signal_handlers(service: MonitoringSupervisor) -> None:
    def stop(_signum: int, _frame: Any) -> None:
        logging.getLogger(__name__).info("Señal de apagado recibida.")
        service.request_stop()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)


def _resolved_config_db_path(config_db_path: str | None) -> Path:
    return (
        Path(config_db_path).expanduser()
        if config_db_path is not None
        else Path(os.environ.get("IRIS_CONFIG_DB", "data/config.db")).expanduser()
    )


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)

    if args.migrate_env_to_sqlite:
        dotenv_path = Path(args.dotenv_path).expanduser()
        db_path = _resolved_config_db_path(args.config_db)
        if config_store.is_config_initialized(db_path):
            print(
                "Error: la configuración SQLite ya está inicializada; la migración "
                "one-shot no sobrescribirá cambios vivos.",
                file=sys.stderr,
            )
            return 2
        source = {
            key: value
            for key, value in dotenv_values(dotenv_path).items()
            if isinstance(value, str) and value.strip()
        }
        if not source:
            print(f"No se encontraron variables para importar en {dotenv_path}.")
            return 0
        try:
            candidate = load_config(env=source)
        except ConfigurationError as exc:
            print(f"Error de configuración: {exc}", file=sys.stderr)
            return 2
        canonical = config_mapping(candidate, include_secrets_and_infrastructure=True)
        config_store.initialize_config_mapping(db_path, canonical)
        print(
            f"Se importaron {len(canonical)} variable(s) IRIS validadas "
            f"de {dotenv_path} a {db_path}."
        )
        return 0

    try:
        config = load_config(dotenv_path=args.dotenv_path, config_db_path=args.config_db)
        _configure_logging(config.log_level)
    except ConfigurationError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        return 2

    if args.check_config:
        print(json.dumps(sanitized_config(config), ensure_ascii=False, indent=2))
        return 0

    db_path = _resolved_config_db_path(args.config_db)
    seed_values = config_mapping(config, include_secrets_and_infrastructure=False)
    # La clave editable de DashScope pertenece al control plane persistente.
    # El SQLite queda restringido a 0600 y ningún endpoint devuelve su valor.
    seed_values["DASHSCOPE_API_KEY"] = config.alibaba.api_key
    config_store.initialize_config_mapping(db_path, seed_values)
    stored_mapping = config_store.read_config_mapping(db_path)
    if "DASHSCOPE_API_KEY" not in stored_mapping:
        config_store.mutate_config_mapping(
            db_path,
            values={"DASHSCOPE_API_KEY": config.alibaba.api_key},
        )
    config = load_config(dotenv_path=args.dotenv_path, config_db_path=db_path)

    from iris.alibaba import AlibabaVisionClient
    from iris.service import MonitoringService
    from iris.supervisor import MonitorAlreadyRunning, MonitoringSupervisor

    def generation_factory(generation_config):
        analyzer = AlibabaVisionClient(generation_config.alibaba)
        return MonitoringService(generation_config, analyzer)

    service = MonitoringSupervisor(
        config_db_path=db_path,
        dotenv_path=Path(args.dotenv_path).expanduser(),
        generation_factory=generation_factory,
    )
    _install_signal_handlers(service)
    try:
        service.run()
    except MonitorAlreadyRunning as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        service.request_stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
