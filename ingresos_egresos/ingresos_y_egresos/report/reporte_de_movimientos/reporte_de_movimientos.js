// Copyright (c) 2024, Ernesto Ruiz and contributors
// For license information, please see license.txt

frappe.query_reports["Reporte de Movimientos"] = {
	"filters": [
		{
			"fieldname": "fecha_inicio",
			"label": "Fecha Inicial",
			"fieldtype": "Date",
			"reqd": 1
		},
		{
			"fieldname": "fecha_final",
			"label": "Fecha Final",
			"fieldtype": "Date",
			"reqd": 1
		},
		{
			"fieldname": "sucursal",
			"label": "Sucursal",
			"fieldtype": "Link",
			"options": "Branch"
		}
	]
};


