# Copyright (c) 2024, Ernesto Ruiz and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from ingresos_egresos.currency import get_base_currency, report_context


def execute(filters=None):
    filters = filters or {}

    report_filters = report_context(filters, "fecha_inicio", "fecha_final")[2]
    base = get_base_currency()

    movements = frappe.get_list(
        "Movimiento",
        filters=report_filters,
        fields=[
            "name as movimiento",
            "sucursal",
            "fecha_de_registro",
            "tipo",
            "clasificacion",
            "referencia",
            "moneda",
            "importe",
            "tasa_de_cambio",
            "importe_base",
            "descripcion",
            "vinculado", "turno_pos", "fecha_operacion", "medio_pago", "origen_pos",
        ],
        order_by="fecha_de_registro ASC",
        limit_page_length=0,
    )

    columns = [
        {"label": _("Movimiento"), "fieldname": "movimiento", "fieldtype": "Link", "options": "Movimiento", "width": 150},
        {"label": _("Sucursal"), "fieldname": "sucursal", "fieldtype": "Link", "options": "Branch", "width": 120},
        {"label": _("Fecha de Registro"), "fieldname": "fecha_de_registro", "fieldtype": "Date", "width": 120},
        {"label": _("Tipo"), "fieldname": "tipo", "fieldtype": "Data", "width": 100},
        {"label": _("Clasificación"), "fieldname": "clasificacion", "fieldtype": "Data", "width": 120},
        {"label": _("Referencia"), "fieldname": "referencia", "fieldtype": "Data", "width": 150},
        {"label": _("Moneda"), "fieldname": "moneda", "fieldtype": "Link", "options": "Currency", "width": 80},
        {"label": _("Importe"), "fieldname": "importe", "fieldtype": "Currency", "options": "moneda", "width": 120},
        {"label": _("Tasa de Cambio"), "fieldname": "tasa_de_cambio", "fieldtype": "Float", "width": 100},
        {"label": _("Importe Base"), "fieldname": "importe_base", "fieldtype": "Currency", "options": "moneda_base", "width": 120},
        {"label": _("Estado"), "fieldname": "estado", "fieldtype": "Data", "width": 100},
        {"label": _("Descripción"), "fieldname": "descripcion", "fieldtype": "Text", "width": 200},
    ]

    columns.append({"label": _("Moneda Base"), "fieldname": "moneda_base", "fieldtype": "Link", "options": "Currency", "width": 90})
    columns.extend([
        {"label": _("Turno POS"), "fieldname": "turno_pos", "fieldtype": "Link", "options": "IE Turno POS", "width": 160},
        {"label": _("Fecha de operación"), "fieldname": "fecha_operacion", "fieldtype": "Datetime", "width": 160},
        {"label": _("Medio de pago"), "fieldname": "medio_pago", "fieldtype": "Link", "options": "Mode of Payment", "width": 120},
        {"label": _("Origen POS"), "fieldname": "origen_pos", "fieldtype": "Data", "width": 110},
    ])
    for movement in movements:
        movement["moneda_base"] = base
        movement["estado"] = _("Cerrado") if movement.get("vinculado") else _("Pendiente")

    return columns, movements
