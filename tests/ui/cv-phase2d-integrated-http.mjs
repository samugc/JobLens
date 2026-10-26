import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const cv=require('../../web/workspace/api-adapter.js');
const pa=require('../../web/workspace/profile-adapter.js');
const review=require('../../web/workspace/profile-review.js');
const [origin,pdfPath,docxPath]=process.argv.slice(2);
const calls=[];let extractionWire,profileWire;
const transport=async(url,options)=>{
 assert.equal(new URL(url).origin,origin);
 assert.equal(options.headers['X-JobLens-Request'],'1');
 calls.push(new URL(url).pathname);
 if(url.endsWith('/profiles')){
  const body=JSON.parse(options.body);
  assert.deepEqual(Object.keys(body).sort(),['documents','job_id']);
  assert.equal(body.documents[0].status,'partial');
 }
 const r=await fetch(url,{...options,headers:{...options.headers,Origin:origin}});
 const wire=await r.clone().json();
 if(url.endsWith('/profiles'))profileWire=wire;else extractionWire=wire;
 return r;
};
const job=await new cv.CvApiAdapter({baseUrl:origin+'/api/cv',fetchImpl:transport}).createExtraction([
 new File([readFileSync(pdfPath)],'synthetic.pdf',{type:'application/pdf'}),
 new File([readFileSync(docxPath)],'synthetic.docx',{type:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'})
]);
assert.equal(job.schemaVersion,'1.1');assert.equal(job.transportVersion,'1.0');
assert.equal(job.documents[0].parserStatus,'partial');assert.equal(job.documents[0].status,'needs_review');
const profile=await new pa.CvProfileAdapter({baseUrl:origin+'/api/cv',fetchImpl:transport}).createProfile(job);
assert.equal(profile.schemaVersion,'0.1');
assert.ok(profile.proposals.every(p=>p.status==='proposed'));
const python=profile.proposals.find(p=>p.category==='skill'&&p.value.name==='python');
assert.equal(new Set(python.evidence.map(e=>e.documentId)).size,2);
const atlas=profile.proposals.filter(p=>p.category==='project'&&p.value.name==='project atlas');
assert.equal(atlas.length,1);assert.equal(atlas[0].conflicts.length,0);
assert.equal(new Set(atlas[0].evidence.map(e=>e.documentId)).size,2);
assert.ok(atlas[0].evidence.some(e=>e.quote.includes('synthetic sales')));
assert.ok(atlas[0].evidence.some(e=>e.quote.includes('written in Python')));
const beacon=profile.proposals.filter(p=>p.category==='project'&&p.value.name==='project beacon');
assert.equal(beacon.length,2);
const language=profile.conflicts.find(c=>c.kind==='conflicting_stated_level');
const project=profile.conflicts.find(c=>c.kind==='conflicting_description');
assert.equal(language.blocking,true);assert.equal(project.blocking,true);
assert.equal(project.resolutionHint,null);assert.equal(project.suggestion,null);
assert.equal(language.resolutionHint.strategy,'prefer_higher_cefr_claim');
assert.equal(language.resolutionHint.requiresUserConfirmation,true);
assert.match(language.resolutionHint.explanation,/no reliable chronology/);
const rawLanguage=profileWire.conflicts.find(c=>c.kind==='conflicting_stated_level');
assert.equal(language.resolutionHint.explanation,rawLanguage.resolution_hint.explanation);
const c1=language.resolutionHint.keepProposalIds[0];
assert.equal(profile.proposals.find(p=>p.id===c1).value.stated_level,'c1');
let unicode=false;
for(const p of profileWire.proposals)for(const e of p.evidence){
 const segment=extractionWire.documents.find(d=>d.document_id===e.document_id).segments[e.segment_index];
 assert.equal(Array.from(segment.text).slice(e.start,e.end).join(''),e.quote);
 assert.deepEqual(pa.normalizeLocator(e.locator,'e'),pa.normalizeLocator(segment.locator,'s'));
 if(segment.text.slice(e.start,e.end)!==e.quote)unicode=true;
}
assert.ok(unicode);
assert.ok(profile.proposals.every(p=>p.evidence.every(e=>e.verified && e.resolved)));
let state=review.createReviewState(profile);
const view=()=>review.buildViewModel(profile,state,pa);
const act=a=>{const r=review.applyReviewAction(state,a,{adapter:pa});if(r.applied)state=r.state;return r;};
assert.equal(view().counts.unresolved,2);assert.equal(view().counts.approved,0);assert.equal(state.history.length,0);
assert.equal(act({kind:'approve',proposalId:c1}).applied,false);
for(const id of project.proposalIds)assert.equal(act({kind:'approve',proposalId:id}).applied,false);
assert.equal(act({kind:'use_recommendation',conflictId:language.conflictId}).applied,true);
assert.equal(view().counts.unresolved,1);assert.equal(view().counts.approved,0);
assert.equal(view().proposals.find(p=>p.id===c1).status,'proposed');
assert.equal(view().conflicts.find(c=>c.conflictId===project.conflictId).resolved,false);
for(const id of project.proposalIds)assert.equal(act({kind:'approve',proposalId:id}).applied,false);
assert.equal(act({kind:'approve',proposalId:c1}).applied,true);
const edited=act({kind:'edit',proposalId:c1,value:{language:'english',stated_level:'c2'}});
assert.equal(edited.applied,true);assert.equal(view().counts.approved,0);
assert.equal(view().proposals.find(p=>p.id===c1).status,'superseded');
assert.equal(view().proposals.find(p=>p.id===edited.revisionId).status,'proposed');
assert.deepEqual(view().history.map(e=>e.kind),['use_recommendation','approve','edit']);
assert.equal(act({kind:'resolve_conflict',conflictId:project.conflictId,kept:[project.proposalIds[0]],note:'Synthetic reviewer explicitly selects this artifact'}).applied,true);
assert.equal(view().counts.approved,0);
// Negative contract cases are mutations of the real response, not fixture responses.
for(const bad of [null,42,'foreign_id',python.id]){
 const raw=structuredClone(profileWire);raw.conflicts.find(c=>c.kind==='conflicting_stated_level').resolution_hint.keep_proposal_ids=[bad];
 let normalized;
 try{normalized=pa.normalizeProfileEnvelope(raw,{source:pa.sourceFromJob(job)});}catch(e){assert.equal(e.name,'CvProfileContractError');continue;}
 const c=normalized.conflicts.find(c=>c.kind==='conflicting_stated_level');assert.equal(c.resolutionHint,null);
 assert.equal(review.applyReviewAction(review.createReviewState(normalized),{kind:'use_recommendation',conflictId:c.conflictId},{adapter:pa}).applied,false);
}
const unknown=structuredClone(profileWire);unknown.conflicts.find(c=>c.kind==='conflicting_description').kind='unknown_future_conflict';
const up=pa.normalizeProfileEnvelope(unknown,{source:pa.sourceFromJob(job)});const us=review.createReviewState(up);
for(const id of project.proposalIds)assert.equal(review.applyReviewAction(us,{kind:'approve',proposalId:id},{adapter:pa}).applied,false);
assert.deepEqual(calls,['/api/cv/extractions','/api/cv/profiles']);
for(const path of ['/workspace/fixtures/profile-synthetic.json','/workspace/fixtures/profile-synthetic-recommendation.json','/src/joblens_public/profile/engine.py'])assert.equal((await fetch(origin+path)).status,404);
const html=await (await fetch(origin+'/workspace/')).text();
for(const id of ['profile-preview','profile-preview-suggestion'])assert.match(html,new RegExp('<button id="'+id+'"[^>]*hidden[^>]*disabled'));
const app=await (await fetch(origin+'/workspace/app.js')).text();
assert.ok(!app.includes('no engine is mounted here'));
assert.ok(app.includes('conflict.resolutionHint.explanation'));assert.ok(app.includes('renderConflictQuotes(conflict)'));
console.log(JSON.stringify({result:'PASS',proposals:profile.proposals.length,atlasEvidence:atlas[0].evidence.length,conflicts:profile.conflicts.length,unicode,apiCalls:calls.length,reviewHistory:view().history.length}));
