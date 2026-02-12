// Copyright (c) 2024, Ernesto Ruiz and contributors
// For license information, please see license.txt

frappe.query_reports["Reporte de Flujo de Caja"] = {
    "filters": [
        {
            "fieldname": "company",
            "label": __("Company"),
            "fieldtype": "Link",
            "options": "Company",
            "default": frappe.defaults.get_user_default("Company"),
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
    ],
    "formatter": function (value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (column.fieldname == "saldo_acumulado" && data && data.saldo_acumulado < 0) {
            value = "<span style='color:red!important; font-weight:bold;'>" + value + "</span>";
        } else if (column.fieldname == "saldo_acumulado" && data && data.saldo_acumulado > 0) {
            value = "<span style='color:green!important; font-weight:bold;'>" + value + "</span>";
        }
        return value;
    }
};
