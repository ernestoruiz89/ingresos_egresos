import frappe
from frappe import _
from frappe.utils import flt
from ingresos_egresos.currency import aggregate, report_context


def execute(filters=None):
    filters = filters or {}
    currency, field, movement_filters = report_context(filters)
    columns = [
        {"label": _("Sucursal"), "fieldname": "sucursal", "fieldtype": "Link", "options": "Branch", "width": 120},
        {"label": _("Fecha"), "fieldname": "fecha", "fieldtype": "Date", "width": 120},
        {"label": _("Estado"), "fieldname": "estado", "fieldtype": "Data", "width": 110},
        {"label": _("Moneda"), "fieldname": "moneda", "fieldtype": "Link", "options": "Currency", "width": 80},
    ] + [{"label": _(label), "fieldname": name, "fieldtype": "Currency", "options": "moneda", "width": 140}
         for name, label in [("ingresos", "Entradas"), ("egresos", "Salidas"), ("neto", "Flujo Neto"), ("saldo_acumulado", "Saldo Acumulado")]]
    rows = frappe.get_list("Movimiento", filters=movement_filters,
        fields=["sucursal", "fecha_de_registro", "vinculado", "tipo", aggregate("sum", field, "total")],
        group_by="sucursal, fecha_de_registro, vinculado, tipo", order_by="fecha_de_registro asc, sucursal asc, vinculado asc", limit_page_length=0)
    history_filters = dict(movement_filters, fecha_de_registro=["<", filters["from_date"]])
    history = frappe.get_list("Movimiento", filters=history_filters,
        fields=["tipo", aggregate("sum", field, "total")], group_by="tipo", limit_page_length=0)
    balance = sum(flt(row.total) * (1 if row.tipo == "Ingreso" else -1) for row in history)
    grouped = {}
    for row in rows:
        key = (row.fecha_de_registro, row.sucursal, row.vinculado)
        entry = grouped.setdefault(key, dict(fecha=row.fecha_de_registro, sucursal=row.sucursal,
            estado=_("Cerrado") if row.vinculado else _("Pendiente"), moneda=currency, ingresos=0, egresos=0))
        entry["ingresos" if row.tipo == "Ingreso" else "egresos"] += flt(row.total)
    data = []
    for key in sorted(grouped):
        entry = grouped[key]
        entry["neto"] = entry["ingresos"] - entry["egresos"]
        balance += entry["neto"]
        entry["saldo_acumulado"] = balance
        data.append(entry)
    chart = {"type": "axis-mixed", "colors": ["#28a745", "#dc3545", "#007bff"], "data": {
        "labels": [f"{row['fecha']} / {row['sucursal']} ({row['estado']})" for row in data],
        "datasets": [{"name": _(label) + " (" + currency + ")", "values": [row[key] for row in data], "chartType": kind}
            for key, label, kind in [("ingresos", "Ingresos", "bar"), ("egresos", "Egresos", "bar"), ("saldo_acumulado", "Saldo Acumulado", "line")]]}}
    return columns, data, None, chart
