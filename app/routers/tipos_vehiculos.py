import re

from fastapi import APIRouter, Depends

from app import db
from app.seguridad import ApiError, Usuario, solo_admin, usuario_actual
from app.utiles import como_bool, cuerpo_json

router = APIRouter(prefix="/api/tipos-vehiculos", tags=["tipos de vehículo"])


def normalizar_codigo(codigo) -> str:
    return re.sub(r"\s+", "_", str(codigo).strip().lower())


def verificar_propiedad(id_tipo: int, u: Usuario):
    if id_tipo < 1:
        raise ApiError(400, "id inválido")
    if not db.uno(
        "SELECT id_tipo FROM tipos_vehiculos WHERE id_tipo = %s AND id_empresa = %s",
        (id_tipo, u.id_empresa),
    ):
        raise ApiError(404, "Tipo de vehículo no encontrado")


def guardar_capacidad(conn, id_empresa, id_tipo, capacidad):
    conn.execute(
        """INSERT INTO capacidades_tipo (id_empresa, id_tipo, capacidad_total)
           VALUES (%s, %s, %s)
           ON CONFLICT (id_empresa, id_tipo) DO UPDATE SET capacidad_total = EXCLUDED.capacidad_total""",
        (id_empresa, id_tipo, int(float(capacidad))),
    )


@router.get("")
def listar(u: Usuario = Depends(usuario_actual)):
    filas = db.consultar(
        """SELECT tv.*,
                  COALESCE(ct.capacidad_total, 0) AS capacidad_total,
                  (SELECT COUNT(*) FROM vehiculos v
                    WHERE v.id_tipo = tv.id_tipo AND v.id_empresa = tv.id_empresa) AS total_vehiculos,
                  (SELECT COUNT(*) FROM tarifas t
                    WHERE t.id_tipo = tv.id_tipo AND t.id_empresa = tv.id_empresa AND t.activa = TRUE) AS tiene_tarifa_activa
           FROM tipos_vehiculos tv
           LEFT JOIN capacidades_tipo ct ON ct.id_tipo = tv.id_tipo AND ct.id_empresa = tv.id_empresa
           WHERE tv.id_empresa = %s
           ORDER BY tv.fecha_creacion ASC""",
        (u.id_empresa,),
    )
    return {"success": True, "data": db.filas(filas)}


@router.get("/activos")
def activos(u: Usuario = Depends(usuario_actual)):
    filas = db.consultar(
        "SELECT id_tipo, nombre, codigo FROM tipos_vehiculos "
        "WHERE id_empresa = %s AND activo = TRUE ORDER BY nombre ASC",
        (u.id_empresa,),
    )
    return {"success": True, "data": db.filas(filas)}


@router.get("/{id_tipo}")
def ver(id_tipo: int, u: Usuario = Depends(usuario_actual)):
    verificar_propiedad(id_tipo, u)
    fila = db.uno(
        """SELECT tv.*, COALESCE(ct.capacidad_total, 0) AS capacidad_total
           FROM tipos_vehiculos tv
           LEFT JOIN capacidades_tipo ct ON ct.id_tipo = tv.id_tipo AND ct.id_empresa = tv.id_empresa
           WHERE tv.id_tipo = %s AND tv.id_empresa = %s""",
        (id_tipo, u.id_empresa),
    )
    return {"success": True, "data": db.fila(fila)}


@router.post("", status_code=201)
def crear(cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(solo_admin)):
    nombre, codigo = cuerpo.get("nombre"), cuerpo.get("codigo")
    if not nombre or not codigo:
        raise ApiError(400, "Nombre y código son obligatorios")
    codigo = normalizar_codigo(codigo)

    if db.uno("SELECT 1 FROM tipos_vehiculos WHERE codigo = %s AND id_empresa = %s", (codigo, u.id_empresa)):
        raise ApiError(400, "Ya existe un tipo de vehículo con este código")

    with db.transaccion() as conn:
        id_tipo = conn.execute(
            """INSERT INTO tipos_vehiculos (id_empresa, nombre, codigo, activo)
               VALUES (%s, %s, %s, TRUE) RETURNING id_tipo""",
            (u.id_empresa, str(nombre).strip(), codigo),
        ).fetchone()["id_tipo"]
        if cuerpo.get("capacidad_total") is not None:
            guardar_capacidad(conn, u.id_empresa, id_tipo, cuerpo["capacidad_total"])

    return {"success": True, "message": "Tipo de vehículo registrado exitosamente", "id": id_tipo}


@router.put("/{id_tipo}")
def actualizar(id_tipo: int, cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(solo_admin)):
    verificar_propiedad(id_tipo, u)
    nombre = cuerpo.get("nombre")
    if not nombre:
        raise ApiError(400, "El nombre es obligatorio")

    codigo = normalizar_codigo(cuerpo["codigo"]) if cuerpo.get("codigo") else None
    if codigo and db.uno(
        "SELECT 1 FROM tipos_vehiculos WHERE codigo = %s AND id_empresa = %s AND id_tipo <> %s",
        (codigo, u.id_empresa, id_tipo),
    ):
        raise ApiError(400, "Ya existe otro tipo de vehículo con este código")

    activo = como_bool(cuerpo["activo"]) if cuerpo.get("activo") is not None else True

    with db.transaccion() as conn:
        conn.execute(
            """UPDATE tipos_vehiculos SET nombre = %s, codigo = COALESCE(%s, codigo), activo = %s
               WHERE id_tipo = %s AND id_empresa = %s""",
            (str(nombre).strip(), codigo, activo, id_tipo, u.id_empresa),
        )
        if cuerpo.get("capacidad_total") is not None:
            guardar_capacidad(conn, u.id_empresa, id_tipo, cuerpo["capacidad_total"])

    return {"success": True, "message": "Tipo de vehículo actualizado exitosamente"}


@router.delete("/{id_tipo}")
def eliminar(id_tipo: int, u: Usuario = Depends(solo_admin)):
    verificar_propiedad(id_tipo, u)
    if db.uno("SELECT COUNT(*) AS n FROM vehiculos WHERE id_tipo = %s", (id_tipo,))["n"] > 0:
        raise ApiError(400, "No se puede eliminar un tipo de vehículo que tiene vehículos asociados")
    if db.uno("SELECT COUNT(*) AS n FROM tarifas WHERE id_tipo = %s AND activa = TRUE", (id_tipo,))["n"] > 0:
        raise ApiError(400, "No se puede eliminar un tipo de vehículo que tiene tarifas activas")
    if db.uno("SELECT COUNT(*) AS n FROM tarifas WHERE id_tipo = %s", (id_tipo,))["n"] > 0:
        raise ApiError(400, "No se puede eliminar: el tipo tiene tarifas usadas en cobros anteriores. Desactívelo.")

    with db.transaccion() as conn:
        conn.execute("DELETE FROM capacidades_tipo WHERE id_tipo = %s AND id_empresa = %s", (id_tipo, u.id_empresa))
        conn.execute("DELETE FROM tipos_vehiculos WHERE id_tipo = %s AND id_empresa = %s", (id_tipo, u.id_empresa))

    return {"success": True, "message": "Tipo de vehículo eliminado exitosamente"}
