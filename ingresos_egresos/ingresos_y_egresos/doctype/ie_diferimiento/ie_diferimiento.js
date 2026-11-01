frappe.ui.form.on("IE Diferimiento", {
    refresh(frm) {
        frm.disable_save();
        if (frm.doc.estado === "Anulado" || !frappe.model.can_create("Journal Entry") || !frappe.model.can_submit("Journal Entry")) return;
        if (frm.doc.estado === "Activo") {
            frm.add_custom_button(__("Contabilizar cuotas vencidas"), async () => {
                await frappe.confirm(__("Se contabilizarán las cuotas pendientes hasta la fecha del servidor. ¿Continuar?"), async () => {
                    const result = (await frappe.call({method: "ingresos_egresos.deferred.process", args: {name: frm.doc.name}, freeze: true})).message;
                    await frm.reload_doc();
                    if (result.status === "error") return frappe.msgprint({title: __("Revisar diferimiento"), message: frappe.utils.escape_html(result.error), indicator: "orange"});
                    frappe.show_alert({message: __("Asientos creados: {0}", [result.asientos.length]), indicator: "green"});
                });
            });
        }
        if (frm.doc.estado !== "Completado") {
            const paused = frm.doc.estado === "Pausado";
            frm.add_custom_button(paused ? __("Reanudar calendario") : __("Pausar calendario"), async () => {
                await frappe.call({method: "ingresos_egresos.deferred.set_paused", args: {name: frm.doc.name, paused: paused ? 0 : 1}});
                await frm.reload_doc();
            });
        }
        frm.set_intro(__("Las cuotas reconocen ingreso o gasto; no generan nuevos movimientos de caja. Anular una cuota pausa el calendario hasta reanudarlo."), "blue");
    }
});
