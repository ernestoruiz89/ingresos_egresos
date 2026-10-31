"""Server-side guards also cover Desk forms and REST, not only the POS buttons."""
from hashlib import sha256
import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime, getdate
from ingresos_egresos import pos


def validate_configuration(doc):
    pos.lock_configuration()
    profiles = [row.pos_profile for row in doc.perfiles_pos]
    if len(profiles) != len(set(profiles)):
        frappe.throw(_("Cada perfil POS debe vincularse a una sola sucursal."))
    old = sorted((row.pos_profile,row.sucursal) for row in pos.current_rows("IE Perfil POS",
        filters={"parent":"IE Configuracion"},fields=["pos_profile","sucursal"]))
    new = sorted((row.pos_profile,row.sucursal) for row in doc.perfiles_pos)
    if pos.enabled()==cint(doc.integrar_pos) and old==new:
        return
    if doc.integrar_pos and not profiles:
        frappe.throw(_("Configure al menos un perfil POS y su sucursal."))
    if pos.current_rows("POS Opening Entry",filters={"docstatus":1,"status":"Open"},limit=1):
        frappe.throw(_("Cierre todos los POS antes de modificar la integración."))
    if pos.current_rows(pos.TURN,filters={"estado":["not in",[pos.CLOSED,pos.CANCELLED]]},limit=1):
        frappe.throw(_("Hay turnos integrados pendientes. Termine sus cierres antes de cambiar la configuración."))
    branches = {branch for _,branch in old+new}
    if branches and pos.current_rows("Movimiento",filters={"sucursal":["in",list(branches)],"docstatus":["<",2],"vinculado":0},limit=1):
        frappe.throw(_("Cierre los movimientos pendientes de las sucursales vinculadas antes de modificar la integración."))
    if doc.integrar_pos:
        pos.get_base_currency()


def before_opening_submit(doc, method=None):
    pos.lock_configuration()  # Serialize activation even when integration is currently off.
    if not pos.enabled(): return
    pos.require_operator()
    doc.period_start_date = get_datetime(doc.period_start_date).replace(microsecond=0)
    if doc.period_start_date>now_datetime():frappe.throw(_("La apertura no puede tener una fecha y hora futuras."))
    pos.lock_profile(doc.pos_profile)
    if pos.current_rows("POS Opening Entry",filters={"pos_profile":doc.pos_profile,"status":"Open","docstatus":1,"name":["!=",doc.name]},limit=1):
        frappe.throw(_("El perfil ya tiene un POS abierto."))
    pending=frappe.db.sql("""SELECT name FROM `tabIE Turno POS` WHERE pos_profile=%s
        AND estado NOT IN ('Cerrado','Cancelado') LIMIT 1 FOR UPDATE""",doc.pos_profile)
    if pending:
        frappe.throw(_("El turno {0} todavía no tiene ambos cierres completos.").format(pending[0][0]))
    branch=mapped_branch(doc.pos_profile)
    if not branch: frappe.throw(_("Configure la sucursal de este perfil POS en IE Configuración."))
    scope=frappe.get_doc(dict(doctype=pos.TURN,__islocal=1,sucursal=branch,
        pos_profile=doc.pos_profile,company=doc.company,cajero=doc.user))
    if not frappe.permissions.has_user_permission(scope,user=frappe.session.user):
        frappe.throw(_("La sucursal o empresa del perfil está fuera de sus permisos."),frappe.PermissionError)
    if not pos.profile_accessible(doc.pos_profile):
        frappe.throw(_("No tiene acceso a este perfil POS."),frappe.PermissionError)
    allowed=frappe.get_all("POS Profile User",filters={"parent":doc.pos_profile},pluck="user")
    if allowed and doc.user not in allowed:
        frappe.throw(_("El cajero no está autorizado para este perfil POS."),frappe.PermissionError)
    if doc.user != frappe.session.user and not pos.supervisor():
        frappe.throw(_("Solo puede abrir su propio turno."),frappe.PermissionError)


def on_opening_submit(doc, method=None):
    if not pos.enabled(): return
    branch=mapped_branch(doc.pos_profile)
    company_currency=frappe.db.get_value("Company",doc.company,"default_currency")
    base=pos.get_base_currency()
    rate=pos.exchange_rate(company_currency,base,doc.period_start_date)
    modes=set();funds=[]
    for row in doc.balance_details:
        if row.mode_of_payment in modes: frappe.throw(_("No repita medios de pago en la apertura."))
        modes.add(row.mode_of_payment)
        funds.append(dict(medio_pago=row.mode_of_payment,moneda=company_currency,importe=flt(row.opening_amount),
                          importe_base=flt(flt(row.opening_amount)*rate,pos.precision())))
    with pos.internal_operation():
        frappe.get_doc(dict(doctype=pos.TURN,pos_opening_entry=doc.name,pos_profile=doc.pos_profile,
            sucursal=branch,company=doc.company,cajero=doc.user,fecha_inicio=doc.period_start_date,estado=pos.OPEN,
            moneda_empresa=company_currency,moneda_base=base,tasa_empresa_base=rate,
            tipo_factura=frappe.db.get_single_value("POS Settings","invoice_type"),
            fondos_apertura=frappe.as_json(funds), medios_pago=frappe.as_json(sorted(set(
                frappe.get_all("POS Payment Method",filters={"parent":doc.pos_profile},pluck="mode_of_payment")))))).insert(ignore_permissions=True)


def before_opening_cancel(doc, method=None):
    if not frappe.db.exists(pos.TURN,doc.name):return
    turn=pos.lock_turn(doc.name)
    pos.check_scope(turn)
    if turn.estado != pos.OPEN or frappe.db.exists("Movimiento",{"turno_pos":turn.name,"docstatus":["<",2]}):
        frappe.throw(_("La apertura integrada tiene operaciones o cierres; utilice el cierre conjunto."))


def on_opening_cancel(doc, method=None):
    if frappe.db.exists(pos.TURN,doc.name):
        turn=pos.lock_turn(doc.name);pos.set_state(turn,pos.CANCELLED);pos.publish(turn)


def opening_updated(doc, method=None):
    if frappe.db.exists(pos.TURN,doc.name): pos.enqueue_reconcile(doc)


def is_pos_source(doc):
    return doc.doctype=="POS Invoice" or (
        cint(doc.get("is_pos")) and cint(doc.get("is_created_using_pos")) and not cint(doc.get("is_consolidated")))


def invoice_before_submit(doc, method=None):
    if not is_pos_source(doc) or not pos.enabled():return
    names=frappe.get_all(pos.TURN,filters={"pos_profile":doc.pos_profile,"cajero":doc.owner,"estado":pos.OPEN},pluck="name")
    if len(names)!=1:frappe.throw(_("No hay un turno integrado abierto para esta factura y cajero."))
    turn=pos.lock_turn(names[0]);pos.check_scope(turn);pos.assert_open(turn)
    stamp=get_datetime(f"{doc.posting_date} {doc.posting_time or '00:00:00'}")
    if stamp<get_datetime(turn.fecha_inicio) or stamp>now_datetime():
        frappe.throw(_("La fecha y hora de la factura deben pertenecer al turno POS actual."))
    doc.custom_ie_turno_pos=turn.name


def invoice_on_submit(doc, method=None):
    if not is_pos_source(doc) or not doc.get("custom_ie_turno_pos"):return
    turn=pos.lock_turn(doc.custom_ie_turno_pos);pos.assert_open(turn)
    from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import get_change_payment_row
    payments=[frappe._dict(row.as_dict()) for row in doc.payments]
    if flt(doc.change_amount):
        row=get_change_payment_row(payments,doc.get("account_for_change_amount"))
        if not row:frappe.throw(_("No se encontró el medio de pago del vuelto."))
        row.amount=flt(row.amount)-flt(doc.change_amount)
        row.base_amount=flt(row.base_amount)-flt(doc.base_change_amount)
    rate=flt(doc.conversion_rate) if turn.moneda_base==turn.moneda_empresa else pos.exchange_rate(doc.currency,turn.moneda_base,doc.posting_date)
    for index,row in enumerate(payments):
        amount=flt(row.amount)
        if not amount:continue
        key=sha256(f"invoice|{doc.doctype}|{doc.name}|{row.name or index}".encode()).hexdigest()
        if frappe.db.exists("Movimiento",{"clave_origen_pos":key}):continue
        incoming=amount>0
        pos.insert_movement(turn,dict(tipo="Ingreso" if incoming else "Egreso",clasificacion="Ventas POS" if incoming else "Devoluciones POS",
            importe=abs(amount),moneda=doc.currency,tasa_de_cambio=rate,tasa_empresa=flt(doc.conversion_rate),
            importe_empresa=abs(flt(row.base_amount)),medio_pago=row.mode_of_payment,
            origen_pos="Venta" if incoming else "Devolucion",documento_origen_tipo=doc.doctype,documento_origen=doc.name,
            referencia=doc.name,descripcion=_("Cobro POS") if incoming else _("Devolución POS"),
            fecha_operacion=now_datetime(),clave_origen_pos=key))


def invoice_before_cancel(doc, method=None):
    original=frappe.db.get_value(doc.doctype,doc.name,"custom_ie_turno_pos")
    if not original:return
    if original!=doc.get("custom_ie_turno_pos"):
        frappe.throw(_("No se puede desvincular una factura de su turno POS."))
    turn=pos.lock_turn(original);pos.check_scope(turn);pos.assert_open(turn)


def invoice_on_cancel(doc, method=None):
    if not doc.get("custom_ie_turno_pos"):return
    frappe.db.sql("""UPDATE `tabMovimiento` SET docstatus=2 WHERE turno_pos=%s
        AND documento_origen_tipo=%s AND documento_origen=%s AND origen_pos IN ('Venta','Devolucion')""",
        (doc.custom_ie_turno_pos,doc.doctype,doc.name))


def closing_guard(doc, method=None):
    opening=frappe.db.get_value("POS Closing Entry",doc.name,"pos_opening_entry") or doc.pos_opening_entry
    if not frappe.db.exists(pos.TURN,opening):return
    if not frappe.flags.ie_pos_internal:
        frappe.throw(_("Utilice Cierre conjunto o Anular cierre conjunto de Ingresos y Egresos."))
    if method == "before_cancel":
        doc.ignore_linked_doctypes = [pos.CLOSURE, pos.TURN]


def profile_before_save(doc, method=None):
    if doc.is_new() or not pos.current_rows(pos.TURN,filters={"pos_profile":doc.name,"estado":["not in",[pos.CLOSED,pos.CANCELLED]]},limit=1):return
    old=frappe.get_doc("POS Profile",doc.name,for_update=True)
    changed=any(old.get(key)!=doc.get(key) for key in ("company","currency"))
    changed=changed or sorted(row.mode_of_payment for row in old.payments)!=sorted(row.mode_of_payment for row in doc.payments)
    if changed:frappe.throw(_("No cambie la empresa, moneda o medios de pago de un perfil con turnos pendientes."))


def opening_before_update(doc, method=None):
    if not frappe.db.exists(pos.TURN,doc.name):return
    turn=pos.lock_turn(doc.name)
    old=frappe.get_doc("POS Opening Entry",doc.name)
    immutable=any(doc.get(key)!=old.get(key) for key in ("pos_profile","company","user"))
    immutable=immutable or get_datetime(doc.period_start_date)!=get_datetime(old.period_start_date)
    immutable=immutable or sorted((r.mode_of_payment,flt(r.opening_amount)) for r in doc.balance_details)!=sorted((r.mode_of_payment,flt(r.opening_amount)) for r in old.balance_details)
    if immutable:frappe.throw(_("La configuración y los fondos de un turno integrado son inmutables."))
    if doc.status==old.status and doc.pos_closing_entry==old.pos_closing_entry:return
    pce=frappe.get_doc("POS Closing Entry",turn.pos_closing_entry) if turn.pos_closing_entry else None
    closing=(pce and pce.docstatus==1 and pce.status=="Submitted" and doc.status=="Closed"
             and doc.pos_closing_entry==pce.name and turn.operacion=="Cierre")
    reopening=(pce and pce.docstatus==2 and pce.status=="Cancelled" and doc.status=="Open"
               and not doc.pos_closing_entry and turn.operacion=="Anulacion")
    if not (closing or reopening):frappe.throw(_("El estado de la apertura solo cambia mediante el cierre conjunto."))


def closing_before_update(doc, method=None):
    if frappe.db.exists(pos.TURN,doc.pos_opening_entry) and not frappe.flags.ie_pos_internal:
        frappe.throw(_("El cierre integrado solo se actualiza mediante el proceso conjunto."))


def mapped_branch(profile):
    rows=frappe.db.sql("""SELECT sucursal FROM `tabIE Perfil POS`
        WHERE parent='IE Configuracion' AND parenttype='IE Configuracion' AND pos_profile=%s FOR UPDATE""",profile)
    return rows[0][0] if rows else None


def settings_before_save(doc, method=None):
    pos.lock_configuration()
    if doc.invoice_type != frappe.db.get_single_value("POS Settings","invoice_type",cache=False):
        if pos.current_rows(pos.TURN,filters={"estado":["not in",[pos.CLOSED,pos.CANCELLED]]},limit=1):
            frappe.throw(_("No cambie el modo de facturación mientras existan turnos integrados pendientes."))


def invoice_before_update(doc, method=None):
    old=frappe.get_doc(doc.doctype,doc.name,for_update=True)
    opening=old.get("custom_ie_turno_pos")
    if not opening:return
    if doc.get("custom_ie_turno_pos")!=opening:
        frappe.throw(_("No se puede desvincular una factura de su turno POS."))
    fields=("company","pos_profile","owner","posting_date","posting_time","currency","conversion_rate",
        "grand_total","base_grand_total","paid_amount","base_paid_amount","change_amount","base_change_amount","is_return","return_against")
    payment_fields=("name","mode_of_payment","account","amount","base_amount")
    item_fields=("name","item_code","qty","rate","amount","base_amount")
    def rows(source,table,keys):return [tuple(row.get(key) for key in keys) for row in source.get(table,[])]
    changed=any(doc.get(key)!=old.get(key) for key in fields)
    changed=changed or rows(doc,"payments",payment_fields)!=rows(old,"payments",payment_fields)
    changed=changed or rows(doc,"items",item_fields)!=rows(old,"items",item_fields)
    if changed:
        frappe.throw(_("Los importes y pagos de una factura integrada son inmutables. Anule desde el turno abierto."))
