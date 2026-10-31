import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate
from ingresos_egresos.currency import aggregate, get_base_currency


def empty_totals():
    return dict(ingresos=0, egresos=0, saldo=0, saldo_anterior=0,
                detalles=dict(ingresos_vinc=0, ingresos_pend=0, egresos_vinc=0, egresos_pend=0))


@frappe.whitelist()
def get_dashboard_data(sucursal=None, from_date=None, to_date=None, moneda=None):
    if not sucursal:
        return {}
    frappe.has_permission("Movimiento", "read", throw=True)
    if not frappe.has_permission("Branch", "read", sucursal):
        frappe.throw(_("No tiene permisos para acceder a la sucursal seleccionada."))
    if from_date and to_date and getdate(from_date) > getdate(to_date):
        frappe.throw(_("La fecha inicial debe ser menor o igual a la fecha final."))
    base = get_base_currency()
    filters = {"sucursal": sucursal, "docstatus": ["<", 2]}
    if moneda:
        filters["moneda"] = moneda
    if from_date and to_date:
        filters["fecha_de_registro"] = ["between", [from_date, to_date]]
    elif from_date:
        filters["fecha_de_registro"] = [">=", from_date]
    elif to_date:
        filters["fecha_de_registro"] = ["<=", to_date]

    # Aggregate with exactly the same filters and permissions as the preview.
    groups = frappe.get_list("Movimiento", filters=filters,
        fields=["moneda", "tipo", "vinculado", aggregate("sum", "importe", "importe"), aggregate("sum", "importe_base", "importe_base")],
        group_by="moneda, tipo, vinculado", limit_page_length=0)
    totals = empty_totals()
    by_currency = {}
    for row in groups:
        entry = by_currency.setdefault(row.moneda, empty_totals())
        kind = "ingresos" if row.tipo == "Ingreso" else "egresos"
        detail = kind + ("_vinc" if row.vinculado else "_pend")
        entry[kind] += flt(row.importe)
        entry["detalles"][detail] += flt(row.importe)
        totals[kind] += flt(row.importe_base)
        totals["detalles"][detail] += flt(row.importe_base)
    if from_date:
        history_filters = {"sucursal": sucursal, "docstatus": ["<", 2], "fecha_de_registro": ["<", from_date]}
        if moneda:
            history_filters["moneda"] = moneda
        history = frappe.get_list("Movimiento", filters=history_filters,
            fields=["moneda", "tipo", aggregate("sum", "importe", "importe"), aggregate("sum", "importe_base", "importe_base")],
            group_by="moneda, tipo", limit_page_length=0)
        for row in history:
            entry = by_currency.setdefault(row.moneda, empty_totals())
            sign = 1 if row.tipo == "Ingreso" else -1
            entry["saldo_anterior"] += sign * flt(row.importe)
            totals["saldo_anterior"] += sign * flt(row.importe_base)
    totals["saldo"] = totals["saldo_anterior"] + totals["ingresos"] - totals["egresos"]
    for entry in by_currency.values():
        entry["saldo"] = entry["saldo_anterior"] + entry["ingresos"] - entry["egresos"]
    preview = frappe.get_list("Movimiento", filters=filters,
        fields=["name", "fecha_de_registro", "tipo", "clasificacion", "importe", "importe_base", "moneda", "vinculado", "referencia", "descripcion"],
        order_by="fecha_de_registro desc, creation desc", limit_page_length=10)
    # There is no single closing date across currencies.
    last = None
    if moneda:
        rows = frappe.get_list("Registro de Cierre de Movimiento",
            filters={"sucursal": sucursal, "moneda": moneda, "docstatus": 1},
            fields=["fecha_final"], order_by="fecha_final desc", limit_page_length=1)
        last = rows[0].fecha_final if rows else None
    return {"moneda_base": base, "totales": totals,
            "por_moneda": [dict(moneda=currency, **values) for currency, values in sorted(by_currency.items())],
            "movimientos": preview,
            "periodo": {"ultimo_cierre": last, "estado": "Cerrado hoy" if last and getdate(last) >= getdate(nowdate()) else "Abierto"}}
