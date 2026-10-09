"""Cálculo del cobro según la tarifa.

Modos: minuto | hora | dia | mixto, con escalones
(paso_minutos_a_horas, paso_horas_a_dias) y redondeo (arriba | exacto).
"""
import math

from app.utiles import redondear


def techo(n: float) -> int:
    return math.ceil(n - 1e-9)


def calcular_total(tarifa: dict, entrada, salida) -> dict:
    minutos = max(0, int((salida - entrada).total_seconds() // 60))
    if minutos == 0:
        minutos = 1  # cobro mínimo de 1 minuto

    v_min = float(tarifa.get("valor_minuto") or 0)
    v_hora = float(tarifa.get("valor_hora") or 0)
    v_dia = float(tarifa.get("valor_dia_completo") or 0)
    modo = tarifa.get("modo_cobro") or "mixto"
    paso_min_hora = int(tarifa.get("paso_minutos_a_horas") or 0)
    paso_hora_dia = int(tarifa.get("paso_horas_a_dias") or 0)
    red_horas = tarifa.get("redondeo_horas") or "arriba"
    red_dias = tarifa.get("redondeo_dias") or "arriba"

    horas_brutas = minutos / 60
    dias_brutos = minutos / (60 * 24)

    def horas():
        return horas_brutas if red_horas == "exacto" else techo(horas_brutas)

    def dias():
        return dias_brutos if red_dias == "exacto" else techo(dias_brutos)

    if modo == "minuto":
        total = minutos * v_min
    elif modo == "hora":
        total = horas() * v_hora
    elif modo == "dia":
        total = dias() * v_dia
    elif paso_hora_dia > 0 and horas_brutas >= paso_hora_dia:
        total = dias() * v_dia
    elif paso_min_hora > 0 and minutos >= paso_min_hora:
        total = horas() * v_hora
    elif paso_min_hora > 0:
        total = minutos * v_min
    else:
        # Sin escalones: días completos + horas + minutos sobrantes.
        d, resto = divmod(minutos, 60 * 24)
        h, m = divmod(resto, 60)
        total = d * v_dia + h * v_hora + m * v_min

    d, resto = divmod(minutos, 60 * 24)
    h, m = divmod(resto, 60)

    return {
        "minutos": minutos,
        "total": redondear(total),
        "detalleTiempo": {"dias": d, "horas": h, "minutos": m},
    }
