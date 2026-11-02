"""Currency rules shared by movements, closures and reports."""

from math import isfinite

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate


def multicurrency_allowed():
    rows = frappe.db.sql("SELECT value FROM `tabSingles` WHERE doctype='IE Configuracion' AND field='permitir_multimoneda'")
    # Sites being upgraded keep their existing behavior until model sync.
    return not rows or bool(cint(rows[0][0]))


def company_currency(sucursal=None, company=None, strict=True):
    if not company and sucursal:
        companies = set(frappe.get_all("IE Cuenta Caja", filters={"parent": "IE Configuracion",
            "parenttype": "IE Configuracion", "sucursal": sucursal}, pluck="company")) - {None, ""}
        companies.update(frappe.db.get_value("POS Profile", row.pos_profile, "company") for row in
            frappe.get_all("IE Perfil POS", filters={"parent": "IE Configuracion", "sucursal": sucursal}, fields=["pos_profile"]))
        companies.discard(None)
        if len(companies) > 1:
            if strict:
                frappe.throw(_("La sucursal {0} tiene varias compañías. Configure una sola compañía por sucursal para operar sin multimoneda.").format(sucursal))
            return None, None
        company = next(iter(companies), None)
    if not company:
        company = frappe.defaults.get_global_default("company") or frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        companies = frappe.get_all("Company", pluck="name", limit=2)
        company = companies[0] if len(companies) == 1 else None
    currency = frappe.get_cached_value("Company", company, "default_currency") if company else None
    if not currency and strict:
        frappe.throw(_("Configure la compañía predeterminada de ERPNext o la compañía de la sucursal en las cuentas de caja de IE Configuración."))
    return company, currency


def validate_movement_currency(doc):
    if multicurrency_allowed():
        return
    company = frappe.db.get_value("IE Turno POS", doc.turno_pos, "company") if doc.get("turno_pos") else None
    currency = company_currency(doc.sucursal, company=company)[1]
    if not doc.moneda:
        doc.moneda = currency
    if doc.moneda == currency:
        return
    # Closing or viewing a historical movement must never rewrite its units.
    if not doc.is_new():
        old = frappe.get_doc("Movimiento", doc.name)
        fields = ("sucursal", "moneda", "tipo")
        if (all(old.get(key) == doc.get(key) for key in fields)
                and getdate(old.fecha_de_registro) == getdate(doc.fecha_de_registro)
                and all(flt(old.get(key)) == flt(doc.get(key)) for key in ("importe", "tasa_de_cambio"))):
            return
    frappe.throw(_("Multimoneda está desactivada. Registre el movimiento en la moneda de la compañía: {0}.").format(currency))


def get_base_currency():
    currency = frappe.db.get_single_value("IE Configuracion", "moneda_base")
    if not currency:
        frappe.throw(_("Debe configurar la moneda base en IE Configuración."))
    return currency


def valid_rate(value):
    try:
        return isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


@frappe.whitelist()
def get_currency_settings(sucursal=None):
    frappe.has_permission("Movimiento", "read", throw=True)
    company, currency = company_currency(sucursal, strict=False)
    return {"moneda_base": get_base_currency(), "permitir_multimoneda": multicurrency_allowed(),
            "company": company, "moneda_empresa": currency}


@frappe.whitelist()
def get_rate(moneda, fecha_de_registro):
    frappe.has_permission("Movimiento", "read", throw=True)
    from erpnext.setup.utils import get_exchange_rate

    base = get_base_currency()
    rate = 1 if moneda == base else get_exchange_rate(moneda, base, getdate(fecha_de_registro))
    return {"moneda_base": base, "tasa_de_cambio": flt(rate) if valid_rate(rate) else None}


def calculate_amounts(moneda, rate, amount, date):
    base = get_base_currency()
    moneda = moneda or base
    if moneda == base:
        rate = 1
    elif rate in (None, "", 0, "0"):
        rate = get_rate(moneda, date)["tasa_de_cambio"]
    if not valid_rate(rate):
        frappe.throw(_("Debe indicar una tasa de cambio positiva y válida para {0}.").format(moneda))
    if not isfinite(flt(amount)):
        frappe.throw(_("El importe debe ser un número finito."))
    result = flt(amount) * float(rate)
    if not isfinite(result):
        frappe.throw(_("El importe convertido debe ser un número finito."))
    return moneda, float(rate), result


def get_balance(sucursal, moneda, before_date):
    """Include active drafts, as in dashboard period totals; never add currencies."""
    row = frappe.db.sql(
        """SELECT
            COALESCE(SUM(CASE WHEN tipo = 'Ingreso' THEN importe ELSE -importe END), 0) AS importe,
            COALESCE(SUM(CASE WHEN tipo = 'Ingreso' THEN importe_base ELSE -importe_base END), 0) AS importe_base
        FROM `tabMovimiento`
        WHERE sucursal = %s AND moneda = %s AND docstatus < 2 AND fecha_de_registro < %s
        AND COALESCE(turno_pos, '') = '' """,
        (sucursal, moneda, before_date), as_dict=True,
    )[0]
    return flt(row.importe), flt(row.importe_base)


def report_context(filters, start_key="from_date", end_key="to_date"):
    filters = filters or {}
    if not filters.get(start_key) or not filters.get(end_key):
        frappe.throw(_("Debe seleccionar una fecha inicial y una fecha final."))
    if getdate(filters[start_key]) > getdate(filters[end_key]):
        frappe.throw(_("La fecha inicial debe ser menor o igual a la fecha final."))
    currency = filters.get("moneda") or get_base_currency()
    # Without a currency filter all rows are consolidated using stored base amounts.
    field = "importe" if filters.get("moneda") else "importe_base"
    movement_filters = {"docstatus": ["<", 2], "fecha_de_registro": ["between", [filters[start_key], filters[end_key]]]}
    for key in ("sucursal", "moneda", "turno_pos"):
        if filters.get(key):
            movement_filters[key] = filters[key]
    return currency, field, movement_filters


def aggregate(function, field, alias):
    # Frappe v16 requires structured functions; v15 DatabaseQuery uses SQL fields.
    if int(frappe.__version__.split(".")[0]) >= 16:
        return {function.upper(): field, "as": alias}
    return f"{function}({field}) as {alias}"
