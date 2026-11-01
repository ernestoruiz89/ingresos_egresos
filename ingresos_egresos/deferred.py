"""Monthly recognition of direct cash movements, using native Journal Entries."""
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, get_first_day, get_last_day, getdate, nowdate

INPUT_FIELDS = ("es_diferido", "inicio_diferimiento", "meses_diferimiento")
PLAN = "IE Diferimiento"


def error_message(error):
    return str(error) or (_("Revise los permisos del usuario que autorizó el calendario.")
        if isinstance(error, frappe.PermissionError) else _("No fue posible procesar el calendario: {0}.").format(type(error).__name__))


def validate_movement(doc):
    if not doc.get("es_diferido"):
        return
    if doc.es_activo or doc.tipo not in ("Ingreso", "Egreso") or doc.origen_pos in ("Venta", "Devolucion"):
        frappe.throw(_("El diferimiento solo se aplica a ingresos o egresos manuales y no puede combinarse con un activo fijo."))
    if not doc.inicio_diferimiento or getdate(doc.inicio_diferimiento) < getdate(doc.fecha_de_registro):
        frappe.throw(_("El inicio del diferimiento debe ser igual o posterior a la fecha del movimiento."))
    if not 1 <= cint(doc.meses_diferimiento) <= 120 or flt(doc.meses_diferimiento) != cint(doc.meses_diferimiento):
        frappe.throw(_("Indique entre 1 y 120 meses para el diferimiento."))


def default_account(company, kind):
    field = "default_deferred_revenue_account" if kind == "Ingreso" else "default_deferred_expense_account"
    return frappe.get_cached_value("Company", company, field)


def prepare(doc, plan, options):
    if not doc.get("es_diferido"):
        return
    validate_movement(doc)
    from ingresos_egresos.accounting import account_details
    name = options.get("cuenta_diferida") or default_account(plan["company"], doc.tipo)
    plan.update(es_diferido=True, cuenta_diferida=name, inicio_diferimiento=doc.inicio_diferimiento,
        meses_diferimiento=doc.meses_diferimiento)
    if not name:
        plan["faltantes"].append("cuenta_diferida")
    else:
        account = account_details(name, plan["company"])
        account.check_permission("read")
        root = "Liability" if doc.tipo == "Ingreso" else "Asset"
        if account.root_type != root or account.report_type != "Balance Sheet" or account.account_type in (
            "Cash", "Bank", "Receivable", "Payable", "Fixed Asset", "Stock", "Accumulated Depreciation"
        ) or account.currency != plan["moneda_empresa"]:
            frappe.throw(_("La cuenta diferida debe ser de balance, de {0}, y usar la moneda de la empresa.").format(_("pasivo") if root == "Liability" else _("activo")))
    if plan.get("cuenta_contrapartida"):
        result = account_details(plan["cuenta_contrapartida"], plan["company"])
        if result.root_type != plan["raiz_cuenta"] or result.report_type != "Profit and Loss" or result.currency != plan["moneda_empresa"]:
            frappe.throw(_("La cuenta a reconocer debe ser de ingreso o gasto, según el movimiento, y usar la moneda de la empresa."))


def schedule(start, months, amount, precision=2):
    quantum = Decimal(1).scaleb(-precision)
    total = Decimal(str(amount)).quantize(quantum, rounding=ROUND_HALF_UP)
    part = (total / months).quantize(quantum, rounding=ROUND_HALF_UP)
    if part <= 0 or total - part * (months - 1) <= 0:
        frappe.throw(_("El importe es demasiado pequeño para el número de meses. Reduzca los períodos."))
    first = get_first_day(start)
    return [dict(numero=i + 1, fecha=get_last_day(add_months(first, i)),
        importe=float(part if i < months - 1 else total - part * (months - 1)), estado="Pendiente") for i in range(months)]


def create_plan(doc, plan, journal):
    calendar = frappe.get_doc(dict(doctype=PLAN, movimiento=doc.name, asiento_inicial=journal.name,
        company=plan["company"], sucursal=doc.sucursal, turno_pos=doc.turno_pos, tipo=doc.tipo,
        moneda=plan["moneda_empresa"], importe=journal.total_debit, importe_reconocido=0,
        importe_pendiente=journal.total_debit, cuenta_diferida=plan["cuenta_diferida"],
        cuenta_resultado=plan["cuenta_contrapartida"], centro_de_costos=plan["centro_de_costos"],
        fecha_inicio=doc.inicio_diferimiento, meses=doc.meses_diferimiento, estado="Activo",
        autorizado_por=frappe.session.user))
    for row in schedule(doc.inicio_diferimiento, cint(doc.meses_diferimiento), journal.total_debit,
                        cint(frappe.get_system_settings("currency_precision") or 2)):
        calendar.append("cuotas", dict(**row, moneda=plan["moneda_empresa"]))
    calendar.insert(ignore_permissions=True)
    return calendar.name


def locked_plan(name):
    from ingresos_egresos.accounting import movement, require_posting_permissions
    from ingresos_egresos.pos import lock_configuration
    require_posting_permissions()
    lock_configuration()
    # Same lock order as posting and cancellation: configuration, movement, plan.
    source_name = frappe.db.get_value(PLAN, name, "movimiento")
    if not source_name:
        frappe.throw(_("No existe el calendario solicitado."), frappe.DoesNotExistError)
    source = movement(source_name, lock=True)
    plan = frappe.get_doc(PLAN, name, for_update=True)
    if source.diferimiento != name or source.asiento_contable != plan.asiento_inicial or source.estado_contable != "Contabilizado":
        frappe.throw(_("Este calendario no corresponde a una contabilización vigente."))
    return plan


def totals(plan, state=None):
    recognized = flt(sum(row.importe for row in plan.cuotas if row.estado == "Contabilizado"),
        cint(frappe.get_system_settings("currency_precision") or 2))
    pending = flt(plan.importe - recognized, cint(frappe.get_system_settings("currency_precision") or 2))
    values = dict(importe_reconocido=recognized, importe_pendiente=pending,
        estado=state or ("Completado" if not pending else "Activo"))
    frappe.db.set_value(PLAN, plan.name, values)
    plan.update(values)
    plan.notify_update()


def process_locked(plan):
    from ingresos_egresos.accounting import account_details, internal_posting, validate_cost_center
    if plan.estado in ("Anulado", "Pausado", "Completado"):
        return []
    for name in (plan.cuenta_diferida, plan.cuenta_resultado):
        account = account_details(name, plan.company)
        account.check_permission("read")
        if account.currency != plan.moneda:
            frappe.throw(_("Las cuentas del calendario deben conservar la moneda de la empresa."))
        expected = ("Asset" if plan.tipo == "Egreso" else "Liability") if name == plan.cuenta_diferida else ("Expense" if plan.tipo == "Egreso" else "Income")
        if account.root_type != expected:
            frappe.throw(_("La naturaleza de las cuentas del calendario cambió. Revise su configuración."))
    validate_cost_center(plan.centro_de_costos, plan.company, permissions=True)
    posted = []
    for row in plan.cuotas:
        if row.estado == "Contabilizado" or getdate(row.fecha) > getdate(nowdate()):
            continue
        expense = plan.tipo == "Egreso"
        accounts = [dict(account=plan.cuenta_diferida, debit_in_account_currency=0 if expense else row.importe,
                         credit_in_account_currency=row.importe if expense else 0),
                    dict(account=plan.cuenta_resultado, debit_in_account_currency=row.importe if expense else 0,
                         credit_in_account_currency=0 if expense else row.importe, cost_center=plan.centro_de_costos)]
        journal = frappe.get_doc(dict(doctype="Journal Entry", voucher_type="Journal Entry", company=plan.company,
            posting_date=row.fecha, custom_ie_diferimiento=plan.name, custom_ie_cuota=row.name,
            user_remark=_("Reconocimiento mensual {0}, cuota {1}, movimiento {2}").format(plan.name, row.numero, plan.movimiento),
            accounts=accounts))
        with internal_posting():
            journal.insert(); journal.submit()
        row.update(dict(estado="Contabilizado", asiento_contable=journal.name))
        frappe.db.set_value(row.doctype, row.name, {"estado": row.estado, "asiento_contable": journal.name}, update_modified=False)
        posted.append(journal.name)
    frappe.db.set_value(PLAN, plan.name, "ultimo_error", None, update_modified=False)
    totals(plan)
    return posted


@frappe.whitelist(methods=["POST"])
def process(name):
    plan = locked_plan(name)
    frappe.db.savepoint("ie_deferred_process")
    previous_messages = len(frappe.message_log)
    try:
        return dict(status="posted", asientos=process_locked(plan))
    except Exception as error:
        frappe.db.rollback(save_point="ie_deferred_process")
        del frappe.message_log[previous_messages:]
        # Persist an actionable error while leaving the financial batch atomic.
        message = error_message(error)
        frappe.db.set_value(PLAN, name, "ultimo_error", message)
        return dict(status="error", error=message)


@frappe.whitelist(methods=["POST"])
def set_paused(name, paused):
    plan = locked_plan(name)
    if plan.estado == "Anulado":
        frappe.throw(_("No se puede reactivar un calendario anulado."))
    totals(plan, "Pausado" if cint(paused) else None)
    return plan.estado


def process_due():
    if not cint(frappe.db.get_single_value("IE Configuracion", "procesar_diferidos_automaticamente")):
        return
    previous_user = frappe.session.user
    names = frappe.db.sql("""SELECT DISTINCT p.name, p.autorizado_por, p.modified
        FROM `tabIE Diferimiento` p INNER JOIN `tabIE Cuota Diferida` c
        ON c.parent=p.name AND c.parenttype='IE Diferimiento' AND c.parentfield='cuotas'
        WHERE p.estado='Activo' AND c.estado!='Contabilizado' AND c.fecha<=%s
        ORDER BY p.modified ASC LIMIT 100""", nowdate(), as_dict=True)
    try:
        for row in names:
            frappe.db.savepoint("ie_deferred_automatic")
            try:
                if not frappe.get_cached_value("User", row.autorizado_por, "enabled"):
                    frappe.throw(_("El usuario que autorizó el calendario está deshabilitado."), frappe.PermissionError)
                frappe.set_user(row.autorizado_por)
                process(row.name)
            except Exception as error:
                frappe.db.rollback(save_point="ie_deferred_automatic")
                frappe.db.set_value(PLAN, row.name, "ultimo_error", error_message(error))
            if not frappe.in_test:
                frappe.db.commit()
    finally:
        frappe.set_user(previous_user)


def journal_plan(doc):
    if not doc.meta.has_field("custom_ie_diferimiento"):
        return None
    old = frappe.db.get_value("Journal Entry", doc.name, ["custom_ie_diferimiento", "custom_ie_cuota"], as_dict=True) if not doc.is_new() else None
    if doc.get("custom_ie_diferimiento") and not (old and old.custom_ie_diferimiento) and not frappe.flags.ie_accounting_internal:
        frappe.throw(_("Los reconocimientos se crean únicamente desde el calendario de diferimiento."))
    if doc.get("custom_ie_cuota") and not doc.get("custom_ie_diferimiento"):
        frappe.throw(_("La cuota requiere su calendario de diferimiento."))
    if old and old.custom_ie_diferimiento and (old.custom_ie_diferimiento != doc.get("custom_ie_diferimiento") or old.custom_ie_cuota != doc.get("custom_ie_cuota")):
        frappe.throw(_("No se puede desvincular una cuota de su calendario."))
    return doc.get("custom_ie_diferimiento")


def before_recognition_cancel(doc):
    plan = locked_plan(doc.custom_ie_diferimiento)
    row = next((row for row in plan.cuotas if row.name == doc.custom_ie_cuota and row.asiento_contable == doc.name), None)
    if not row or row.estado != "Contabilizado":
        frappe.throw(_("El asiento no es el reconocimiento vigente de esta cuota."))
    if any(other.estado == "Contabilizado" and other.numero > row.numero for other in plan.cuotas):
        frappe.throw(_("Anule primero las cuotas posteriores de este calendario."))
    doc.ignore_linked_doctypes = (PLAN, "IE Cuota Diferida")


def after_recognition_cancel(doc):
    plan = frappe.get_doc(PLAN, doc.custom_ie_diferimiento, for_update=True)
    for row in plan.cuotas:
        if row.name == doc.custom_ie_cuota and row.asiento_contable == doc.name:
            row.estado = "Anulado"
            frappe.db.set_value(row.doctype, row.name, "estado", "Anulado", update_modified=False)
            totals(plan, "Pausado")
            break


def cancel_for_journal(source):
    if not source.get("diferimiento"):
        return
    plan = frappe.get_doc(PLAN, source.diferimiento, for_update=True)
    if any(row.estado == "Contabilizado" for row in plan.cuotas):
        frappe.throw(_("Anule primero los asientos de las cuotas del diferimiento, desde la última hacia la primera."))
    frappe.db.set_value(PLAN, plan.name, "estado", "Anulado")
    plan.notify_update()


def has_permission(doc, user=None, permission_type=None, **kwargs):
    if doc is None or permission_type != "read":
        return None
    source = frappe.get_doc("Movimiento", doc.movimiento)
    if not frappe.has_permission("Movimiento", "read", doc=source, user=user):
        return False
    if source.turno_pos and not frappe.has_permission("IE Turno POS", "read", doc=source.turno_pos, user=user):
        return False
    return None


def get_permission_query_conditions(user=None):
    from frappe.desk.reportview import build_match_conditions
    from ingresos_egresos.ingresos_y_egresos.doctype.ie_turno_pos.ie_turno_pos import get_permission_query_conditions as turn_conditions
    if not frappe.has_permission("Movimiento", "read", user=user):
        return "1=0"
    source = build_match_conditions("Movimiento", user=user) or "1=1"
    turn = " AND ".join(f"({condition})" for condition in
        (build_match_conditions("IE Turno POS", user=user), turn_conditions(user)) if condition) or "1=1"
    return ("`tabIE Diferimiento`.movimiento IN (SELECT name FROM `tabMovimiento` WHERE (" + source + ") "
        "AND (COALESCE(turno_pos, '')='' OR turno_pos IN (SELECT name FROM `tabIE Turno POS` WHERE " + turn + ")))" )
