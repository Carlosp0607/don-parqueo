"""Mensualidades: suscripciones por vehículo y sus pagos por periodo."""
import datetime as dt

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import db
from app.seguridad import ApiError, Usuario, usuario_actual
from app.utiles import como_bool, cuerpo_json, entero, hoy_utc, numero, sumar_meses

router = APIRouter(prefix="/api/mensualidades", tags=["mensualidades"])


def meses_entre(b: dt.date, a: dt.date) -> int:
    m = (b.year - a.year) * 12 + (b.month - a.month)
    return m + 1 if b.day >= a.day else m


def proximo_inicio(fila):
    """El siguiente periodo arranca el día después del último pagado, o en la fecha de inicio."""
    if fila.get("last_paid_until"):
        return fila["last_paid_until"] + dt.timedelta(days=1)
    return fila.get("fecha_inicio")


def esta_inactiva(fila, hoy):
    return fila["estado"] == "cancelada" or (fila.get("fecha_fin") is not None and hoy > fila["fecha_fin"])


def estado_de_pago(fila):
    hoy = hoy_utc()
    inicio = proximo_inicio(fila)
    vencidos, dias = 0, None

    if esta_inactiva(fila, hoy) or inicio is None:
        estado = "inactivo"
    elif hoy >= inicio:
        vencidos = max(1, meses_entre(hoy, inicio))
        estado = "vencido"
    else:
        dias = (inicio - hoy).days
        estado = "proximo" if dias <= 5 else "al_dia"

    return {
        "next_payment_date": inicio.isoformat() if inicio else None,
        "overdue_payments": vencidos,
        "due_status": estado,
        "days_to_next": dias,
    }


def vehiculo_por_placa(conn, id_empresa, placa, id_tipo, mensaje):
    """Busca la placa en la empresa; si no existe, crea el vehículo con el tipo dado."""
    veh = conn.execute(
        "SELECT id_vehiculo FROM vehiculos WHERE placa = %s AND id_empresa = %s", (placa, id_empresa)
    ).fetchone()
    if veh:
        return veh["id_vehiculo"]
    id_tipo = entero(id_tipo, minimo=0, maximo=2**31 - 1)
    if not id_tipo:
        raise ApiError(400, mensaje)
    if not conn.execute(
        "SELECT 1 FROM tipos_vehiculos WHERE id_tipo = %s AND id_empresa = %s", (id_tipo, id_empresa)
    ).fetchone():
        raise ApiError(400, "Tipo de vehículo no válido para esta empresa")
    return conn.execute(
        "INSERT INTO vehiculos (id_empresa, placa, id_tipo, color, modelo) "
        "VALUES (%s, %s, %s, '', '') RETURNING id_vehiculo",
        (id_empresa, placa, id_tipo),
    ).fetchone()["id_vehiculo"]


@router.get("")
def listar(q: str = "", estado: str = "", page: str = "1", pageSize: str = "20",
           u: Usuario = Depends(usuario_actual)):
    limite = min(entero(pageSize, minimo=1, maximo=100, defecto=20), 100)
    desplazamiento = max((entero(page, minimo=1, defecto=1) - 1) * limite, 0)

    where, params = ["m.id_empresa = %s"], [u.id_empresa]
    if estado:
        where.append("m.estado = %s")
        params.append(estado)
    if q:
        where.append("(v.placa ILIKE %s OR m.titular_nombre ILIKE %s OR m.titular_documento ILIKE %s)")
        params += [f"%{q}%"] * 3
    condicion = " AND ".join(where)

    filas = db.consultar(
        f"""SELECT m.*, v.placa, tv.nombre AS tipo, tv.codigo AS tipo_codigo, v.id_tipo, p.last_paid_until
            FROM mensualidades m
            JOIN vehiculos v ON v.id_vehiculo = m.id_vehiculo
            JOIN tipos_vehiculos tv ON tv.id_tipo = v.id_tipo
            LEFT JOIN (
                SELECT id_mensualidad, MAX(periodo_hasta) AS last_paid_until
                FROM mensualidades_pagos WHERE id_empresa = %s GROUP BY id_mensualidad
            ) p ON p.id_mensualidad = m.id_mensualidad
            WHERE {condicion}
            ORDER BY m.fecha_creacion DESC
            LIMIT %s OFFSET %s""",
        (u.id_empresa, *params, limite, desplazamiento),
    )
    total = db.uno(
        f"""SELECT COUNT(*) AS total FROM mensualidades m
            JOIN vehiculos v ON v.id_vehiculo = m.id_vehiculo
            JOIN tipos_vehiculos tv ON tv.id_tipo = v.id_tipo
            WHERE {condicion}""",
        params,
    )["total"]

    data = [{**db.fila(f), **estado_de_pago(f)} for f in filas]
    return {"success": True, "data": data, "total": total}


@router.post("")
def crear(cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(usuario_actual)):
    placa = str(cuerpo.get("placa") or "").strip().upper()
    if not (placa and cuerpo.get("titular_nombre") and cuerpo.get("valor_mensual") and cuerpo.get("fecha_inicio")):
        raise ApiError(400, "Faltan datos obligatorios")

    with db.transaccion() as conn:
        id_vehiculo = vehiculo_por_placa(conn, u.id_empresa, placa, cuerpo.get("id_tipo"),
                                         "Tipo de vehículo requerido para crear el vehículo")
        nueva = conn.execute(
            """INSERT INTO mensualidades (
                   id_empresa, id_vehiculo, titular_nombre, titular_documento, titular_telefono, titular_email,
                   valor_mensual, fecha_inicio, fecha_fin, auto_renovar, estado, observaciones)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, 'activa', %s) RETURNING id_mensualidad""",
            (u.id_empresa, id_vehiculo, cuerpo["titular_nombre"],
             cuerpo.get("titular_documento") or None, cuerpo.get("titular_telefono") or None,
             cuerpo.get("titular_email") or None, numero(cuerpo["valor_mensual"]), cuerpo["fecha_inicio"],
             como_bool(cuerpo.get("auto_renovar", True)), cuerpo.get("observaciones") or ""),
        ).fetchone()

    return JSONResponse(
        {"success": True, "id_mensualidad": nueva["id_mensualidad"], "message": "Mensualidad creada"},
        status_code=201,
    )


@router.put("/{id_mensualidad}")
def actualizar(id_mensualidad: int, cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(usuario_actual)):
    with db.transaccion() as conn:
        actual = conn.execute(
            """SELECT m.id_vehiculo, v.placa AS placa_actual
               FROM mensualidades m JOIN vehiculos v ON v.id_vehiculo = m.id_vehiculo
               WHERE m.id_mensualidad = %s AND m.id_empresa = %s""",
            (id_mensualidad, u.id_empresa),
        ).fetchone()
        if not actual:
            raise ApiError(404, "Mensualidad no encontrada")

        id_vehiculo = actual["id_vehiculo"]
        placa = str(cuerpo.get("placa") or "").strip().upper()
        if placa and placa != (actual["placa_actual"] or "").upper():
            id_vehiculo = vehiculo_por_placa(conn, u.id_empresa, placa, cuerpo.get("id_tipo"),
                                             "Tipo de vehículo requerido para crear el vehículo con la nueva placa")

        auto = cuerpo.get("auto_renovar")
        n = conn.execute(
            """UPDATE mensualidades SET
                   id_vehiculo = %s,
                   titular_nombre = COALESCE(%s, titular_nombre),
                   titular_documento = %s,
                   titular_telefono = %s,
                   titular_email = %s,
                   valor_mensual = COALESCE(%s, valor_mensual),
                   fecha_inicio = COALESCE(%s::date, fecha_inicio),
                   fecha_fin = COALESCE(%s::date, fecha_fin),
                   auto_renovar = COALESCE(%s, auto_renovar),
                   estado = COALESCE(%s, estado),
                   observaciones = COALESCE(%s, observaciones)
               WHERE id_mensualidad = %s AND id_empresa = %s""",
            (id_vehiculo,
             cuerpo.get("titular_nombre") or None,
             cuerpo.get("titular_documento") or None,
             cuerpo.get("titular_telefono") or None,
             cuerpo.get("titular_email") or None,
             numero(cuerpo["valor_mensual"]) if cuerpo.get("valor_mensual") is not None else None,
             cuerpo.get("fecha_inicio") or None,
             cuerpo.get("fecha_fin") or None,
             None if auto is None else como_bool(auto),
             cuerpo.get("estado") or None,
             cuerpo.get("observaciones") or None,
             id_mensualidad, u.id_empresa),
        ).rowcount

    return {"success": True, "message": "Mensualidad actualizada" if n else "Sin cambios"}


@router.get("/{id_mensualidad}")
def ver(id_mensualidad: int, u: Usuario = Depends(usuario_actual)):
    fila = db.uno(
        """SELECT m.*, v.placa, tv.nombre AS tipo, tv.codigo AS tipo_codigo, v.id_tipo
           FROM mensualidades m
           JOIN vehiculos v ON v.id_vehiculo = m.id_vehiculo
           JOIN tipos_vehiculos tv ON tv.id_tipo = v.id_tipo
           WHERE m.id_mensualidad = %s AND m.id_empresa = %s""",
        (id_mensualidad, u.id_empresa),
    )
    if not fila:
        raise ApiError(404, "Mensualidad no encontrada")
    return {"success": True, "data": db.fila(fila)}


@router.get("/{id_mensualidad}/pagos")
def pagos(id_mensualidad: int, u: Usuario = Depends(usuario_actual)):
    filas = db.consultar(
        "SELECT * FROM mensualidades_pagos WHERE id_empresa = %s AND id_mensualidad = %s ORDER BY fecha_pago DESC",
        (u.id_empresa, id_mensualidad),
    )
    return {"success": True, "data": db.filas(filas)}


@router.post("/{id_mensualidad}/pagos")
def registrar_pago(id_mensualidad: int, cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(usuario_actual)):
    desde, hasta, monto = cuerpo.get("periodo_desde"), cuerpo.get("periodo_hasta"), cuerpo.get("monto")
    if not (desde and hasta and monto):
        raise ApiError(400, "Datos de pago incompletos")

    metodo = cuerpo.get("metodo_pago") or "efectivo"
    if str(metodo).lower() == "qr":
        metodo = "QR"
    if metodo not in ("efectivo", "tarjeta", "QR", "transferencia"):
        raise ApiError(400, f'El método de pago "{metodo}" no es válido para mensualidades.')

    if not db.uno(
        "SELECT 1 FROM mensualidades WHERE id_mensualidad = %s AND id_empresa = %s", (id_mensualidad, u.id_empresa)
    ):
        raise ApiError(404, "Mensualidad no encontrada")
    if not db.uno(
        "SELECT 1 FROM turnos WHERE id_empresa = %s AND id_usuario = %s AND estado = 'abierto' LIMIT 1",
        (u.id_empresa, u.id),
    ):
        raise ApiError(409, "Debe abrir un turno antes de registrar pagos de mensualidad")

    db.ejecutar(
        """INSERT INTO mensualidades_pagos (
               id_empresa, id_mensualidad, periodo_desde, periodo_hasta, metodo_pago, monto, referencia_pago, id_usuario)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (u.id_empresa, id_mensualidad, desde, hasta, metodo, numero(monto), cuerpo.get("referencia_pago"), u.id),
    )
    return JSONResponse({"success": True, "message": "Pago registrado"}, status_code=201)


@router.get("/{id_mensualidad}/sugerencia-pago")
def sugerencia_pago(id_mensualidad: int, u: Usuario = Depends(usuario_actual)):
    """Próximo periodo a cobrar y monto sugerido (meses vencidos x valor mensual)."""
    m = db.uno(
        """SELECT m.*, (SELECT MAX(periodo_hasta) FROM mensualidades_pagos mp
                         WHERE mp.id_empresa = m.id_empresa AND mp.id_mensualidad = m.id_mensualidad
                       ) AS last_paid_until
           FROM mensualidades m
           WHERE m.id_mensualidad = %s AND m.id_empresa = %s""",
        (id_mensualidad, u.id_empresa),
    )
    if not m:
        raise ApiError(404, "Mensualidad no encontrada")

    valor = float(m["valor_mensual"] or 0)
    hoy, inicio = hoy_utc(), proximo_inicio(m)

    if esta_inactiva(m, hoy) or inicio is None:
        return {"success": True, "data": {"due_status": "inactivo", "valor_mensual": valor, "months": 0,
                                          "periodo_desde": None, "periodo_hasta": None, "monto": 0}}

    meses, estado = 1, "al_dia"
    if hoy >= inicio:
        meses, estado = max(1, meses_entre(hoy, inicio)), "vencido"
    elif (inicio - hoy).days <= 5:
        estado = "proximo"

    hasta = sumar_meses(inicio, meses) - dt.timedelta(days=1)
    return {"success": True, "data": {
        "due_status": estado, "valor_mensual": valor, "months": meses,
        "periodo_desde": inicio.isoformat(), "periodo_hasta": hasta.isoformat(), "monto": valor * meses,
    }}
