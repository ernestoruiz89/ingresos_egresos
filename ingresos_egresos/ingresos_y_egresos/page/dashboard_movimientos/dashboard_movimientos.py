import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

@frappe.whitelist()
def get_dashboard_data(sucursal=None, from_date=None, to_date=None):
    if not sucursal:
        return {}

    # Validar permisos
    if not frappe.has_permission("Branch", "read", sucursal):
         frappe.throw(_("No tiene permisos para acceder a la sucursal seleccionada."))

    # 1. Obtener fecha del último cierre para esta sucursal (necesario para sugerir 'Desde')
    ultimo_cierre = frappe.db.get_value(
        "Registro de Cierre de Movimiento",
        filters={"sucursal": sucursal, "docstatus": 1},
        fieldname="fecha_final",
        order_by="fecha_final desc"
    )

    # 2. Construir filtros para frappe.get_all
    filtros = {
        "sucursal": sucursal,
        "docstatus": 1
    }

    if from_date and to_date:
        filtros["fecha_de_registro"] = ["between", [from_date, to_date]]
    
    # 3. Obtener todos los movimientos filtrados para calcular totales (KPIs)
    # Al usar frappe.get_all aquí y en la tabla, los datos DEBEN coincidir
    todos_los_movimientos = frappe.get_all(
        "Movimiento",
        filters=filtros,
        fields=["tipo", "importe", "vinculado"]
    )

    t_ingresos = 0
    t_egresos = 0
    v_ingresos = 0
    v_egresos = 0
    p_ingresos = 0
    p_egresos = 0

    for m in todos_los_movimientos:
        val = flt(m.importe)
        tipo = m.tipo
        is_vinc = m.vinculado

        if tipo == "Ingreso":
            t_ingresos += val
            if is_vinc: v_ingresos += val
            else: p_ingresos += val
        elif tipo == "Egreso":
            t_egresos += val
            if is_vinc: v_egresos += val
            else: p_egresos += val

    # Saldo actual total
    saldo_total = t_ingresos - t_egresos

    # Últimos 10 movimientos (para la vista previa de la tabla)
    movimientos_preview = frappe.get_all(
        "Movimiento",
        filters=filtros,
        fields=["name", "fecha_de_registro", "tipo", "clasificacion", "importe", "vinculado"],
        order_by="fecha_de_registro desc, creation desc",
        limit_page_length=10
    )

    return {
        "periodo": {
            "estado": "Abierto" if not ultimo_cierre or ultimo_cierre < getdate(nowdate()) else "Cerrado hoy",
            "ultimo_cierre": ultimo_cierre
        },
        "totales": {
            "ingresos": t_ingresos,
            "egresos": t_egresos,
            "saldo": saldo_total,
            "detalles": {
                "ingresos_vinc": v_ingresos,
                "ingresos_pend": p_ingresos,
                "egresos_vinc": v_egresos,
                "egresos_pend": p_egresos
            }
        },
        "movimientos": movimientos_preview
    }
