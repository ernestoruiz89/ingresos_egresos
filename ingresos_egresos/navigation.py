"""Visibility for the app entry in the Frappe v16 desktop."""

import frappe
from frappe.utils.user import is_website_user


def has_app_permission():
    if frappe.session.user == "Guest" or is_website_user():
        return False
    return any(
        frappe.has_permission(doctype, "read")
        for doctype in (
            "Movimiento",
            "IE Turno POS",
            "Registro de Cierre de Movimiento",
            "IE Configuracion",
            "IE Codigo",
        )
    )
