"""Ingreso y salida de vehículos.

El cobro se confirma en una transacción: se recalcula el total con la hora
exacta, se valida que lo pagado alcance, se cierra el movimiento y se guardan
los pagos. Si algo falla, no queda nada a medias.
"""
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import db
from app.seguridad import ApiError, Usuario, usuario_actual
from app.tarifa import calcular_total
from app.utiles import AHORA, ahora_utc, cuerpo_json, entero, numero

router = APIRouter(prefix="/api/movimientos", tags=["movimientos"])
log = logging.getLogger("movimientos")

# Deben coincidir con el CHECK de pagos.metodo_pago en schema.sql.
METODOS_VALIDOS = ["efectivo", "tarjeta", "QR", "nequi", "daviplata", "breb", "transferencia"]


def normalizar_metodo(valor):
    """'QR' va en mayúscula, el resto en minúscula. None si el método no existe."""
    v = str(valor or "").strip().lower()
    if not v:
        return None
    if v == "qr":
        return "QR"
    return next((m for m in METODOS_VALIDOS if m.lower() == v), None)


def metodo_invalido(valor):
    return ApiError(400, f'El método de pago "{valor}" no existe. Válidos: {", ".join(METODOS_VALIDOS)}.')


def resumen_tarifa(t):
    return {
        "id_tarifa": t["id_tarifa"],
        "valor_minuto": float(t["valor_minuto"] or 0),
        "valor_hora": float(t["valor_hora"] or 0),
        "valor_dia_completo": float(t["valor_dia_completo"] or 0),
        "modo_cobro": t["modo_cobro"] or "mixto",
    }


def tarifa_por_id(conn, id_tarifa):
    t = conn.execute("SELECT * FROM tarifas WHERE id_tarifa = %s", (id_tarifa,)).fetchone()
    if not t:
        raise ApiError(400, "La tarifa del movimiento ya no existe")
    return t


def armar_factura(conn, id_empresa, id_movimiento):
    m = conn.execute(
        """SELECT m.id_movimiento, m.fecha_entrada, m.fecha_salida, m.total_a_pagar, m.estado,
                  v.placa, tv.nombre AS tipo, tv.codigo AS tipo_codigo
           FROM movimientos m
           JOIN vehiculos v ON v.id_vehiculo = m.id_vehiculo
           JOIN tipos_vehiculos tv ON tv.id_tipo = v.id_tipo
           WHERE m.id_movimiento = %s AND m.id_empresa = %s""",
        (id_movimiento, id_empresa),
    ).fetchone()
    if not m:
        return None

    pagos = conn.execute(
        "SELECT metodo_pago, monto FROM pagos WHERE id_movimiento = %s AND id_empresa = %s",
        (id_movimiento, id_empresa),
    ).fetchall()

    fin = m["fecha_salida"] or ahora_utc()
    minutos = max(1, int((fin - m["fecha_entrada"]).total_seconds() // 60))

    return db.a_json({
        "movimientoId": m["id_movimiento"],
        "placa": m["placa"],
        "tipo": m["tipo"],
        "tipoCodigo": m["tipo_codigo"],
        "fechaEntrada": m["fecha_entrada"],
        "fechaSalida": m["fecha_salida"],
        "minutos": minutos,
        "estado": m["estado"],
        "total": float(m["total_a_pagar"] or 0),
        "pagosList": [{"metodo_pago": p["metodo_pago"], "monto": float(p["monto"])} for p in pagos],
    })


def movimiento_activo_por_placa(conn, placa, id_empresa):
    m = conn.execute(
        """SELECT m.id_movimiento, m.fecha_entrada, m.id_tarifa,
                  v.placa, tv.nombre AS tipo, tv.codigo AS tipo_codigo
           FROM movimientos m
           JOIN vehiculos v ON v.id_vehiculo = m.id_vehiculo
           JOIN tipos_vehiculos tv ON tv.id_tipo = v.id_tipo
           WHERE v.placa = %s AND m.id_empresa = %s AND m.estado = 'activo'
           ORDER BY m.fecha_entrada DESC LIMIT 1""",
        (placa, id_empresa),
    ).fetchone()
    if not m:
        raise ApiError(404, f"No hay ingreso activo para la placa {placa}")
    return m


# --- Ingreso ----------------------------------------------------------------

@router.post("/ingreso")
@router.post("/entrada", include_in_schema=False)  # alias legado
def registrar_entrada(cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(usuario_actual)):
    placa = str(cuerpo.get("placa") or "").strip().upper()
    id_tipo = entero(cuerpo.get("id_tipo"), minimo=0, maximo=2**31 - 1)
    if not placa or not id_tipo:
        raise ApiError(400, "Placa y tipo de vehículo son obligatorios")

    with db.transaccion() as conn:
        tipo = conn.execute(
            "SELECT id_tipo, nombre, codigo FROM tipos_vehiculos "
            "WHERE id_tipo = %s AND id_empresa = %s AND activo = TRUE",
            (id_tipo, u.id_empresa),
        ).fetchone()
        if not tipo:
            raise ApiError(400, "Tipo de vehículo no válido para esta empresa")

        # El vehículo se busca dentro de la empresa; si no existe, se crea.
        veh = conn.execute(
            "SELECT id_vehiculo, id_tipo FROM vehiculos WHERE placa = %s AND id_empresa = %s",
            (placa, u.id_empresa),
        ).fetchone()
        if veh:
            id_vehiculo = veh["id_vehiculo"]
            if veh["id_tipo"] != id_tipo:
                conn.execute("UPDATE vehiculos SET id_tipo = %s WHERE id_vehiculo = %s", (id_tipo, id_vehiculo))
        else:
            id_vehiculo = conn.execute(
                "INSERT INTO vehiculos (id_empresa, placa, id_tipo, color) "
                "VALUES (%s, %s, %s, 'N/D') RETURNING id_vehiculo",
                (u.id_empresa, placa, id_tipo),
            ).fetchone()["id_vehiculo"]

        if conn.execute(
            "SELECT 1 FROM movimientos WHERE id_vehiculo = %s AND id_empresa = %s AND estado = 'activo'",
            (id_vehiculo, u.id_empresa),
        ).fetchone():
            raise ApiError(409, f"La placa {placa} ya tiene un ingreso activo")

        tarifa = conn.execute(
            f"""SELECT * FROM tarifas
                WHERE id_empresa = %s AND id_tipo = %s AND activa = TRUE
                  AND fecha_vigencia_desde <= {AHORA}
                  AND (fecha_vigencia_hasta IS NULL OR fecha_vigencia_hasta >= {AHORA})
                ORDER BY fecha_vigencia_desde DESC LIMIT 1""",
            (u.id_empresa, id_tipo),
        ).fetchone()
        if not tarifa:
            raise ApiError(400, "No hay tarifa vigente para este tipo de vehículo")

        mov = conn.execute(
            """INSERT INTO movimientos (id_empresa, id_vehiculo, id_tarifa, id_usuario_entrada, estado)
               VALUES (%s, %s, %s, %s, 'activo') RETURNING id_movimiento, fecha_entrada""",
            (u.id_empresa, id_vehiculo, tarifa["id_tarifa"], u.id),
        ).fetchone()

    return JSONResponse({
        "success": True,
        "message": "Ingreso registrado",
        "data": db.a_json({
            "movimientoId": mov["id_movimiento"],
            "placa": placa,
            "tipo": tipo["nombre"],
            "tipoCodigo": tipo["codigo"],
            "fechaEntrada": mov["fecha_entrada"],
            "tarifa": resumen_tarifa(tarifa),  # el comprobante de ingreso imprime las tarifas
        }),
    }, status_code=201)


# --- Salida en dos pasos: calcular -> confirmar con pagos ---------------------

@router.post("/calcular-salida")
@router.post("/calcular", include_in_schema=False)  # alias legado
def calcular_salida(cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(usuario_actual)):
    placa = str(cuerpo.get("placa") or "").strip().upper()
    if not placa:
        raise ApiError(400, "La placa es obligatoria")

    with db.pool.connection() as conn:
        m = movimiento_activo_por_placa(conn, placa, u.id_empresa)
        tarifa = tarifa_por_id(conn, m["id_tarifa"])

    ahora = ahora_utc()
    calculo = calcular_total(tarifa, m["fecha_entrada"], ahora)

    return {"success": True, "data": db.a_json({
        "movimientoId": m["id_movimiento"],
        "placa": m["placa"],
        "tipo": m["tipo"],
        "tipoCodigo": m["tipo_codigo"],
        "fechaEntrada": m["fecha_entrada"],
        "fechaSalida": ahora,
        "minutos": calculo["minutos"],
        "detalleTiempo": calculo["detalleTiempo"],
        "tarifa": resumen_tarifa(tarifa),
        "total": calculo["total"],
        "pagosList": [],
    })}


def confirmar(u: Usuario, id_movimiento: int, pagos: list):
    # El método se valida ANTES de tocar la base, para no fallar después de cobrar.
    for p in pagos:
        if isinstance(p, dict) and p.get("metodo_pago") and not normalizar_metodo(p["metodo_pago"]):
            raise metodo_invalido(p["metodo_pago"])

    with db.transaccion() as conn:
        mov = conn.execute(
            "SELECT id_movimiento, fecha_entrada, id_tarifa, estado FROM movimientos "
            "WHERE id_movimiento = %s AND id_empresa = %s FOR UPDATE",
            (id_movimiento, u.id_empresa),
        ).fetchone()
        if not mov:
            raise ApiError(404, "Movimiento no encontrado")
        if mov["estado"] == "finalizado":
            raise ApiError(409, "El movimiento ya fue finalizado")

        tarifa = tarifa_por_id(conn, mov["id_tarifa"])
        ahora = ahora_utc()
        total = calcular_total(tarifa, mov["fecha_entrada"], ahora)["total"]

        validos = [
            (u.id_empresa, id_movimiento, normalizar_metodo(p["metodo_pago"]), numero(p.get("monto")), u.id)
            for p in pagos
            if isinstance(p, dict) and p.get("metodo_pago") and numero(p.get("monto")) > 0
        ]
        if sum(v[3] for v in validos) + 0.01 < total:
            raise ApiError(400, "El pago registrado es menor al total a pagar")

        conn.execute(
            """UPDATE movimientos
               SET fecha_salida = %s, total_a_pagar = %s, id_usuario_salida = %s, estado = 'finalizado'
               WHERE id_movimiento = %s AND id_empresa = %s""",
            (ahora, total, u.id, id_movimiento, u.id_empresa),
        )
        if validos:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO pagos (id_empresa, id_movimiento, metodo_pago, monto, id_usuario) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    validos,
                )

        factura = armar_factura(conn, u.id_empresa, id_movimiento)

    return {"success": True, "message": "Salida confirmada", "data": factura}


@router.post("/confirmar-salida")
@router.post("/confirmar", include_in_schema=False)  # alias legado
def confirmar_salida(cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(usuario_actual)):
    id_movimiento = entero(cuerpo.get("id_movimiento"), minimo=0, maximo=2**31 - 1)
    if not id_movimiento:
        raise ApiError(400, "id_movimiento es obligatorio")
    pagos = cuerpo.get("pagos") if isinstance(cuerpo.get("pagos"), list) else []
    return confirmar(u, id_movimiento, pagos)


@router.post("/salida")
def registrar_salida(cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(usuario_actual)):
    """Salida directa por placa, pagando el total con un solo método."""
    placa = str(cuerpo.get("placa") or "").strip().upper()
    crudo = cuerpo.get("metodoPago") or cuerpo.get("metodo_pago") or "efectivo"
    if not placa:
        raise ApiError(400, "La placa es obligatoria")
    metodo = normalizar_metodo(crudo)
    if not metodo:
        raise metodo_invalido(crudo)

    with db.pool.connection() as conn:
        m = movimiento_activo_por_placa(conn, placa, u.id_empresa)
        tarifa = tarifa_por_id(conn, m["id_tarifa"])
    total = calcular_total(tarifa, m["fecha_entrada"], ahora_utc())["total"]

    return confirmar(u, m["id_movimiento"], [{"metodo_pago": metodo, "monto": total}])


# --- Consultas ----------------------------------------------------------------

@router.get("/activos")
def listar_activos(u: Usuario = Depends(usuario_actual)):
    filas = db.consultar(
        "SELECT * FROM v_movimientos_activos WHERE id_empresa = %s ORDER BY fecha_entrada DESC",
        (u.id_empresa,),
    )
    return {"success": True, "data": db.filas(filas)}


@router.get("/detalle/{id_movimiento}")
def detalle(id_movimiento: int, u: Usuario = Depends(usuario_actual)):
    """Si el movimiento sigue activo, el total es una PREVISUALIZACIÓN con la hora
    actual. El cobro real se recalcula en la salida."""
    with db.pool.connection() as conn:
        m = conn.execute(
            """SELECT m.id_movimiento, m.fecha_entrada, m.fecha_salida, m.total_a_pagar, m.estado,
                      m.id_tarifa, v.placa, tv.nombre AS tipo, tv.codigo AS tipo_codigo,
                      ue.nombre AS usuario_entrada, us.nombre AS usuario_salida
               FROM movimientos m
               JOIN vehiculos v ON v.id_vehiculo = m.id_vehiculo
               JOIN tipos_vehiculos tv ON tv.id_tipo = v.id_tipo
               LEFT JOIN usuarios ue ON ue.id_usuario = m.id_usuario_entrada
               LEFT JOIN usuarios us ON us.id_usuario = m.id_usuario_salida
               WHERE m.id_movimiento = %s AND m.id_empresa = %s""",
            (id_movimiento, u.id_empresa),
        ).fetchone()
        if not m:
            raise ApiError(404, "Movimiento no encontrado")
        tarifa = conn.execute("SELECT * FROM tarifas WHERE id_tarifa = %s", (m["id_tarifa"],)).fetchone()

    salida = dict(m)
    if m["estado"] == "activo" and tarifa:
        calculo = calcular_total(tarifa, m["fecha_entrada"], ahora_utc())
        salida.update(
            total=calculo["total"], total_a_pagar=calculo["total"], minutos=calculo["minutos"],
            detalleTiempo=calculo["detalleTiempo"], es_previsualizacion=True,
        )
    elif m["estado"] != "activo":
        salida["total"] = float(m["total_a_pagar"] or 0)

    return {"success": True, "data": db.a_json(salida)}


@router.get("/factura/{id_movimiento}")
def factura(id_movimiento: int, u: Usuario = Depends(usuario_actual)):
    """Para reimprimir el comprobante."""
    with db.pool.connection() as conn:
        datos = armar_factura(conn, u.id_empresa, id_movimiento)
    if not datos:
        raise ApiError(404, "Movimiento no encontrado")
    return {"success": True, "data": datos}


# --- Pagos adicionales sobre un movimiento ya finalizado ------------------------

pagos_router = APIRouter(prefix="/api/pagos", tags=["pagos"])


@pagos_router.post("/bulk")
def pagos_bulk(cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(usuario_actual)):
    id_movimiento = entero(cuerpo.get("id_movimiento"), minimo=0, maximo=2**31 - 1)
    pagos = cuerpo.get("pagos")
    if not id_movimiento or not isinstance(pagos, list) or not pagos:
        raise ApiError(400, "Datos de pago inválidos")

    if not db.uno(
        "SELECT 1 FROM movimientos WHERE id_movimiento = %s AND id_empresa = %s",
        (id_movimiento, u.id_empresa),
    ):
        raise ApiError(404, "Movimiento no encontrado")

    validos = []
    for p in pagos:
        if not isinstance(p, dict) or not p.get("metodo_pago") or not numero(p.get("monto")) > 0:
            continue
        metodo = normalizar_metodo(p["metodo_pago"])
        if not metodo:
            raise metodo_invalido(p["metodo_pago"])
        validos.append((u.id_empresa, id_movimiento, metodo, numero(p["monto"]), u.id))
    if not validos:
        raise ApiError(400, "No hay pagos válidos")

    with db.transaccion() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO pagos (id_empresa, id_movimiento, metodo_pago, monto, id_usuario) "
            "VALUES (%s, %s, %s, %s, %s)",
            validos,
        )
    return {"success": True, "message": "Pagos registrados"}
