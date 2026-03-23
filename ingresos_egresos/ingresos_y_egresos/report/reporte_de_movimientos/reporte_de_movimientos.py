# Copyright (c) 2024, Ernesto Ruiz and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
    filters = filters or {}

    start_date = filters.get("fecha_inicio")
    end_date = filters.get("fecha_final")
    branch = filters.get("sucursal")

    if not start_date or not end_date:
        frappe.throw(_("Debe seleccionar una fecha inicial y una fecha final."))

    report_filters = {"fecha_de_registro": ["between", [start_date, end_date]]}
    if branch:
        report_filters["sucursal"] = branch

    movements = frappe.get_all(
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
            "vinculado",
        ],
        order_by="fecha_de_registro ASC",
    )

    columns = [
        {"label": _("Movimiento"), "fieldname": "movimiento", "fieldtype": "Link", "options": "Movimiento", "width": 150},
        {"label": _("Sucursal"), "fieldname": "sucursal", "fieldtype": "Link", "options": "Branch", "width": 120},
        {"label": _("Fecha de Registro"), "fieldname": "fecha_de_registro", "fieldtype": "Date", "width": 120},
        {"label": _("Tipo"), "fieldname": "tipo", "fieldtype": "Data", "width": 100},
        {"label": _("Clasificación"), "fieldname": "clasificacion", "fieldtype": "Data", "width": 120},
        {"label": _("Referencia"), "fieldname": "referencia", "fieldtype": "Data", "width": 150},
        {"label": _("Moneda"), "fieldname": "moneda", "fieldtype": "Link", "options": "Currency", "width": 80},
        {"label": _("Importe"), "fieldname": "importe", "fieldtype": "Currency", "width": 120},
        {"label": _("Tasa de Cambio"), "fieldname": "tasa_de_cambio", "fieldtype": "Float", "width": 100},
        {"label": _("Importe Base"), "fieldname": "importe_base", "fieldtype": "Currency", "width": 120},
        {"label": _("Estado"), "fieldname": "estado", "fieldtype": "Data", "width": 100},
        {"label": _("Descripción"), "fieldname": "descripcion", "fieldtype": "Text", "width": 200},
    ]

    for movement in movements:
        movement["estado"] = _("Cerrado") if movement.get("vinculado") else _("Pendiente")

    return columns, movements
