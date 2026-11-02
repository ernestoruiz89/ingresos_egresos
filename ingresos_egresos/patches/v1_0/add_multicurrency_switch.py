"""Keep the historical multi-currency behavior when installing the new switch."""
import frappe


def execute():
    if not frappe.db.sql("SELECT value FROM `tabSingles` WHERE doctype='IE Configuracion' AND field='permitir_multimoneda'"):
        frappe.db.set_single_value("IE Configuracion", "permitir_multimoneda", 1)
