import frappe
from frappe import _
from frappe.utils import flt
from ingresos_egresos.currency import aggregate, report_context


def execute(filters=None):
    filters = filters or {}
    currency, field, movement_filters = report_context(filters)
    if filters.get("type"):
        movement_filters["tipo"] = filters["type"]
    columns = [
        {"label": _("Sucursal"), "fieldname": "sucursal", "fieldtype": "Link", "options": "Branch", "width": 120},
        {"label": _("Clasificación"), "fieldname": "clasificacion", "fieldtype": "Data", "width": 180},
        {"label": _("Estado"), "fieldname": "estado", "fieldtype": "Data", "width": 110},
        {"label": _("Cantidad"), "fieldname": "cantidad", "fieldtype": "Int", "width": 100},
        {"label": _("Moneda"), "fieldname": "moneda", "fieldtype": "Link", "options": "Currency", "width": 80},
        {"label": _("Monto Total"), "fieldname": "total", "fieldtype": "Currency", "options": "moneda", "width": 140},
        {"label": _("% del Total"), "fieldname": "percentage", "fieldtype": "Percent", "width": 100},
    ]
    data = frappe.get_list("Movimiento", filters=movement_filters,
        fields=["sucursal", "clasificacion", "vinculado", aggregate("count", "name", "cantidad"), aggregate("sum", field, "total")],
        group_by="sucursal, clasificacion, vinculado", order_by="sucursal asc, total desc", limit_page_length=0)
    grand_total = sum(flt(row.total) for row in data)
    for row in data:
        row.update(moneda=currency, estado=_("Cerrado") if row.vinculado else _("Pendiente"),
            percentage=flt(flt(row.total) / grand_total * 100, 1) if grand_total else 0)
    chart = {"type": "donut", "height": 300, "data": {
        "labels": [f"{row.sucursal} / {row.clasificacion or _('Sin Clasificación')} ({row.estado})" for row in data],
        "datasets": [{"name": _("Monto por Concepto") + " (" + currency + ")", "values": [row.total for row in data]}]}}
    return columns, data, None, chart
