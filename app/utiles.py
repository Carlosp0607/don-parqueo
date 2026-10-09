"""Funciones de apoyo compartidas por los routers."""
import datetime as dt
import math
import re

from fastapi import Request

# Hora actual en UTC, escrita en SQL. Todas las fechas del sistema se guardan
# en UTC sin zona; así no dependen de la zona horaria de la sesión de la base.
AHORA = "(now() AT TIME ZONE 'utc')"
HOY = f"({AHORA})::date"

FECHA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


async def cuerpo_json(request: Request) -> dict:
    """Dependencia: el cuerpo JSON de la petición, o {} si no viene o no es un objeto."""
    try:
        datos = await request.json()
    except Exception:
        return {}
    return datos if isinstance(datos, dict) else {}


def ahora_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def hoy_utc() -> dt.date:
    return ahora_utc().date()


def entero(valor, minimo=0, maximo=100_000, defecto=0) -> int:
    """Convierte a entero acotado. Lo que no sea número devuelve el valor por defecto."""
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return defecto
    if math.isnan(n) or math.isinf(n):
        return defecto
    return max(minimo, min(maximo, int(n)))


def numero(valor, defecto=0.0) -> float:
    """Equivale a Number() de JavaScript para los casos que usa el sistema."""
    if valor is None or valor == "":
        return defecto
    try:
        return float(valor)
    except (TypeError, ValueError):
        return math.nan


def como_bool(valor) -> bool:
    if isinstance(valor, str):
        return valor.strip().lower() in ("1", "true", "si", "sí", "on", "activo")
    return bool(valor)


def redondear(valor: float) -> int:
    """Redondeo comercial (0.5 sube), igual que Math.round."""
    return int(math.floor(valor + 0.5))


def sumar_meses(fecha: dt.date, meses: int) -> dt.date:
    """Suma meses como setMonth() de JavaScript: si el día no existe, se pasa al mes siguiente."""
    total = fecha.year * 12 + (fecha.month - 1) + meses
    anio, mes = divmod(total, 12)
    return dt.date(anio, mes + 1, 1) + dt.timedelta(days=fecha.day - 1)


def texto_like(valor: str) -> str:
    """Patrón para LIKE con los comodines del usuario escapados."""
    return "%" + re.sub(r"([%_\\])", r"\\\1", valor) + "%"
