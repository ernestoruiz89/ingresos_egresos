const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(values) {
    const frappe = {ie_deferred:{},provide(){},datetime:{get_today:()=> '2026-10-31'}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../public/js/ie_deferred.js'),'utf8'),{frappe,__:v=>v});
    const names=['es_diferido','inicio_diferimiento','meses_diferimiento','es_activo'];
    const dialog={values,fields_dict:Object.fromEntries(names.map(name=>[name,{df:{}}])),
        get_value(name){return this.values[name];},
        async set_value(name,value){this.values[name]=value;await this.fields_dict[name]?.df.onchange?.();},
        set_df_property(name,key,value){this.fields_dict[name].df[key]=value;}};
    return {api:frappe.ie_deferred,dialog};
}

test('enabling deferral requests dates and preserves the saved service period',async()=>{
    const {api,dialog}=setup({es_diferido:1,inicio_diferimiento:'2027-01-01',meses_diferimiento:6});
    await api.bind(dialog);
    assert.equal(dialog.values.inicio_diferimiento,'2027-01-01');assert.equal(dialog.values.meses_diferimiento,6);
    assert.equal(dialog.fields_dict.inicio_diferimiento.df.reqd,1);
});
test('ordinary movements do not require service dates or months',async()=>{
    const {api,dialog}=setup({es_diferido:0,es_activo:1});await api.bind(dialog);
    assert.equal(dialog.values.es_activo,1);assert.equal(dialog.fields_dict.inicio_diferimiento.df.reqd,0);
});
test('asset and deferral options are mutually exclusive and keep the asset handler',async()=>{
    const {api,dialog}=setup({es_diferido:0,es_activo:1,fecha_de_registro:'2026-09-01'});
    let assetEvents=0;dialog.fields_dict.es_activo.df.onchange=()=>{assetEvents++;};await api.bind(dialog);
    await dialog.set_value('es_diferido',1);
    assert.equal(dialog.values.es_activo,0);assert.equal(dialog.values.inicio_diferimiento,'2026-09-01');
    await dialog.set_value('es_activo',1);
    assert.equal(dialog.values.es_diferido,0);assert.equal(dialog.fields_dict.inicio_diferimiento.df.reqd,0);assert.equal(assetEvents,2);
});
