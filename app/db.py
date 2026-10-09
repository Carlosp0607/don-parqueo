"""Conexión a PostgreSQL y utilidades para consultar.

Todas las consultas van parametrizadas (%s), nunca con texto pegado:
así se evita la inyección SQL.
"""
import datetime as dt
import logging
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import bcrypt
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app import config

log = logging.getLogger("db")

# prepare_threshold=None: sin sentencias preparadas, para que funcione detrás
# del pooler de Supabase.
pool = ConnectionPool(
    config.DATABASE_URL,
    min_size=1,
    max_size=10,
    open=False,
    kwargs={"row_factory": dict_row, "prepare_threshold": None},
)


def abrir():
    pool.open(wait=True, timeout=30)


def cerrar():
    pool.close()


def consultar(sql, params=()):
    """Devuelve todas las filas como lista de diccionarios."""
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def uno(sql, params=()):
    """Devuelve la primera fila o None."""
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchone()


def ejecutar(sql, params=()):
    """Ejecuta un INSERT/UPDATE/DELETE y devuelve las filas afectadas."""
    with pool.connection() as conn:
        return conn.execute(sql, params).rowcount


@contextmanager
def transaccion():
    """Bloque atómico: o se guarda todo o no se guarda nada."""
    with pool.connection() as conn:
        with conn.transaction():
            yield conn


# ---------------------------------------------------------------------------
# Formato de salida: el frontend se escribió para la API de Node.js, así que
# las fechas salen en UTC con la "Z" al final y los decimales como texto,
# igual que los devolvía mysql2.
# ---------------------------------------------------------------------------
def a_json(valor):
    if isinstance(valor, dt.datetime):
        return valor.strftime("%Y-%m-%dT%H:%M:%S.") + f"{valor.microsecond // 1000:03d}Z"
    if isinstance(valor, dt.date):
        return valor.isoformat() + "T00:00:00.000Z"
    if isinstance(valor, dt.time):
        return valor.strftime("%H:%M:%S")
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, (bytes, memoryview)):
        return None  # los binarios (logo, QR) se sirven por su propio endpoint
    if isinstance(valor, dict):
        return {k: a_json(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [a_json(v) for v in valor]
    return valor


def fila(d):
    return None if d is None else a_json(dict(d))


def filas(lista):
    return [a_json(dict(d)) for d in lista]


# ---------------------------------------------------------------------------
# Migración al arrancar. Idempotente:
#   - Base vacía   -> aplica schema.sql.
#   - Ya existe    -> no hace nada.
# Nunca borra datos.
# ---------------------------------------------------------------------------
ESQUEMA = Path(__file__).resolve().parent.parent / "schema.sql"


def migrar_si_hace_falta():
    try:
        with pool.connection() as conn:
            existe = conn.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = 'empresas'"
            ).fetchone()
            if not existe:
                log.info("[migrate] Base vacía. Aplicando esquema...")
                conn.execute(ESQUEMA.read_text(encoding="utf-8"))
                conn.commit()

            hay_usuarios = conn.execute("SELECT COUNT(*) AS n FROM usuarios").fetchone()["n"]
            if hay_usuarios == 0 and config.ADMIN_INICIAL_PASSWORD:
                clave = bcrypt.hashpw(config.ADMIN_INICIAL_PASSWORD.encode(), bcrypt.gensalt()).decode()
                conn.execute(
                    "INSERT INTO usuarios (id_empresa, nombre, usuario_login, contrasena, rol) "
                    "VALUES (1, 'Administrador', 'admin', %s, 'admin')",
                    (clave,),
                )
                conn.commit()
                log.info("[migrate] Usuario admin creado para la empresa 1.")
    except Exception as e:  # la migración nunca debe tumbar el servidor
        log.error("[migrate] Falló: %s", e)
