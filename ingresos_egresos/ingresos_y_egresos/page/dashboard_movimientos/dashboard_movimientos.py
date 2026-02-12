import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

@frappe.whitelist()
def get_dashboard_data(sucursal=None):
    if not sucursal:
        return {}

    # Validar permisos: El usuario debe tener permiso de lectura sobre la Sucursal solicitada
    # Opcionalmente verificar permisos sobre 'Movimiento' si se requiere granularidad
    if not frappe.has_permission("Branch", "read", sucursal):
         frappe.throw(_("No tiene permisos para acceder a la sucursal seleccionada."))

    # 1. Obtener fecha del último cierre para esta sucursal
    ultimo_cierre = frappe.db.get_value(
        "Registro de Cierre de Movimiento",
        filters={"sucursal": sucursal, "docstatus": 1},
        fieldname="fecha_final",
        order_by="fecha_final desc"
    )

    fecha_inicio_calculo = None
    if ultimo_cierre:
        # Si hubo cierre, calculamos desde el día siguiente al último cierre
        # Ojo: la lógica de negocio puede variar, pero asumiremos movimientos NO vinculados (no cerrados)
        pass 
    
    # En lugar de fecha, filtramos por 'vinculado=0' que son los pendientes de cierre
    # Esto es más seguro según la lógica de 'Registro de Cierre' que usa vinculado=0
    
    # Totales (Ingresos y Egresos pendientes de cierre)
    totales = frappe.db.sql("""
        SELECT 
            SUM(CASE WHEN tipo = 'Entrada' THEN importe ELSE 0 END) as total_ingresos,
            SUM(CASE WHEN tipo = 'Salida' THEN importe ELSE 0 END) as total_egresos
        FROM `tabMovimiento`
        WHERE sucursal = %s
        AND docstatus = 1
        AND vinculado = 0
    """, (sucursal,), as_dict=True)[0]

    # Saldo actual (Ingresos - Egresos)
    saldo = flt(totales.total_ingresos) - flt(totales.total_egresos)

    # Últimos 10 movimientos (para la tabla)
    movimientos = frappe.get_all(
        "Movimiento",
        filters={
            "sucursal": sucursal,
            "docstatus": 1
        },
        fields=["name", "fecha_de_registro", "tipo", "clasificacion", "importe", "vinculado"],
        order_by="creation desc",
        limit_page_length=10
    )

    return {
        "periodo": {
            "estado": "Abierto" if not ultimo_cierre or ultimo_cierre < getdate(nowdate()) else "Cerrado hoy",
            "ultimo_cierre": ultimo_cierre
        },
        "totales": {
            "ingresos": flt(totales.total_ingresos),
            "egresos": flt(totales.total_egresos),
            "saldo": saldo
        },
        "movimientos": movimientos
    }
