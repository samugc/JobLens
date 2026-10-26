import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import vm from 'node:vm';
const require=createRequire(import.meta.url);
const cv=require('../../web/workspace/api-adapter.js');
const pa=require('../../web/workspace/profile-adapter.js');
const review=require('../../web/workspace/profile-review.js');
const rc=require('../../web/workspace/reconciliation-adapter.js');
const [origin,pdfPath,docxPath,specPath,resultPath]=process.argv.slice(2);
const spec=JSON.parse(readFileSync(specPath,'utf8'));
let wire,requestBody;const calls=[];
const transport=async(url,opts)=>{
 assert.equal(new URL(url).origin,origin);assert.equal(opts.headers['X-JobLens-Request'],'1');calls.push(new URL(url).pathname);
 if(!url.endsWith('/extractions')){const b=JSON.parse(opts.body);assert.deepEqual(Object.keys(b).sort(),['documents','job_id']);assert.equal(b.documents[0].status,'partial');if(url.endsWith('/reconciliations'))requestBody=b;}
 const r=await fetch(url,{...opts,headers:{...opts.headers,Origin:origin}});
 assert.equal(r.headers.get('access-control-allow-origin'),null);
 if(url.endsWith('/reconciliations'))wire=await r.clone().json();return r;
};
const job=await new cv.CvApiAdapter({baseUrl:origin+'/api/cv',fetchImpl:transport}).createExtraction([
 new File([readFileSync(pdfPath)],'synthetic.pdf',{type:'application/pdf'}),
 new File([readFileSync(docxPath)],'synthetic.docx',{type:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'})]);
assert.equal(job.schemaVersion,'1.1');assert.equal(job.documents[0].parserStatus,'partial');
const profile=await new pa.CvProfileAdapter({baseUrl:origin+'/api/cv',fetchImpl:transport}).createProfile(job);
assert.equal(profile.schemaVersion,'0.1');assert.ok(profile.proposals.every(p=>p.status==='proposed'));
const model=await new rc.ReconciliationAdapter({baseUrl:origin+'/api/cv',fetchImpl:transport}).createReconciliation(job);
assert.equal(model.report.reconciliation_schema_version,'0.1');assert.deepEqual(model.report,wire);
assert.ok(wire.claims.length);assert.ok([...model.verified.values()].every(Boolean));
assert.equal(model.counts.approved,0);
const claims=wire.claims.filter(c=>c.category===spec.category && (!spec.subject || c.subject===spec.subject));
assert.ok(claims.length>=2 || spec.crossCategory,JSON.stringify({spec,claims}));
const ids=new Set(claims.map(c=>c.claim_id));
if(spec.crossCategory)assert.ok(wire.relationships.some(r=>r.basis==='cross_category'&&r.relation==='complementary'));
else assert.ok(wire.relationships.some(r=>ids.has(r.left_claim_id)&&ids.has(r.right_claim_id)&&spec.relations.includes(r.relation)),JSON.stringify({spec,relationships:wire.relationships}));
if(spec.outcome){const d=wire.decisions.find(d=>d.category===spec.category&&d.subject===spec.subject);assert.ok(d);assert.equal(d.outcome,spec.outcome);assert.equal(d.requires_user_confirmation,spec.outcome!=='auto_consolidate');
 if(spec.kept){const kept=wire.claims.find(c=>c.claim_id===d.keep_claim_ids[0]);assert.equal(kept.attributes.find(a=>a.name==='proficiency').value,spec.kept);}
}
if(spec.outcome==='auto_consolidate'){const c=wire.consolidated.find(c=>c.category===spec.category&&c.subject===spec.subject);assert.equal(new Set(c.evidence.map(e=>e.document_id)).size,2);}
let unicode=false;
for(const c of wire.claims)for(const e of c.evidence){const segment=job.documents.find(d=>d.id===e.document_id).segments[e.segment_index];assert.equal(Array.from(segment.text).slice(e.start,e.end).join(''),e.quote);if(segment.text.slice(e.start,e.end)!==e.quote)unicode=true;}
assert.ok(unicode,'actual non-BMP source offsets are exercised');
if(spec.attributes)for(const name of spec.attributes)assert.ok(claims.some(c=>c.attributes.some(a=>a.name===name)),name);
// Negative checks operate on real report data; they do not replace server output.
const invalid=structuredClone(wire);invalid.claims[0].evidence[0].quote='UNSUPPORTED SYNTHETIC QUOTE';
const bad=rc.normalizeReport(invalid,{source:pa.sourceFromJob(job)});assert.equal(bad.verified.get(invalid.claims[0].claim_id),false);assert.ok(bad.groups.some(g=>g.blocking));
if(wire.relationships.length){const unknown=structuredClone(wire);unknown.relationships[0].relation='unknown_engine_relation';assert.ok(rc.normalizeReport(unknown,{source:pa.sourceFromJob(job)}).groups.some(g=>g.blocking));}
let state=review.createReviewState(profile);const previous=JSON.stringify(state);
assert.deepEqual(calls,['/api/cv/extractions','/api/cv/profiles','/api/cv/reconciliations']);
assert.equal(JSON.stringify(state),previous);assert.equal(model.counts.approved,0);
const available=profile.proposals.find(p=>review.canApprove(p,state).allowed);
if(available){state=review.applyReviewAction(state,{kind:'approve',proposalId:available.id},{adapter:pa}).state;
 const value={...available.value};const primary=pa.CATEGORY_META[available.category].primary;value[primary]='unsupported synthetic edit';
 const edit=review.applyReviewAction(state,{kind:'edit',proposalId:available.id,value},{adapter:pa});assert.equal(edit.applied,true);
 assert.equal(edit.state.proposals.find(p=>p.id===available.id).status,'superseded');
 assert.equal(review.applyReviewAction(edit.state,{kind:'approve',proposalId:edit.revisionId},{adapter:pa}).applied,false);
 assert.deepEqual(edit.state.history.map(e=>e.kind),['approve','edit']);}
// Execute the served rendering function with a minimal DOM test double.
// This verifies render output, not a browser, layout or Safari behavior.
class Element{
 constructor(){this.children=[];this._text='';this.attrs={};this.classList={toggle(){}};}
 set textContent(v){this._text=String(v);this.children=[];}
 get textContent(){return this._text+this.children.map(c=>c.textContent).join(' ');}
 append(...nodes){this.children.push(...nodes);}get firstChild(){return this.children[0];}
 removeChild(n){this.children.splice(this.children.indexOf(n),1);}setAttribute(k,v){this.attrs[k]=v;}
}
const nodes=new Map();const document={addEventListener(){},createElement:()=>new Element(),getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);}};
const window={JobLensCV:cv,JobLensProfileAdapter:pa,JobLensProfileReview:review,JobLensReconciliation:rc};
let app=await (await fetch(origin+'/workspace/app.js')).text();
app=app.replace(/\}\)\(\);\s*$/, 'window.__test={state,renderReconciliation,renderViewSwitch};})();');
vm.runInNewContext(app,{window,document,console});window.__test.state.job=job;window.__test.state.reconciliation=model;window.__test.state.view='reconciliation';window.__test.renderReconciliation();window.__test.renderViewSwitch();
assert.equal(nodes.get('view-reconciliation').attrs['aria-selected'],'true');assert.equal(nodes.get('view-profile').attrs['aria-selected'],'false');
const rendered=nodes.get('reconciliation-groups').textContent;
for(const c of wire.claims){assert.ok(rendered.includes(c.claim_id));for(const e of c.evidence)assert.ok(rendered.includes(e.quote));for(const a of c.attributes)assert.ok(rendered.includes(typeof a.value==='string'?a.value:JSON.stringify(a.value)));}
for(const r of wire.relationships){assert.ok(rendered.includes(r.reason));assert.ok(rendered.includes(r.relation));}
for(const d of wire.decisions){assert.ok(rendered.includes(d.outcome));assert.ok(rendered.includes(d.explanation));}
assert.equal(typeof rc.approveAll,'undefined');assert.ok(rendered.includes('no approval, resolution or claim-to-proposal mapping is transferred'));
// Primary review coverage: every source claim keeps a visible quote in the
// attention, consolidated or remaining-claims section, and recommendations
// keep their unselected alternatives.
const attentionText=nodes.get('reconciliation-attention').textContent;
const consolidatedText=nodes.get('reconciliation-consolidated').textContent;
const findingsText=nodes.get('reconciliation-findings').textContent;
const primaryText=attentionText+consolidatedText+findingsText;
for(const c of wire.claims){
 const quote=c.evidence[0]?.quote;
 assert.ok(quote && primaryText.includes(quote),`source claim ${c.claim_id} is not discoverable in primary review`);
}
for(const d of wire.decisions){
 if(d.outcome==='auto_consolidate')continue;
 for(const id of d.alternative_claim_ids||[]){
  const c=wire.claims.find(item=>item.claim_id===id);
  assert.ok(c&&attentionText.includes(c.evidence[0].quote),`retained alternative ${id} is missing from attention`);
 }
}
assert.ok(!primaryText.includes('What would be left out'));
assert.ok(!primaryText.includes('dato'));
writeFileSync(resultPath,JSON.stringify({request:requestBody,report:wire}));
console.log(JSON.stringify({case:spec.id,claims:wire.claims.length,relationships:wire.relationships.length,decisions:wire.decisions.length,rendered:true,unicode,apiCalls:calls.length}));
