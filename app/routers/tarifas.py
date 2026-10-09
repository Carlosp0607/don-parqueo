from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import db
from app.seguridad import ApiError, Usuario, solo_admin, usuario_actual
from app.utiles import AHORA, como_bool, cuerpo_json, entero, numero

router = APIRouter(prefix="/api/tarifas", tags=["tarifas"])

SELECT_BASE = """
    SELECT t.id_tarifa, t.id_tipo, t.valor_hora, t.valor_minuto, t.valor_dia_completo,
           t.modo_cobro, t.paso_minutos_a_horas, t.paso_horas_a_dias,
           t.redondeo_horas, t.redondeo_dias, t.activa,
           t.fecha_vigencia_desde, t.fecha_vigencia_hasta,
           tv.nombre AS tipo_nombre, tv.codigo AS tipo_codigo
    FROM tarifas t
    JOIN tipos_vehiculos tv ON tv.id_tipo = t.id_tipo
"""

MODOS = ("minuto", "hora", "dia", "mixto")
REDONDEOS = ("arriba", "exacto")


@router.get("")
def listar(u: Usuario = Depends(usuario_actual)):
    tarifas = db.filas(db.consultar(f"{SELECT_BASE} WHERE t.id_empresa = %s ORDER BY tv.nombre ASC", (u.id_empresa,)))
    return {"success": True, "data": tarifas, "tarifas": tarifas}


@router.get("/current")
def vigentes(u: Usuario = Depends(usuario_actual)):
    tarifas = db.consultar(
        f"""{SELECT_BASE}
            WHERE t.id_empresa = %s AND t.activa = TRUE
              AND t.fecha_vigencia_desde <= {AHORA}
              AND (t.fecha_vigencia_hasta IS NULL OR t.fecha_vigencia_hasta >= {AHORA})
            ORDER BY tv.nombre ASC""",
        (u.id_empresa,),
    )
    return {"success": True, "data": db.filas(tarifas)}


@router.api_route("", methods=["POST", "PUT"])
def guardar(cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(solo_admin)):
    """Crea o actualiza la tarifa activa de un tipo de vehículo."""
    id_tipo = entero(cuerpo.get("id_tipo"), minimo=0, maximo=2**31 - 1)
    modo = cuerpo.get("modo_cobro") or "mixto"
    valores = [numero(cuerpo.get(k), 0) for k in ("valor_hora", "valor_minuto", "valor_dia_completo")]
    red_horas = cuerpo.get("redondeo_horas") or "arriba"
    red_dias = cuerpo.get("redondeo_dias") or "arriba"

    if not id_tipo:
        raise ApiError(400, "Debe seleccionar un tipo de vehículo")
    if any(v != v or v < 0 for v in valores):  # v != v detecta NaN
        raise ApiError(400, "Los valores no pueden ser negativos")
    if modo not in MODOS:
        raise ApiError(400, "Modo de cobro inválido")
    if red_horas not in REDONDEOS or red_dias not in REDONDEOS:
        raise ApiError(400, "Redondeo inválido")

    if not db.uno("SELECT 1 FROM tipos_vehiculos WHERE id_tipo = %s AND id_empresa = %s", (id_tipo, u.id_empresa)):
        raise ApiError(400, "Tipo de vehículo no válido para esta empresa")

    datos = (*valores, modo,
             entero(cuerpo.get("paso_minutos_a_horas")), entero(cuerpo.get("paso_horas_a_dias")),
             red_horas, red_dias)

    existente = db.uno(
        "SELECT id_tarifa FROM tarifas WHERE id_empresa = %s AND id_tipo = %s AND activa = TRUE LIMIT 1",
        (u.id_empresa, id_tipo),
    )
    if existente:
        db.ejecutar(
            """UPDATE tarifas SET valor_hora = %s, valor_minuto = %s, valor_dia_completo = %s,
                      modo_cobro = %s, paso_minutos_a_horas = %s, paso_horas_a_dias = %s,
                      redondeo_horas = %s, redondeo_dias = %s
               WHERE id_tarifa = %s AND id_empresa = %s""",
            (*datos, existente["id_tarifa"], u.id_empresa),
        )
        return {"success": True, "message": "Tarifa actualizada correctamente", "id_tarifa": existente["id_tarifa"]}

    nueva = db.uno(
        """INSERT INTO tarifas (id_empresa, id_tipo, valor_hora, valor_minuto, valor_dia_completo,
                                modo_cobro, paso_minutos_a_horas, paso_horas_a_dias,
                                redondeo_horas, redondeo_dias, activa)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE) RETURNING id_tarifa""",
        (u.id_empresa, id_tipo, *datos),
    )
    return JSONResponse(
        {"success": True, "message": "Tarifa creada exitosamente", "id_tarifa": nueva["id_tarifa"]},
        status_code=201,
    )


@router.put("/{id_tarifa}/estado")
def cambiar_estado(id_tarifa: int, cuerpo: dict = Depends(cuerpo_json), u: Usuario = Depends(solo_admin)):
    if id_tarifa < 1:
        raise ApiError(400, "id inválido")
    if cuerpo.get("activa") is not None:
        activa = como_bool(cuerpo["activa"])
    else:
        activa = str(cuerpo.get("estado") or "").upper() == "ACTIVO"

    n = db.ejecutar(
        "UPDATE tarifas SET activa = %s WHERE id_tarifa = %s AND id_empresa = %s",
        (activa, id_tarifa, u.id_empresa),
    )
    if n == 0:
        raise ApiError(404, "Tarifa no encontrada")
    return {"success": True, "message": "Estado de la tarifa modificado"}
