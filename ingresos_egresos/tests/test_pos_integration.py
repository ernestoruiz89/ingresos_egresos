from unittest.mock import patch
from datetime import timedelta

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime, nowdate, getdate

from ingresos_egresos import pos, pos_hooks


class TestPOSIntegration(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        # Emulate durable saga boundaries with savepoints, keeping each test reversible.
        frappe.db.rollback();frappe.db.value_cache.clear()
        self.real_rollback=frappe.db.rollback
        frappe.db.savepoint("ie_saga")
        self.commit_patch=patch.object(frappe.db,"commit",side_effect=lambda *a,**kw: frappe.db.savepoint("ie_saga"));self.commit_patch.start()
        self.addCleanup(self.commit_patch.stop)
        self.rollback_patch=patch.object(frappe.db,"rollback",side_effect=lambda save_point=None,**kw:self.real_rollback(save_point=save_point or "ie_saga"));self.rollback_patch.start()
        self.addCleanup(self.rollback_patch.stop)
        self.enqueue_patch=patch("frappe.enqueue",return_value=None);self.enqueue_patch.start()
        self.addCleanup(self.enqueue_patch.stop)
        self.company="_Test Company"
        if not frappe.db.exists("Company",self.company):
            frappe.get_doc(dict(doctype="Company",company_name=self.company,abbr="_TC",default_currency="INR",
                country="India",create_chart_of_accounts_based_on="Standard Template",chart_of_accounts="Standard")).insert()
        self.currency=frappe.db.get_value("Company",self.company,"default_currency")
        frappe.db.set_single_value("IE Configuracion","moneda_base",self.currency)
        frappe.db.set_single_value("IE Configuracion","integrar_pos",0)
        frappe.db.delete("IE Perfil POS",{"parent":"IE Configuracion"})
        frappe.db.set_single_value("POS Settings","invoice_type","POS Invoice")
        self.suffix=frappe.generate_hash(length=7)
        self.branch=frappe.get_doc(dict(doctype="Branch",branch="IE POS "+self.suffix)).insert().name
        self.cost_center=frappe.db.get_value("Cost Center",{"company":self.company,"is_group":0},"name")
        self.cash_account=frappe.db.get_value("Account",{"company":self.company,"account_type":"Cash","is_group":0},"name")
        self.income=frappe.db.get_value("Account",{"company":self.company,"root_type":"Income","is_group":0},"name")
        self.expense=frappe.db.get_value("Account",{"company":self.company,"root_type":"Expense","is_group":0},"name")
        for mode,kind in [("Cash","Cash"),("Credit Card","Bank")]:
            mop=frappe.get_doc("Mode of Payment",mode)
            account=self.cash_account if kind=="Cash" else frappe.db.get_value("Account",{"company":self.company,"account_type":"Bank","is_group":0},"name") or self.cash_account
            if not any(row.company==self.company for row in mop.accounts):mop.append("accounts",dict(company=self.company,default_account=account));mop.save()
        self.profile=self.make_profile()
        config=frappe.get_single("IE Configuracion");config.set("perfiles_pos",[])
        config.append("perfiles_pos",dict(pos_profile=self.profile,sucursal=self.branch));config.integrar_pos=1;config.save()

    def tearDown(self):
        self.enqueue_patch.stop();self.commit_patch.stop();self.rollback_patch.stop()
        frappe.set_user("Administrator");self.real_rollback();frappe.db.value_cache.clear()
        super().tearDown()

    def make_profile(self):
        doc=frappe.get_doc(dict(doctype="POS Profile",name="IE POS "+frappe.generate_hash(length=8),company=self.company,
            currency=self.currency,warehouse=frappe.db.get_value("Warehouse",{"company":self.company,"is_group":0},"name"),cost_center=self.cost_center,income_account=self.income,expense_account=self.expense,
            write_off_account=self.expense,write_off_cost_center=self.cost_center,account_for_change_amount=self.cash_account,
            selling_price_list="Standard Selling",update_stock=0,allow_partial_payment=1,
            payments=[dict(mode_of_payment="Cash",default=1),dict(mode_of_payment="Credit Card")]))
        return doc.insert().name

    def opening(self, profile=None, user="Administrator", amount=100, when=None):
        return frappe.get_doc(dict(doctype="POS Opening Entry",pos_profile=profile or self.profile,company=self.company,user=user,
            period_start_date=when or now_datetime(),balance_details=[dict(mode_of_payment="Cash",opening_amount=amount),
            dict(mode_of_payment="Credit Card",opening_amount=0)])).submit()

    def manual(self,opening,kind="Ingreso",amount=50,mode="Cash",currency=None,rate=1,request_id=None):
        return pos.register_movement(opening.name,kind,"Ventas POS" if kind=="Ingreso" else "Devoluciones POS",amount,
            currency or self.currency,mode,rate,rate,request_id=request_id or frappe.generate_hash(length=20))

    def close(self,opening):
        values=pos.report(opening.name)["esperado_empresa"]
        return pos.start_closing(opening.name,values)

    def fake_invoice(self,opening,amount=100,change=0,kind="POS Invoice",card=0):
        # Exercise the actual hook with authoritative payment rows; full invoices are tested separately.
        doc=frappe.get_doc(dict(doctype=kind,name="IE INV "+frappe.generate_hash(length=8),company=self.company,
            owner="Administrator",pos_profile=opening.pos_profile,custom_ie_turno_pos=opening.name,is_pos=1,is_created_using_pos=1,
            posting_date=nowdate(),posting_time=now_datetime().time(),currency=self.currency,conversion_rate=1,
            change_amount=change,base_change_amount=change,account_for_change_amount=self.cash_account,
            payments=[dict(name="cash-row",mode_of_payment="Cash",account=self.cash_account,type="Cash",amount=amount,base_amount=amount)]))
        if card:doc.append("payments",dict(name="card-row",mode_of_payment="Credit Card",account=self.cash_account,type="Bank",amount=card,base_amount=card))
        doc.db_insert()
        return doc

    def test_manual_and_funds_are_not_duplicated(self):
        opening=self.opening()
        one=self.manual(opening,request_id="same-request")
        self.assertEqual(one,self.manual(opening,request_id="same-request"))
        self.manual(opening,"Egreso",20)
        data=pos.report(opening.name)
        self.assertEqual((data["base"]["apertura"],data["base"]["ingresos"],data["base"]["saldo"]),(100,50,130))
        self.assertEqual(data["total"],2)

    def test_automatic_payments_change_refunds_and_idempotence(self):
        opening=self.opening()
        invoice=self.fake_invoice(opening,amount=100,change=20,card=30)
        pos_hooks.invoice_on_submit(invoice);pos_hooks.invoice_on_submit(invoice)
        refund=self.fake_invoice(opening,amount=-10);pos_hooks.invoice_on_submit(refund)
        data=pos.report(opening.name)
        self.assertEqual(data["base"]["ventas"],110)
        self.assertEqual(data["base"]["devoluciones"],10)
        self.assertEqual(data["base"]["saldo"],200)
        self.assertEqual(data["esperado_empresa"],{"Cash":170,"Credit Card":30})
        self.assertEqual(data["total"],3)

    def test_sales_invoice_mode_and_consolidation_ignored(self):
        opening=self.opening();invoice=self.fake_invoice(opening,kind="Sales Invoice")
        pos_hooks.invoice_on_submit(invoice)
        invoice.is_consolidated=1;invoice.custom_ie_turno_pos=None
        pos_hooks.invoice_on_submit(invoice)
        self.assertEqual(pos.report(opening.name)["total"],1)

    def test_manual_foreign_currency_and_company_amount(self):
        opening=self.opening();self.manual(opening,amount=10,currency="USD",rate=80)
        data=pos.report(opening.name)
        self.assertEqual(data["base"]["saldo"],900)
        self.assertEqual(data["esperado_empresa"]["Cash"],900)
        self.assertEqual(pos.report(opening.name,moneda="USD")["base"]["ingresos"],800)

    def test_joint_close_and_idempotent_retry(self):
        opening=self.opening();self.manual(opening)
        result=self.close(opening)
        self.assertEqual(result["estado"],pos.CLOSED,result)
        closure=frappe.get_doc(pos.CLOSURE,{"turno_pos":opening.name,"docstatus":1})
        self.assertEqual((closure.total_ingresos,closure.saldo_final),(50,150))
        self.assertEqual(pos.retry(opening.name)["estado"],pos.CLOSED)
        self.assertEqual(self.close(opening)["pos_closing_entry"],result["pos_closing_entry"])
        self.assertEqual(frappe.db.count(pos.CLOSURE,{"turno_pos":opening.name,"docstatus":1}),1)

    def test_empty_turn_still_has_both_closures(self):
        opening=self.opening();result=self.close(opening)
        self.assertEqual(result["estado"],pos.CLOSED,result)
        self.assertTrue(frappe.db.exists(pos.CLOSURE,{"turno_pos":opening.name,"docstatus":1}))

    def test_multiple_turns_same_day_and_month_boundary(self):
        opening=self.opening(when=now_datetime()-timedelta(days=40))
        self.manual(opening)
        self.assertEqual(self.close(opening)["estado"],pos.CLOSED)
        another=self.opening();self.manual(another)
        self.assertEqual(self.close(another)["estado"],pos.CLOSED)

    def test_failure_after_erp_close_blocks_next_opening_and_can_retry(self):
        opening=self.opening()
        with patch("ingresos_egresos.pos.finalize_closures",side_effect=RuntimeError("IE simulated failure")):
            result=self.close(opening)
        self.assertEqual(result["estado"],"Error")
        self.assertEqual(frappe.db.get_value("POS Opening Entry",opening.name,"status"),"Closed")
        with self.assertRaises(frappe.ValidationError):self.opening()
        self.assertEqual(pos.retry(opening.name)["estado"],pos.CLOSED)
        self.opening()

    def test_joint_cancellation_reopens_and_rejects_later_turn(self):
        opening=self.opening();self.manual(opening);self.close(opening)
        result=pos.cancel_closing(opening.name)
        self.assertEqual(result["estado"],pos.OPEN,result)
        self.assertEqual(frappe.db.get_value("POS Opening Entry",opening.name,"status"),"Open")
        self.assertEqual(frappe.db.count(pos.CLOSURE,{"turno_pos":opening.name,"docstatus":1}),0)
        self.assertEqual(self.close(opening)["estado"],pos.CLOSED)
        self.opening()
        with self.assertRaises(frappe.ValidationError):pos.cancel_closing(opening.name)

    def test_server_rejects_direct_close_and_movement_injection(self):
        opening=self.opening()
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(dict(doctype="Movimiento",turno_pos=opening.name,sucursal=self.branch,company=self.company,
                tipo="Ingreso",importe=10,moneda=self.currency,tasa_de_cambio=1,fecha_de_registro=nowdate(),
                flags={"ie_pos_service":True})).insert()
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(dict(doctype=pos.CLOSURE,turno_pos=opening.name,sucursal=self.branch,moneda=self.currency,
                fecha_inicio=nowdate(),fecha_final=nowdate())).insert()

    def test_report_pagination_and_filters(self):
        opening=self.opening()
        for index in range(28):self.manual(opening,request_id=str(index),mode="Credit Card" if index%2 else "Cash")
        self.assertEqual(len(pos.report(opening.name)["movimientos"]),25)
        self.assertEqual(len(pos.report(opening.name,start=25)["movimientos"]),3)
        self.assertEqual(pos.report(opening.name,medio_pago="Cash")["total"],14)

    def test_cannot_change_configuration_or_cancel_opening_with_movements(self):
        opening=self.opening();self.manual(opening)
        config=frappe.get_single("IE Configuracion");config.integrar_pos=0
        with self.assertRaises(frappe.ValidationError):config.save()
        with self.assertRaises(frappe.ValidationError):opening.cancel()

    def test_invoice_cancel_invalidates_only_its_automatic_movements(self):
        opening=self.opening();invoice=self.fake_invoice(opening);pos_hooks.invoice_on_submit(invoice)
        self.manual(opening)
        pos_hooks.invoice_before_cancel(invoice);pos_hooks.invoice_on_cancel(invoice)
        self.assertEqual(pos.report(opening.name)["total"],1)
        self.close(opening)
        with self.assertRaises(frappe.ValidationError):pos_hooks.invoice_before_cancel(invoice)

    def test_no_user_can_read_someone_elses_turn_without_authorization(self):
        opening=self.opening()
        frappe.set_user("Guest")
        try:
            with self.assertRaises(frappe.PermissionError):pos.report(opening.name)
        finally:frappe.set_user("Administrator")

    def test_legacy_pending_movements_prevent_activation(self):
        config=frappe.get_single("IE Configuracion");config.integrar_pos=0;config.save()
        frappe.get_doc(dict(doctype="Movimiento",sucursal=self.branch,tipo="Ingreso",importe=10,moneda=self.currency,
            tasa_de_cambio=1,fecha_de_registro=nowdate())).insert()
        config.integrar_pos=1
        with self.assertRaises(frappe.ValidationError):config.save()

    def test_unintegrated_opening_prevents_activation(self):
        config=frappe.get_single("IE Configuracion");config.integrar_pos=0;config.save()
        self.opening()
        config.integrar_pos=1
        with self.assertRaises(frappe.ValidationError):config.save()

    def test_unmapped_profile_cannot_open(self):
        profile=self.make_profile()
        with self.assertRaises(frappe.ValidationError):self.opening(profile)

    def test_native_pos_is_unchanged_when_integration_disabled(self):
        config=frappe.get_single("IE Configuracion");config.integrar_pos=0;config.save()
        opening=self.opening()
        self.assertFalse(frappe.db.exists(pos.TURN,opening.name))

    def test_generated_movements_do_not_get_recaptured_by_general_closure(self):
        opening=self.opening();self.manual(opening);self.close(opening)
        closure=frappe.get_doc(dict(doctype=pos.CLOSURE,sucursal=self.branch,moneda=self.currency,
            fecha_inicio=nowdate(),fecha_final=nowdate())).insert()
        self.assertEqual(closure.total_ingresos,0)

    def real_invoice(self, opening, kind="POS Invoice", amount=100):
        item="IE POS Service "+self.suffix
        if not frappe.db.exists("Item",item):
            frappe.get_doc(dict(doctype="Item",item_code=item,item_name=item,item_group="All Item Groups",
                stock_uom="Nos",is_stock_item=0,is_sales_item=1)).insert()
        customer=frappe.db.get_value("Customer",{"disabled":0},"name")
        doc=frappe.get_doc(dict(doctype=kind,company=self.company,customer=customer,is_pos=1,
            is_created_using_pos=1,pos_profile=opening.pos_profile,currency=self.currency,conversion_rate=1,
            update_stock=0,account_for_change_amount=self.cash_account,
            items=[dict(item_code=item,qty=1,rate=amount,income_account=self.income,expense_account=self.expense,cost_center=self.cost_center)],
            payments=[dict(mode_of_payment="Cash",account=self.cash_account,amount=amount)]))
        doc.insert();doc.submit()
        return doc

    def test_real_pos_invoice_and_consolidation_have_one_income(self):
        opening=self.opening();invoice=self.real_invoice(opening)
        self.assertEqual(invoice.custom_ie_turno_pos,opening.name)
        self.assertEqual(pos.report(opening.name)["base"]["ventas"],100)
        result=self.close(opening)
        self.assertEqual(result["estado"],pos.CLOSED,result)
        self.assertEqual(pos.report(opening.name)["total"],1)
        self.assertEqual(pos.cancel_closing(opening.name)["estado"],pos.OPEN)
        invoice.reload();invoice.cancel()
        self.assertEqual(pos.report(opening.name)["total"],0)

    def test_real_sales_invoice_is_recorded_and_closed(self):
        frappe.db.set_single_value("POS Settings","invoice_type","Sales Invoice")
        opening=self.opening();invoice=self.real_invoice(opening,"Sales Invoice")
        self.assertEqual(pos.report(opening.name)["base"]["ventas"],100)
        result=self.close(opening)
        self.assertEqual(result["estado"],pos.CLOSED,result)
        self.assertEqual(frappe.db.get_value("Sales Invoice",invoice.name,"pos_closing_entry"),result["pos_closing_entry"])

    def test_queued_close_survives_browser_and_finishes_from_reconciliation(self):
        opening=self.opening()
        def queue_only(pos_invoices=None,closing_entry=None):
            closing_entry.set_status(update=True,status="Queued")
        with patch("erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry.consolidate_pos_invoices",side_effect=queue_only):
            result=self.close(opening)
        self.assertEqual(result["estado"],"Cerrando POS")
        with self.assertRaises(frappe.ValidationError):self.manual(opening)
        pce=frappe.get_doc("POS Closing Entry",result["pos_closing_entry"])
        with pos.internal_operation():
            pce.set_status(update=True,status="Submitted");pce.update_opening_entry()
        pos.reconcile_pending()
        self.assertEqual(pos.status(opening.name)["estado"],pos.CLOSED)

    def test_two_profiles_in_same_branch_are_independent(self):
        other_profile=self.make_profile()
        config=frappe.get_single("IE Configuracion");config.append("perfiles_pos",dict(pos_profile=other_profile,sucursal=self.branch));config.save()
        user=frappe.get_doc(dict(doctype="User",email="ie-pos-"+self.suffix+"@example.invalid",first_name="IE POS",
            user_type="System User",send_welcome_email=0,roles=[dict(role="Sales User"),dict(role="IE Cajero POS")])).insert()
        first=self.opening()
        with patch("ingresos_egresos.pos.finalize_closures",side_effect=RuntimeError("simulated failure")):
            self.close(first)
        second=self.opening(other_profile,user.name)
        self.assertTrue(frappe.db.exists(pos.TURN,second.name))
        frappe.set_user(user.name)
        try:
            with self.assertRaises(frappe.PermissionError):pos.report(first.name)
        finally:frappe.set_user("Administrator")

    def test_existing_pos_movement_cannot_be_detached(self):
        opening=self.opening();name=self.manual(opening)["name"]
        doc=frappe.get_doc("Movimiento",name);doc.turno_pos=None;doc.origen_pos=None;doc.clave_origen_pos=None
        with self.assertRaises(frappe.ValidationError):doc.save()

    def test_pos_headers_and_profile_payment_modes_cannot_be_changed_during_turn(self):
        opening=self.opening()
        opening.balance_details[0].opening_amount=999
        with self.assertRaises(frappe.ValidationError):opening.save()
        profile=frappe.get_doc("POS Profile",self.profile);profile.set("payments",[dict(mode_of_payment="Cash",default=1)])
        with self.assertRaises(frappe.ValidationError):profile.save()

    def test_opening_status_cannot_be_reopened_through_desk(self):
        opening=self.opening();self.close(opening);opening.reload()
        opening.pos_closing_entry=None;opening.status="Open"
        with self.assertRaises(frappe.ValidationError):opening.save()

    def test_pending_erp_cancellation_can_finish_without_browser(self):
        opening=self.opening();self.close(opening)
        def queue_cancel(closing_entry):closing_entry.set_status(update=True,status="Queued")
        with patch("erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry.unconsolidate_pos_invoices",side_effect=queue_cancel):
            result=pos.cancel_closing(opening.name)
        self.assertEqual(result["estado"],"Anulando")
        pce=frappe.get_doc("POS Closing Entry",result["pos_closing_entry"])
        pce.set_status(update=True,status="Cancelled");pce.update_opening_entry(for_cancel=True)
        pos.reconcile_pending()
        self.assertEqual(pos.status(opening.name)["estado"],pos.OPEN)

    def test_external_queued_completion_is_accepted_but_false_status_is_not(self):
        opening=self.opening()
        def queue_only(pos_invoices=None,closing_entry=None):closing_entry.set_status(update=True,status="Queued")
        with patch("erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry.consolidate_pos_invoices",side_effect=queue_only):result=self.close(opening)
        doc=frappe.get_doc("POS Closing Entry",result["pos_closing_entry"])
        doc.status="Submitted"
        with self.assertRaises(frappe.ValidationError):doc.save()
        doc.reload();doc.set_status(update=True,status="Submitted");doc.update_opening_entry()
        pos.reconcile_pending()
        self.assertEqual(pos.status(opening.name)["estado"],pos.CLOSED)

    def test_authorized_cashier_can_register_and_close_only_own_turn(self):
        user=frappe.get_doc(dict(doctype="User",email="ie-cashier-"+self.suffix+"@example.invalid",first_name="IE Cashier",
            user_type="System User",send_welcome_email=0,roles=[dict(role=r) for r in ("Sales User","Accounts User","Stock User","IE Cajero POS")])).insert()
        opening=self.opening(user=user.name)
        frappe.set_user(user.name)
        try:
            self.manual(opening)
            self.assertEqual(pos.report(opening.name)["base"]["saldo"],150)
            with self.assertRaises(frappe.PermissionError):self.close(opening)
            frappe.set_user("Administrator")
            user.add_roles("Sales Manager")  # Native ERPNext closing permission is required as well.
            frappe.set_user(user.name)
            result=self.close(opening)
            self.assertEqual(result["estado"],pos.CLOSED,result)
            with self.assertRaises(frappe.PermissionError):pos.cancel_closing(opening.name)
        finally:frappe.set_user("Administrator")

    def test_supervisor_and_turn_list_respect_branch_user_permissions(self):
        profile=self.make_profile()
        other=frappe.get_doc(dict(doctype="Branch",branch="IE Other "+self.suffix)).insert().name
        config=frappe.get_single("IE Configuracion")
        config.append("perfiles_pos",dict(pos_profile=profile,sucursal=other));config.save()
        user=frappe.get_doc(dict(doctype="User",email="ie-supervisor-"+self.suffix+"@example.invalid",first_name="IE Supervisor",
            user_type="System User",send_welcome_email=0,roles=[dict(role=r) for r in ("Sales Manager","IE Supervisor POS")])).insert()
        first=self.opening();second=self.opening(profile,user.name)
        frappe.get_doc(dict(doctype="User Permission",user=user.name,allow="Branch",for_value=self.branch,
            apply_to_all_doctypes=1)).insert()
        frappe.set_user(user.name)
        try:
            self.assertEqual(pos.report(first.name)["estado"],pos.OPEN)
            with self.assertRaises(frappe.PermissionError):pos.report(second.name)
            self.assertEqual(frappe.get_list(pos.TURN,pluck="name"),[first.name])
        finally:frappe.set_user("Administrator")

    def test_partial_collection_uses_only_actual_payment_and_keeps_difference(self):
        opening=self.opening();invoice=self.fake_invoice(opening,amount=25)
        invoice.grand_total=100;invoice.outstanding_amount=75
        pos_hooks.invoice_on_submit(invoice)
        self.assertEqual(pos.report(opening.name)["base"]["ventas"],25)
        result=pos.start_closing(opening.name,{"Cash":120,"Credit Card":0})
        self.assertEqual(result["estado"],pos.CLOSED,result)
        row=frappe.get_doc("POS Closing Entry",result["pos_closing_entry"]).payment_reconciliation[0]
        self.assertEqual((row.expected_amount,row.closing_amount,row.difference),(125,120,-5))

    def test_company_currency_and_app_currency_are_preserved_independently(self):
        frappe.db.set_single_value("IE Configuracion","moneda_base","USD")
        with patch("ingresos_egresos.pos.exchange_rate",return_value=0.0125):opening=self.opening()
        result=pos.register_movement(opening.name,"Ingreso","Ventas POS",10,"EUR","Cash",1.2,96,request_id="two-bases")
        movement=frappe.get_doc("Movimiento",result["name"])
        self.assertEqual((movement.importe_base,movement.importe_empresa),(12,960))
        data=pos.report(opening.name)
        self.assertEqual((data["base"]["saldo"],data["esperado_empresa"]["Cash"]),(13.25,1060))
        self.assertEqual(self.close(opening)["estado"],pos.CLOSED)

    def test_settings_cannot_change_invoice_mode_during_pending_turn(self):
        self.opening()
        doc=frappe.get_single("POS Settings");doc.invoice_type="Sales Invoice"
        with self.assertRaises(frappe.ValidationError):doc.save()

    def test_supervisor_cannot_read_a_profile_assigned_to_other_users(self):
        profile=frappe.get_doc("POS Profile",self.profile)
        profile.append("applicable_for_users",dict(user="Administrator",default=1));profile.save()
        opening=self.opening()
        user=frappe.get_doc(dict(doctype="User",email="ie-unassigned-"+self.suffix+"@example.invalid",first_name="IE Unassigned",
            user_type="System User",send_welcome_email=0,roles=[dict(role=r) for r in ("Sales Manager","IE Supervisor POS")])).insert()
        frappe.set_user(user.name)
        try:
            with self.assertRaises(frappe.PermissionError):pos.report(opening.name)
            self.assertNotIn(opening.name,frappe.get_list(pos.TURN,pluck="name"))
        finally:frappe.set_user("Administrator")

    def test_closed_closure_and_invoice_cannot_be_detached_or_changed(self):
        opening=self.opening();invoice=self.real_invoice(opening);self.close(opening)
        closure=frappe.get_doc(pos.CLOSURE,{"turno_pos":opening.name,"docstatus":1})
        closure.turno_pos=None
        with self.assertRaises(frappe.ValidationError):closure.cancel()
        invoice.reload();invoice.custom_ie_turno_pos=None
        with self.assertRaises(frappe.ValidationError):pos_hooks.invoice_before_update(invoice)
        invoice.reload();invoice.payments[0].amount+=1
        with self.assertRaises(frappe.ValidationError):pos_hooks.invoice_before_update(invoice)

    def test_pos_concept_seeds_preserve_customizations_on_repeated_setup(self):
        from ingresos_egresos.pos_setup import seed_concepts
        doc=frappe.get_doc("IE Codigo","Ingreso")
        doc.append("code_values",dict(code_value="Concepto propio QA",active=1));doc.save()
        seed_concepts();seed_concepts()
        values=frappe.get_doc("IE Codigo","Ingreso").code_values
        self.assertEqual(sum(row.code_value=="Ventas POS" for row in values),1)
        self.assertEqual(sum(row.code_value=="Concepto propio QA" for row in values),1)

    def test_erp_closed_but_app_pending_prevents_configuration_changes(self):
        opening=self.opening()
        with patch("ingresos_egresos.pos.finalize_closures",side_effect=RuntimeError("pending IE")):self.close(opening)
        self.assertEqual(frappe.db.get_value("POS Opening Entry",opening.name,"status"),"Closed")
        config=frappe.get_single("IE Configuracion");config.integrar_pos=0
        with self.assertRaises(frappe.ValidationError):config.save()

    def test_failure_reversing_ie_after_erp_cancel_can_be_retried(self):
        from ingresos_egresos.ingresos_y_egresos.doctype.registro_de_cierre_de_movimiento.registro_de_cierre_de_movimiento import RegistrodeCierredeMovimiento
        opening=self.opening();self.manual(opening);result=self.close(opening)
        with patch.object(RegistrodeCierredeMovimiento,"on_cancel",side_effect=RuntimeError("cancel IE failed")):
            failed=pos.cancel_closing(opening.name)
        self.assertEqual(failed["estado"],"Error")
        self.assertEqual(frappe.db.get_value("POS Closing Entry",result["pos_closing_entry"],"docstatus"),2)
        self.assertEqual(frappe.db.count(pos.CLOSURE,{"turno_pos":opening.name,"docstatus":1}),1)
        self.assertEqual(pos.retry(opening.name)["estado"],pos.OPEN)
        self.assertEqual(frappe.db.count(pos.CLOSURE,{"turno_pos":opening.name,"docstatus":1}),0)
