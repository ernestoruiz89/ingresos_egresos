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

    # 1. Obtener fecha del último cierre para esta sucursal (siempre necesario para sugerir 'Desde')
    ultimo_cierre = frappe.db.get_value(
        "Registro de Cierre de Movimiento",
        filters={"sucursal": sucursal, "docstatus": 1},
        fieldname="fecha_final",
        order_by="fecha_final desc"
    )

    # 2. Construir condiciones para las consultas
    # Si se pasan fechas, las usamos. Si no, mostramos todo lo pendiente (vinculado=0)
    condiciones_sql = "AND sucursal = %s AND docstatus = 1"
    parametros = [sucursal]

    filtros_get_all = {
        "sucursal": sucursal,
        "docstatus": 1
    }

    if from_date and to_date:
        condiciones_sql += " AND fecha_de_registro BETWEEN %s AND %s"
        parametros.extend([from_date, to_date])
        filtros_get_all["fecha_de_registro"] = ["between", [from_date, to_date]]
    
    # Si no hay fechas, traemos todo (vinculados + no vinculados) para la sucursal
    # No agregamos el filtro de 'vinculado = 0' aquí para permitir el total solicitado

    # Totales detallados
    totales_raw = frappe.db.sql(f"""
        SELECT 
            SUM(CASE WHEN tipo = 'Entrada' THEN importe ELSE 0 END) as total_ingresos,
            SUM(CASE WHEN tipo = 'Salida' THEN importe ELSE 0 END) as total_egresos,
            SUM(CASE WHEN tipo = 'Entrada' AND vinculado = 1 THEN importe ELSE 0 END) as vinculados_ingresos,
            SUM(CASE WHEN tipo = 'Salida' AND vinculado = 1 THEN importe ELSE 0 END) as vinculados_egresos,
            SUM(CASE WHEN tipo = 'Entrada' AND vinculado = 0 THEN importe ELSE 0 END) as pendientes_ingresos,
            SUM(CASE WHEN tipo = 'Salida' AND vinculado = 0 THEN importe ELSE 0 END) as pendientes_egresos
        FROM `tabMovimiento`
        WHERE 1=1 {condiciones_sql}
    """, tuple(parametros), as_dict=True)[0]

    # Saldo actual total
    saldo_total = flt(totales_raw.total_ingresos) - flt(totales_raw.total_egresos)

    # Últimos 10 movimientos
    movimientos = frappe.get_all(
        "Movimiento",
        filters=filtros_get_all,
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
            "ingresos": flt(totales_raw.total_ingresos),
            "egresos": flt(totales_raw.total_egresos),
            "saldo": saldo_total,
            "detalles": {
                "ingresos_vinc": flt(totales_raw.vinculados_ingresos),
                "ingresos_pend": flt(totales_raw.pendientes_ingresos),
                "egresos_vinc": flt(totales_raw.vinculados_egresos),
                "egresos_pend": flt(totales_raw.pendientes_egresos)
            }
        },
        "movimientos": movimientos
    }
