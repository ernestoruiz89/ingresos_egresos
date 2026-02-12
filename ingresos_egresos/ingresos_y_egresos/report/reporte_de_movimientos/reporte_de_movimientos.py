# Copyright (c) 2024, Ernesto Ruiz and contributors
# For license information, please see license.txt

import frappe

def execute(filters=None):
    filters = filters or {}

    # Validar filtros
    fecha_inicio = filters.get("fecha_inicio")
    fecha_final = filters.get("fecha_final")
    sucursal = filters.get("sucursal")

    if not fecha_inicio or not fecha_final:
        frappe.throw("Debe seleccionar una fecha inicial y una fecha final.")

    # Crear filtros dinámicos
    condiciones = {
        "fecha_de_registro": ["between", [fecha_inicio, fecha_final]]
    }

    if sucursal:
        condiciones["sucursal"] = sucursal

    # Obtener movimientos utilizando frappe.get_all
    movimientos = frappe.get_all(
        "Movimiento",
        filters=condiciones,
        fields=[
            "name as movimiento",
            "sucursal",
            "fecha_de_registro",
            "tipo",
            "clasificacion",
            "referencia",
            "importe",
            "descripcion"
        ],
        order_by="fecha_de_registro ASC"
    )

    # Definir columnas del reporte
    columns = [
        {"label": "Movimiento", "fieldname": "movimiento", "fieldtype": "Link", "options": "Movimiento", "width": 150},
        {"label": "Sucursal", "fieldname": "sucursal", "fieldtype": "Link", "options": "Branch", "width": 120},
        {"label": "Fecha de Registro", "fieldname": "fecha_de_registro", "fieldtype": "Date", "width": 120},
        {"label": "Tipo", "fieldname": "tipo", "fieldtype": "Data", "width": 100},
        {"label": "Clasificación", "fieldname": "clasificacion", "fieldtype": "Data", "width": 120},
        {"label": "Referencia", "fieldname": "referencia", "fieldtype": "Data", "width": 200},
        {"label": "Importe", "fieldname": "importe", "fieldtype": "Currency", "width": 120},
        {"label": "Descripción", "fieldname": "descripcion", "fieldtype": "Text", "width": 200},
    ]

    return columns, movimientos
