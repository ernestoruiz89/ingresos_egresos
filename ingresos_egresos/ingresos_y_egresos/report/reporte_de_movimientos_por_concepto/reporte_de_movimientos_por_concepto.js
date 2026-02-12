// Copyright (c) 2024, Ernesto Ruiz and contributors
// For license information, please see license.txt

frappe.query_reports["Reporte de Movimientos por Concepto"] = {
    "filters": [
        {
            "fieldname": "type",
            "label": __("Tipo Movimiento"),
            "fieldtype": "Select",
            "options": "\nIngreso\nEgreso",
            "default": "Egreso", // Por defecto salidas para ver gastos
            "reqd": 0
        },
        {
            "fieldname": "sucursal",
            "label": __("Sucursal"),
            "fieldtype": "Link",
            "options": "Branch",
            "reqd": 0
        },
        {
            "fieldname": "from_date",
            "label": __("Fecha Inicial"),
            "fieldtype": "Date",
            "default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
            "reqd": 1
        },
        {
            "fieldname": "to_date",
            "label": __("Fecha Final"),
            "fieldtype": "Date",
            "default": frappe.datetime.get_today(),
            "reqd": 1
        }
    ]
};
