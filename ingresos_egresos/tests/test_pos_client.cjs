const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup(enabled) {
    const events = {}, calls = [], actions = [];
    class Controller {
        prepare_app_defaults(data) {this.pos_opening=data.name;calls.push('defaults');}
        prepare_btns() {calls.push('buttons');}
        prepare_menu() {calls.push('menu');}
        close_pos() {calls.push('native-close');}
        setup_listener_for_pos_closing() {events.native=true;}
        check_outdated_pos_opening_entry() {calls.push('outdated');}
        open_form_view() {}
    }
    const frappe = {ie_pos:{},provide(){},utils:{},pages:{'point-of-sale':{
        on_page_load:()=>calls.push('page')
    }},require:async name=>calls.push(name),realtime:{
        on:(name,handler)=>events[name]=handler,off:name=>delete events[name]
    },show_alert:()=>calls.push('alert')};
    const sandbox={frappe,erpnext:{PointOfSale:{Controller}},__:v=>v};
    for (const name of ['ie_pos_modals.js','pos_integration.js'])
        vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../public/js',name),'utf8'),sandbox);
    frappe.ie_pos.call=async()=>({enabled,estado:'Abierto',puede_cerrar:true});
    frappe.ie_pos.closing=()=>calls.push('joint-close');
    frappe.ie_pos.movement=(_,kind)=>calls.push(kind);
    frappe.ie_pos.report=()=>calls.push('report');
    frappe.ie_pos.install();
    const controller=new Controller();
    controller.page={add_inner_button:(label,action)=>actions.push({label,action}),
        clear_menu(){},add_menu_item(){}};
    controller.$components_wrapper={prop:(key,value)=>controller[key]=value};
    return {controller,frappe,events,calls,actions};
}

test('disabled integration preserves native buttons, menu, listener and closing',async()=>{
    const {controller,calls,actions,events}=setup(false);
    await controller.prepare_app_defaults({name:'opening'});
    controller.prepare_btns();controller.prepare_menu();controller.setup_listener_for_pos_closing();controller.close_pos();
    assert.equal(actions.length,0);
    assert.equal(events.native,true);
    assert.ok(calls.includes('menu')&&calls.includes('native-close'));
});

test('four POS actions operate in modals and replace native closing',async()=>{
    const {controller,calls,actions}=setup(true);
    await controller.prepare_app_defaults({name:'opening'});
    controller.prepare_btns();controller.close_pos();
    assert.deepEqual(actions.map(a=>a.label),['Registrar ingreso','Registrar egreso','Movimientos y saldos','Cierre conjunto']);
    actions.forEach(a=>a.action());
    assert.ok(calls.includes('Ingreso')&&calls.includes('Egreso')&&calls.includes('report'));
    assert.equal(calls.filter(v=>v==='joint-close').length,2);
    assert.ok(!calls.includes('native-close'));
});

test('queued native closing cannot announce completion or unlock another turn',async()=>{
    const {controller,events}=setup(true);
    await controller.prepare_app_defaults({name:'opening'});
    controller.setup_listener_for_pos_closing();
    assert.equal(events.native,undefined);
    events.ie_pos_turn({opening:'other',estado:'Cerrado'});
    assert.equal(controller.ie_state,undefined);
    events.ie_pos_turn({opening:'opening',estado:'Cerrando app'});
    assert.equal(controller.inert,true);
    events.ie_pos_turn({opening:'opening',estado:'Abierto'});
    assert.equal(controller.inert,false);
});

test('loading POS again installs only one set of actions',async()=>{
    const {frappe,controller,actions}=setup(true);
    await frappe.pages['point-of-sale'].on_page_load({});
    await controller.prepare_app_defaults({name:'opening'});controller.prepare_btns();
    assert.equal(actions.length,4);
});

test('integrated overnight turns skip the native obsolete-date warning',async()=>{
    const integrated=setup(true), native=setup(false);
    await integrated.controller.prepare_app_defaults({name:'opening'});
    await native.controller.prepare_app_defaults({name:'opening'});
    integrated.controller.check_outdated_pos_opening_entry();native.controller.check_outdated_pos_opening_entry();
    assert.ok(!integrated.calls.includes('outdated'));
    assert.ok(native.calls.includes('outdated'));
});
