frappe.ui.form.on("IE Turno POS", {
    refresh(frm) {
        const load = () => frappe.require("/assets/ingresos_egresos/js/ie_pos_modals.js");
        // The modal library is also used outside the POS by authorized supervisors.
        frm.add_custom_button(__("Movimientos y saldos"), async () => {await load();frappe.ie_pos.report(frm.doc.name);});
        if (!["Abierto","Cancelado"].includes(frm.doc.estado)) {
            frm.add_custom_button(__("Ver cierre conjunto"),async () => {await load();frappe.ie_pos.closing(frm.doc.name);});
        }
        if (frm.doc.estado === "Cerrado" && frappe.user.has_role(["System Manager","IE Supervisor POS"])) {
            frm.add_custom_button(__("Anular cierre conjunto"),()=>frappe.confirm(__("¿Anular ambos cierres y reabrir este turno?"),async () => {
                await frappe.call({method:"ingresos_egresos.pos.cancel_closing",args:{opening:frm.doc.name},freeze:true});
                frm.reload_doc();
            }));
        }
    }
});
