"""Reportes, dashboard y exportación a Excel."""
import datetime as dt
import io

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Font

from app import db
from app.seguridad import Usuario, usuario_actual
from app.utiles import HOY, entero, hoy_utc, redondear, texto_like

router = APIRouter(prefix="/api/reportes", tags=["reportes"])
dashboard_router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def rango(request: Request):
    """Rango de fechas del filtro (por defecto hoy), de 00:00:00 a 23:59:59."""
    hoy = hoy_utc().isoformat()
    q = request.query_params
    desde = q.get("desde") if len(q.get("desde", "")) >= 8 else hoy
    hasta = q.get("hasta") if len(q.get("hasta", "")) >= 8 else hoy
    return f"{desde} 00:00:00", f"{hasta} 23:59:59"


def filtro_movimientos(request: Request, u: Usuario):
    desde, hasta = rango(request)
    q = request.query_params
    where, params = "m.id_empresa = %s AND m.fecha_entrada BETWEEN %s AND %s", [u.id_empresa, desde, hasta]
    if q.get("estado") in ("activo", "finalizado"):
        where += " AND m.estado = %s"
        params.append(q["estado"])
    if q.get("tipo"):
        where += " AND tv.codigo = %s"
        params.append(q["tipo"].lower())
    if q.get("placa"):
        where += " AND v.placa ILIKE %s"
        params.append(texto_like(q["placa"].upper()))
    return where, params


SELECT_MOVIMIENTOS = """
    SELECT m.id_movimiento, v.placa, tv.nombre AS tipo, tv.codigo AS tipo_codigo,
           m.fecha_entrada, m.fecha_salida, m.estado, m.total_a_pagar
    FROM movimientos m
    JOIN vehiculos v ON v.id_vehiculo = m.id_vehiculo
    JOIN tipos_vehiculos tv ON tv.id_tipo = v.id_tipo
"""

SELECT_TURNOS = """
    SELECT t.id_turno, u.nombre AS usuario, t.fecha_apertura, t.fecha_cierre,
           t.base_inicial, t.total_efectivo, t.total_tarjeta, t.total_qr,
           t.total_general, t.diferencia, t.estado
    FROM turnos t
    JOIN usuarios u ON u.id_usuario = t.id_usuario
    WHERE t.id_empresa = %s AND t.fecha_apertura BETWEEN %s AND %s
    ORDER BY t.fecha_apertura DESC
"""


def excel(nombre_hoja, columnas, filas, archivo):
    """Arma un .xlsx con encabezado en negrita. columnas: [(titulo, clave, ancho)]."""
    libro = Workbook()
    hoja = libro.active
    hoja.title = nombre_hoja
    hoja.append([c[0] for c in columnas])
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for i, (_, _, ancho) in enumerate(columnas):
        hoja.column_dimensions[chr(65 + i)].width = ancho

    for f in filas:
        fila = []
        for _, clave, _ in columnas:
            v = f.get(clave)
            fila.append(float(v) if hasattr(v, "is_finite") else v)  # Decimal -> número
        hoja.append(fila)
    for col in hoja.iter_cols(min_row=2):
        for celda in col:
            if isinstance(celda.value, dt.datetime):
                celda.number_format = "yyyy-mm-dd hh:mm"

    buffer = io.BytesIO()
    libro.save(buffer)
    return Response(buffer.getvalue(), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{archivo}"'})


@router.get("/kpis")
def kpis(request: Request, u: Usuario = Depends(usuario_actual)):
    desde, hasta = rango(request)
    rango_params = (u.id_empresa, desde, hasta)

    ingresos_mov = float(db.uno(
        "SELECT COALESCE(SUM(monto), 0) AS t FROM pagos WHERE id_empresa = %s AND fecha_pago BETWEEN %s AND %s",
        rango_params)["t"])
    ingresos_mens = float(db.uno(
        "SELECT COALESCE(SUM(monto), 0) AS t FROM mensualidades_pagos "
        "WHERE id_empresa = %s AND fecha_pago BETWEEN %s AND %s", rango_params)["t"])
    tickets = db.uno(
        "SELECT COUNT(*) AS n FROM movimientos "
        "WHERE id_empresa = %s AND estado = 'finalizado' AND fecha_salida BETWEEN %s AND %s", rango_params)["n"]
    ocupados = db.uno(
        "SELECT COUNT(*) AS n FROM movimientos WHERE id_empresa = %s AND estado = 'activo'", (u.id_empresa,))["n"]
    capacidad = float(db.uno(
        "SELECT COALESCE(SUM(capacidad_total), 0) AS t FROM capacidades_tipo WHERE id_empresa = %s",
        (u.id_empresa,))["t"])

    return {"success": True, "data": {
        "ingresos": ingresos_mov + ingresos_mens,
        "ingresosMov": ingresos_mov,
        "ingresosMens": ingresos_mens,
        "tickets": tickets,
        "promedioTicket": redondear(ingresos_mov / tickets) if tickets else 0,
        "ocupacion": redondear(ocupados / capacidad * 100) if capacidad else 0,
    }}


@router.get("/ingresos-por-dia")
@router.get("/ingresos", include_in_schema=False)  # alias legado
def ingresos_por_dia(request: Request, u: Usuario = Depends(usuario_actual)):
    desde, hasta = rango(request)
    metodo = request.query_params.get("metodo")
    params, filtro = [u.id_empresa, desde, hasta], ""
    if metodo in ("efectivo", "tarjeta", "QR"):
        filtro, params = " AND metodo_pago = %s", params + [metodo]

    filas = db.consultar(
        f"""SELECT fecha_pago::date AS fecha, COALESCE(SUM(monto), 0) AS total
            FROM pagos
            WHERE id_empresa = %s AND fecha_pago BETWEEN %s AND %s{filtro}
            GROUP BY fecha_pago::date ORDER BY fecha ASC""",
        params,
    )
    return {"success": True, "data": db.filas(filas)}


@router.get("/ingresos-por-metodo")
def ingresos_por_metodo(request: Request, u: Usuario = Depends(usuario_actual)):
    desde, hasta = rango(request)
    filas = db.consultar(
        """SELECT metodo_pago, COALESCE(SUM(monto), 0) AS total
           FROM pagos WHERE id_empresa = %s AND fecha_pago BETWEEN %s AND %s
           GROUP BY metodo_pago ORDER BY total DESC""",
        (u.id_empresa, desde, hasta),
    )
    return {"success": True, "data": db.filas(filas)}


@router.get("/movimientos")
def movimientos(request: Request, u: Usuario = Depends(usuario_actual)):
    q = request.query_params
    pagina = entero(q.get("page"), minimo=0, maximo=100_000, defecto=0)
    por_pagina = entero(q.get("pageSize"), minimo=1, maximo=100, defecto=20)
    where, params = filtro_movimientos(request, u)

    filas = db.consultar(
        f"{SELECT_MOVIMIENTOS} WHERE {where} ORDER BY m.fecha_entrada DESC LIMIT %s OFFSET %s",
        (*params, por_pagina, pagina * por_pagina),
    )
    total = db.uno(
        f"""SELECT COUNT(*) AS n FROM movimientos m
            JOIN vehiculos v ON v.id_vehiculo = m.id_vehiculo
            JOIN tipos_vehiculos tv ON tv.id_tipo = v.id_tipo
            WHERE {where}""",
        params,
    )["n"]
    return {"success": True, "data": db.filas(filas), "paging": {
        "page": pagina, "pageSize": por_pagina, "total": total, "hasNext": (pagina + 1) * por_pagina < total,
    }}


@router.get("/movimientos-ajustados")
def movimientos_ajustados(request: Request, u: Usuario = Depends(usuario_actual)):
    """Sin paginar, para exportar a PDF desde el navegador."""
    limite = entero(request.query_params.get("limit"), minimo=1, maximo=5000, defecto=1000)
    where, params = filtro_movimientos(request, u)
    filas = db.consultar(f"{SELECT_MOVIMIENTOS} WHERE {where} ORDER BY m.fecha_entrada DESC LIMIT %s",
                         (*params, limite))
    return {"success": True, "data": db.filas(filas)}


@router.get("/top-placas")
@router.get("/top", include_in_schema=False)  # alias legado
def top_placas(request: Request, u: Usuario = Depends(usuario_actual)):
    desde, hasta = rango(request)
    limite = entero(request.query_params.get("limit"), minimo=1, maximo=100, defecto=10)
    filas = db.consultar(
        """SELECT v.placa, tv.nombre AS tipo, COUNT(*) AS visitas, COALESCE(SUM(m.total_a_pagar), 0) AS total
           FROM movimientos m
           JOIN vehiculos v ON v.id_vehiculo = m.id_vehiculo
           JOIN tipos_vehiculos tv ON tv.id_tipo = v.id_tipo
           WHERE m.id_empresa = %s AND m.fecha_entrada BETWEEN %s AND %s
           GROUP BY v.placa, tv.nombre
           ORDER BY visitas DESC, total DESC
           LIMIT %s""",
        (u.id_empresa, desde, hasta, limite),
    )
    return {"success": True, "data": db.filas(filas)}


@router.get("/export/xlsx")
def exportar_movimientos(request: Request, u: Usuario = Depends(usuario_actual)):
    where, params = filtro_movimientos(request, u)
    filas = db.consultar(f"{SELECT_MOVIMIENTOS} WHERE {where} ORDER BY m.fecha_entrada DESC LIMIT 5000", params)
    return excel("Movimientos", [
        ("ID", "id_movimiento", 10), ("Placa", "placa", 14), ("Tipo", "tipo", 16),
        ("Entrada", "fecha_entrada", 22), ("Salida", "fecha_salida", 22),
        ("Estado", "estado", 14), ("Total", "total_a_pagar", 14),
    ], filas, "reporte-movimientos.xlsx")


@router.get("/turnos")
def turnos(request: Request, u: Usuario = Depends(usuario_actual)):
    desde, hasta = rango(request)
    return {"success": True, "data": db.filas(db.consultar(SELECT_TURNOS, (u.id_empresa, desde, hasta)))}


@router.get("/turnos/export/xlsx")
def exportar_turnos(request: Request, u: Usuario = Depends(usuario_actual)):
    desde, hasta = rango(request)
    filas = db.consultar(SELECT_TURNOS + " LIMIT 5000", (u.id_empresa, desde, hasta))
    return excel("Turnos", [
        ("Turno", "id_turno", 10), ("Usuario", "usuario", 22), ("Apertura", "fecha_apertura", 22),
        ("Cierre", "fecha_cierre", 22), ("Base", "base_inicial", 14), ("Efectivo", "total_efectivo", 14),
        ("Tarjeta", "total_tarjeta", 14), ("QR", "total_qr", 14), ("Total", "total_general", 14),
        ("Diferencia", "diferencia", 14), ("Estado", "estado", 12),
    ], filas, "reporte-turnos.xlsx")


@router.get("/cierre-caja")
def cierre_caja(u: Usuario = Depends(usuario_actual)):
    fila = db.fila(db.uno(
        f"""SELECT COUNT(m.id_movimiento) AS total_vehiculos,
                   COALESCE(SUM(m.total_a_pagar), 0) AS total_recaudado,
                   MIN(m.fecha_entrada) AS primer_ingreso,
                   MAX(m.fecha_salida) AS ultima_salida
            FROM movimientos m
            WHERE m.id_empresa = %s AND m.id_usuario_salida = %s
              AND m.estado = 'finalizado' AND m.fecha_salida::date = {HOY}""",
        (u.id_empresa, u.id),
    ))
    return {"success": True, "cierre": fila, "data": fila}


# --- Dashboard -----------------------------------------------------------------

@dashboard_router.get("/stats")
def stats(request: Request, u: Usuario = Depends(usuario_actual)):
    q = request.query_params
    por_pagina = entero(q.get("pageSize"), minimo=1, maximo=50, defecto=5)
    pagina = entero(q.get("page"), minimo=0, maximo=100_000, defecto=0)
    desplazamiento = pagina * por_pagina

    por_tipo = db.consultar(
        """SELECT tv.nombre AS tipo, tv.codigo AS tipo_codigo, COUNT(*) AS count
           FROM vehiculos v JOIN tipos_vehiculos tv ON v.id_tipo = tv.id_tipo
           WHERE v.id_empresa = %s
           GROUP BY tv.id_tipo, tv.nombre, tv.codigo""",
        (u.id_empresa,),
    )
    ingresos_hoy = db.uno(
        f"""SELECT COALESCE(SUM(total_a_pagar), 0) AS total FROM movimientos
            WHERE id_empresa = %s AND estado = 'finalizado' AND fecha_salida::date = {HOY}""",
        (u.id_empresa,),
    )["total"]
    usuarios = db.uno(
        "SELECT COUNT(*) AS n FROM usuarios WHERE id_empresa = %s AND activo = TRUE", (u.id_empresa,))["n"]
    actividad = db.consultar(
        """SELECT m.id_movimiento AS id, v.placa, tv.nombre AS tipo, tv.codigo AS tipo_codigo,
                  m.fecha_entrada AS entrada,
                  CASE WHEN m.fecha_salida IS NULL THEN 'activo' ELSE 'finalizado' END AS estado
           FROM movimientos m
           JOIN vehiculos v ON m.id_vehiculo = v.id_vehiculo
           JOIN tipos_vehiculos tv ON v.id_tipo = tv.id_tipo
           WHERE m.id_empresa = %s
           ORDER BY CASE WHEN m.fecha_salida IS NULL THEN 0 ELSE 1 END, m.fecha_entrada DESC
           LIMIT %s OFFSET %s""",
        (u.id_empresa, por_pagina, desplazamiento),
    )
    total = db.uno("SELECT COUNT(*) AS n FROM movimientos WHERE id_empresa = %s", (u.id_empresa,))["n"]

    return {
        "currentVehiclesByType": db.filas(por_tipo),
        "todayIncome": db.a_json(ingresos_hoy),
        "totalUsers": usuarios,
        "recentActivity": db.filas(actividad),
        "paging": {"page": pagina, "pageSize": por_pagina, "total": total,
                   "hasNext": desplazamiento + por_pagina < total},
    }
