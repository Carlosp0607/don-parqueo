"""Turnos de caja: apertura con base, cierre con arqueo e historial."""
import logging
import re

from fastapi import APIRouter, Depends, Query

from app import db
from app.seguridad import ApiError, Usuario, usuario_actual
from app.utiles import AHORA, FECHA_ISO, cuerpo_json

router = APIRouter(prefix="/api/turnos", tags=["turnos"])
log = logging.getLogger("turnos")


def parsear_pesos(valor):
    """Pesos colombianos enteros. Acepta 50000, "50000", "50.000", "$ 50.000".
    Rechaza decimales: la caja se cuadra en pesos enteros. Devuelve None si no sirve."""
    if valor is None or valor == "":
        return 0
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        if valor < 0 or valor != valor or float(valor) != int(valor):
            return None
        return int(valor)

    texto = re.sub(r"[$\s]", "", str(valor).strip())
    if texto == "":
        return 0
    if re.search(r"[.,]\d{1,2}$", texto):  # punto o coma con 1 o 2 dígitos al final = decimal
        return None
    texto = re.sub(r"[.,]", "", texto)
    if not texto.isdigit():
        return None
    return int(texto)


def turno_abierto(id_empresa):
    return db.uno(
        "SELECT * FROM turnos WHERE id_empresa = %s AND estado = 'abierto' "
        "ORDER BY fecha_apertura DESC LIMIT 1",
        (id_empresa,),
    )


def totales_sistema(id_empresa, desde, hasta):
    """Totales para el arqueo, agrupados en tres bolsas:
    efectivo (lo del cajón), tarjeta (datáfono) y digital (QR, Nequi, Daviplata,
    Bre-B, transferencia). 'qr' se mantiene por compatibilidad con turnos.total_qr."""
    r = db.uno(
        f"""SELECT
              SUM(CASE WHEN metodo_pago = 'efectivo' THEN monto ELSE 0 END) AS efectivo,
              SUM(CASE WHEN metodo_pago = 'tarjeta' THEN monto ELSE 0 END) AS tarjeta,
              SUM(CASE WHEN metodo_pago IN ('QR','nequi','daviplata','breb','transferencia')
                       THEN monto ELSE 0 END) AS digital,
              SUM(CASE WHEN metodo_pago = 'QR' THEN monto ELSE 0 END) AS solo_qr,
              SUM(CASE WHEN metodo_pago = 'nequi' THEN monto ELSE 0 END) AS nequi,
              SUM(CASE WHEN metodo_pago = 'daviplata' THEN monto ELSE 0 END) AS daviplata,
              SUM(CASE WHEN metodo_pago = 'breb' THEN monto ELSE 0 END) AS breb,
              SUM(CASE WHEN metodo_pago = 'transferencia' THEN monto ELSE 0 END) AS transferencia,
              SUM(monto) AS total
            FROM pagos
            WHERE id_empresa = %s AND fecha_pago BETWEEN %s AND COALESCE(%s::timestamp, {AHORA})""",
        (id_empresa, desde, hasta),
    ) or {}

    def n(k):
        return float(r.get(k) or 0)

    return {
        "efectivo": n("efectivo"),
        "tarjeta": n("tarjeta"),
        "qr": n("digital"),
        "digital": n("digital"),
        "total": n("total"),
        "detalle": {k: n(c) for k, c in
                    (("qr", "solo_qr"), ("nequi", "nequi"), ("daviplata", "daviplata"),
                     ("breb", "breb"), ("transferencia", "transferencia"))},
    }


def conteo_tickets(id_empresa, desde, hasta):
    filas = db.consultar(
        f"""SELECT tv.codigo AS tipo, COUNT(*) AS cnt
            FROM movimientos m
            JOIN vehiculos v ON v.id_vehiculo = m.id_vehiculo
            JOIN tipos_vehiculos tv ON v.id_tipo = tv.id_tipo
            WHERE m.id_empresa = %s AND m.estado = 'finalizado'
              AND m.fecha_salida BETWEEN %s AND COALESCE(%s::timestamp, {AHORA})
            GROUP BY tv.codigo""",
        (id_empresa, desde, hasta),
    )
    por_tipo = {f["tipo"]: int(f["cnt"]) for f in filas}
    return {"total": sum(por_tipo.values()), "porTipo": por_tipo}


@router.get("")
def historial(
    estado: str = "", desde: str = "", hasta: str = "",
    page: str = Query("1"), limit: str = Query("20"),
    u: Usuario = Depends(usuario_actual),
):
    """Historial de turnos, del más reciente al más viejo. Los totales son los
    GUARDADOS al cierre: no se recalculan aunque luego se corrija un pago."""
    condiciones, valores = ["t.id_empresa = %s"], [u.id_empresa]

    estado = estado.strip().lower()
    if estado in ("cerrado", "abierto"):
        condiciones.append("t.estado = %s")
        valores.append(estado)
    if FECHA_ISO.match(desde):
        condiciones.append("t.fecha_apertura >= %s")
        valores.append(desde + " 00:00:00")
    if FECHA_ISO.match(hasta):
        condiciones.append("t.fecha_apertura <= %s")
        valores.append(hasta + " 23:59:59")
    where = " AND ".join(condiciones)

    pagina = int(page) if page.isdigit() and int(page) >= 1 else 1
    por_pagina = min(int(limit), 100) if limit.isdigit() and int(limit) >= 1 else 20

    total = db.uno(f"SELECT COUNT(*) AS n FROM turnos t WHERE {where}", valores)["n"]
    filas = db.consultar(
        f"""SELECT t.id_turno, t.fecha_apertura, t.fecha_cierre, t.base_inicial,
                   t.total_efectivo, t.total_tarjeta, t.total_qr,
                   t.total_general, t.diferencia, t.estado,
                   t.observacion_apertura, t.observacion_cierre,
                   u.nombre AS usuario
            FROM turnos t
            LEFT JOIN usuarios u ON u.id_usuario = t.id_usuario
            WHERE {where}
            ORDER BY t.fecha_apertura DESC
            LIMIT %s OFFSET %s""",
        (*valores, por_pagina, (pagina - 1) * por_pagina),
    )
    return {
        "success": True,
        "data": db.filas(filas),
        "paginacion": {"page": pagina, "limit": por_pagina, "total": total,
                       "paginas": max(1, -(-total // por_pagina))},
    }


@router.get("/actual")
def actual(u: Usuario = Depends(usuario_actual)):
    return {"success": True, "data": db.fila(turno_abierto(u.id_empresa))}


@router.get("/resumen")
def resumen(u: Usuario = Depends(usuario_actual)):
    t = turno_abierto(u.id_empresa)
    if not t:
        raise ApiError(400, "No hay turno abierto")
    return {"success": True, "data": {
        "turno": db.fila(t),
        "totales": totales_sistema(u.id_empresa, t["fecha_apertura"], t["fecha_cierre"]),
        "stats": conteo_tickets(u.id_empresa, t["fecha_apertura"], t["fecha_cierre"]),
    }}


@router.post("/abrir")
def abrir(cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(usuario_actual)):
    base = parsear_pesos(cuerpo.get("base_inicial"))
    if base is None:
        raise ApiError(400, "La base inicial debe ser un valor en pesos enteros, sin decimales. Ejemplo: 50000")
    observacion = str(cuerpo.get("observacion_apertura") or "").strip()[:255] or None

    if db.uno("SELECT 1 FROM turnos WHERE id_empresa = %s AND estado = 'abierto'", (u.id_empresa,)):
        raise ApiError(400, "Ya existe un turno abierto. Ciérrelo antes de abrir uno nuevo.")

    nuevo = db.uno(
        "INSERT INTO turnos (id_empresa, id_usuario, base_inicial, observacion_apertura) "
        "VALUES (%s, %s, %s, %s) RETURNING id_turno",
        (u.id_empresa, u.id, base, observacion),
    )
    log.info("Turno %s abierto por usuario %s (empresa %s) con base %s", nuevo["id_turno"], u.id, u.id_empresa, base)
    return {"success": True, "data": {"id_turno": nuevo["id_turno"], "base_inicial": base}}


@router.post("/cerrar")
def cerrar(cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(usuario_actual)):
    """El conteo llega en tres bolsas. total_qr representa TODO lo digital;
    también se acepta total_digital."""
    t = turno_abierto(u.id_empresa)
    if not t:
        raise ApiError(400, "No hay turno abierto")

    efectivo = parsear_pesos(cuerpo.get("total_efectivo"))
    tarjeta = parsear_pesos(cuerpo.get("total_tarjeta"))
    digital = parsear_pesos(cuerpo["total_digital"] if "total_digital" in cuerpo else cuerpo.get("total_qr"))
    if None in (efectivo, tarjeta, digital):
        raise ApiError(400, "Los totales del conteo deben ser valores en pesos enteros, sin decimales.")

    total_conteo = efectivo + tarjeta + digital
    esperado = totales_sistema(u.id_empresa, t["fecha_apertura"], t["fecha_cierre"])
    diferencia = round(total_conteo - esperado["total"], 2)

    cierre = db.uno(
        f"""UPDATE turnos
            SET fecha_cierre = {AHORA}, total_efectivo = %s, total_tarjeta = %s, total_qr = %s,
                total_general = %s, diferencia = %s, observacion_cierre = %s, estado = 'cerrado'
            WHERE id_turno = %s RETURNING fecha_cierre""",
        (efectivo, tarjeta, digital, total_conteo, diferencia,
         str(cuerpo.get("observacion_cierre") or "").strip()[:255] or None, t["id_turno"]),
    )
    log.info("Turno %s cerrado. Diferencia: %s", t["id_turno"], diferencia)

    return {"success": True, "data": {
        "id_turno": t["id_turno"],
        "base": str(t["base_inicial"]),
        "expected": esperado,
        "userTotals": {"efectivo": efectivo, "tarjeta": tarjeta, "qr": digital,
                       "digital": digital, "total": total_conteo},
        "diferencia": diferencia,
        "stats": conteo_tickets(u.id_empresa, t["fecha_apertura"], cierre["fecha_cierre"]),
        "turno": {"id_turno": t["id_turno"], "usuario": u.nombre},
    }}


@router.get("/detalle/{id_turno}")
def detalle(id_turno: int, u: Usuario = Depends(usuario_actual)):
    """Para reimprimir el cierre."""
    t = db.uno(
        """SELECT t.*, u.nombre AS usuario, u.usuario_login
           FROM turnos t JOIN usuarios u ON u.id_usuario = t.id_usuario
           WHERE t.id_empresa = %s AND t.id_turno = %s""",
        (u.id_empresa, id_turno),
    )
    if not t:
        raise ApiError(404, "Turno no encontrado")
    return {"success": True, "data": {
        "turno": db.fila(t),
        "expected": totales_sistema(u.id_empresa, t["fecha_apertura"], t["fecha_cierre"]),
        "stats": conteo_tickets(u.id_empresa, t["fecha_apertura"], t["fecha_cierre"]),
    }}
