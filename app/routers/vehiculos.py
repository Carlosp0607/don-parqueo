from fastapi import APIRouter, Depends

from app import db
from app.seguridad import ApiError, Usuario, usuario_actual
from app.utiles import cuerpo_json

router = APIRouter(prefix="/api/vehiculos", tags=["vehiculos"])


def verificar_propiedad(id_vehiculo: int, u: Usuario):
    """Ningún vehículo de otra empresa se puede ver ni tocar."""
    if id_vehiculo < 1:
        raise ApiError(400, "id inválido")
    if not db.uno(
        "SELECT id_vehiculo FROM vehiculos WHERE id_vehiculo = %s AND id_empresa = %s",
        (id_vehiculo, u.id_empresa),
    ):
        raise ApiError(404, "Vehículo no encontrado")


def validar_tipo(id_tipo, u: Usuario):
    if not id_tipo:
        raise ApiError(400, "El tipo de vehículo es obligatorio")
    if not db.uno(
        "SELECT id_tipo FROM tipos_vehiculos WHERE id_tipo = %s AND id_empresa = %s AND activo = TRUE",
        (id_tipo, u.id_empresa),
    ):
        raise ApiError(400, "Tipo de vehículo no válido o inactivo")


def placa_de(cuerpo):
    return str(cuerpo.get("placa") or "").strip().upper()


@router.get("")
def listar(u: Usuario = Depends(usuario_actual)):
    filas = db.consultar(
        """SELECT v.*, tv.nombre AS tipo, tv.codigo AS tipo_codigo,
                  CASE WHEN EXISTS (
                      SELECT 1 FROM movimientos m
                      WHERE m.id_vehiculo = v.id_vehiculo AND m.fecha_salida IS NULL
                  ) THEN 'activo' ELSE 'inactivo' END AS estado
           FROM vehiculos v
           JOIN tipos_vehiculos tv ON v.id_tipo = tv.id_tipo
           WHERE v.id_empresa = %s
           ORDER BY v.fecha_registro DESC""",
        (u.id_empresa,),
    )
    return db.filas(filas)


@router.get("/{id_vehiculo}")
def ver(id_vehiculo: int, u: Usuario = Depends(usuario_actual)):
    verificar_propiedad(id_vehiculo, u)
    fila = db.uno(
        """SELECT v.*, tv.nombre AS tipo, tv.codigo AS tipo_codigo
           FROM vehiculos v
           JOIN tipos_vehiculos tv ON v.id_tipo = tv.id_tipo
           WHERE v.id_vehiculo = %s AND v.id_empresa = %s""",
        (id_vehiculo, u.id_empresa),
    )
    return db.fila(fila)


@router.get("/{id_vehiculo}/historial")
def historial(id_vehiculo: int, u: Usuario = Depends(usuario_actual)):
    verificar_propiedad(id_vehiculo, u)
    filas = db.consultar(
        """SELECT m.id_movimiento, m.fecha_entrada, m.fecha_salida, m.total_a_pagar, m.estado,
                  tv.nombre AS tipo_vehiculo,
                  COALESCE(SUM(p.monto), 0) AS total_pagado,
                  COUNT(p.id_pago) AS pagos
           FROM movimientos m
           JOIN tarifas t ON t.id_tarifa = m.id_tarifa
           JOIN tipos_vehiculos tv ON t.id_tipo = tv.id_tipo
           LEFT JOIN pagos p ON p.id_movimiento = m.id_movimiento
           WHERE m.id_vehiculo = %s AND m.id_empresa = %s
           GROUP BY m.id_movimiento, m.fecha_entrada, m.fecha_salida, m.total_a_pagar, m.estado, tv.nombre
           ORDER BY m.fecha_entrada DESC""",
        (id_vehiculo, u.id_empresa),
    )
    return {"success": True, "data": db.filas(filas)}


@router.post("", status_code=201)
def crear(cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(usuario_actual)):
    placa, id_tipo = placa_de(cuerpo), cuerpo.get("id_tipo")
    validar_tipo(id_tipo, u)
    if not placa:
        raise ApiError(400, "La placa es obligatoria")
    if db.uno("SELECT id_vehiculo FROM vehiculos WHERE placa = %s AND id_empresa = %s", (placa, u.id_empresa)):
        raise ApiError(400, "Ya existe un vehículo con esta placa")

    nuevo = db.uno(
        """INSERT INTO vehiculos (id_empresa, placa, id_tipo, color, modelo)
           VALUES (%s, %s, %s, %s, %s) RETURNING id_vehiculo""",
        (u.id_empresa, placa, id_tipo, cuerpo.get("color") or "", cuerpo.get("modelo")),
    )
    return {"success": True, "message": "Vehículo registrado exitosamente", "id": nuevo["id_vehiculo"]}


@router.put("/{id_vehiculo}")
def actualizar(id_vehiculo: int, cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(usuario_actual)):
    verificar_propiedad(id_vehiculo, u)
    placa, id_tipo = placa_de(cuerpo), cuerpo.get("id_tipo")
    validar_tipo(id_tipo, u)
    if db.uno(
        "SELECT id_vehiculo FROM vehiculos WHERE placa = %s AND id_empresa = %s AND id_vehiculo <> %s",
        (placa, u.id_empresa, id_vehiculo),
    ):
        raise ApiError(400, "Ya existe otro vehículo con esta placa")

    db.ejecutar(
        """UPDATE vehiculos SET placa = %s, id_tipo = %s, color = %s, modelo = %s
           WHERE id_vehiculo = %s AND id_empresa = %s""",
        (placa, id_tipo, cuerpo.get("color") or "", cuerpo.get("modelo"), id_vehiculo, u.id_empresa),
    )
    return {"success": True, "message": "Vehículo actualizado exitosamente"}


@router.delete("/{id_vehiculo}")
def eliminar(id_vehiculo: int, u: Usuario = Depends(usuario_actual)):
    verificar_propiedad(id_vehiculo, u)
    if db.uno("SELECT 1 FROM movimientos WHERE id_vehiculo = %s AND fecha_salida IS NULL", (id_vehiculo,)):
        raise ApiError(400, "No se puede eliminar un vehículo con movimientos activos")
    if db.uno("SELECT 1 FROM movimientos WHERE id_vehiculo = %s", (id_vehiculo,)) or \
            db.uno("SELECT 1 FROM mensualidades WHERE id_vehiculo = %s", (id_vehiculo,)):
        raise ApiError(400, "No se puede eliminar un vehículo con historial de movimientos o mensualidades")

    db.ejecutar("DELETE FROM vehiculos WHERE id_vehiculo = %s AND id_empresa = %s", (id_vehiculo, u.id_empresa))
    return {"success": True, "message": "Vehículo eliminado exitosamente"}
