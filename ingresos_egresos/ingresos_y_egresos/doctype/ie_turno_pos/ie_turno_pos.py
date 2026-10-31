import frappe
from frappe import _
from frappe.model.document import Document


class IETurnoPOS(Document):
    def validate(self):
        if not frappe.flags.ie_pos_internal:
            frappe.throw(_("Los turnos se crean y actualizan desde el POS integrado."))

    def on_trash(self):
        frappe.throw(_("Los turnos POS conservan su historial y no pueden eliminarse."))


def has_permission(doc, user=None, permission_type=None, **kwargs):
    from ingresos_egresos import pos
    user=user or frappe.session.user
    roles=set(frappe.get_roles(user))
    if user=="Guest" or not roles & {"System Manager","IE Cajero POS","IE Supervisor POS"}:return False
    if doc is None:return True
    if user!="Administrator" and doc.cajero!=user and not roles & {"System Manager","IE Supervisor POS"}:return False
    return bool(pos.profile_accessible(doc.pos_profile,user=user) and
                frappe.permissions.has_user_permission(doc,user=user))


def get_permission_query_conditions(user=None):
    from ingresos_egresos import pos
    user=user or frappe.session.user
    if user=="Administrator":return ""
    roles=set(frappe.get_roles(user))
    if not roles & {"System Manager","IE Cajero POS","IE Supervisor POS"}:return "1=0"
    # DatabaseQuery also applies the turn's Branch and Company User Permissions.
    # Reading Branch itself would unnecessarily require an HR role.
    profiles=frappe.get_list("POS Profile",pluck="name",limit_page_length=0,user=user)
    profiles=[profile for profile in profiles if pos.profile_accessible(profile,user=user)]
    if not profiles:return "1=0"
    condition="`tabIE Turno POS`.pos_profile IN ({})".format(','.join(frappe.db.escape(v) for v in profiles))
    if not roles & {"System Manager","IE Supervisor POS"}:
        condition+=" AND `tabIE Turno POS`.cajero="+frappe.db.escape(user)
    return condition
