import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const cv=require('../../web/workspace/api-adapter.js');
const pa=require('../../web/workspace/profile-adapter.js');
const review=require('../../web/workspace/profile-review.js');
const [origin,pdfPath,docxPath]=process.argv.slice(2);
const requests=[]; let extractionWire,profileWire;
const transport=async(url,options)=>{
  assert.equal(new URL(url).origin,origin);
  assert.equal(options.headers['X-JobLens-Request'],'1');
  requests.push({url,method:options.method});
  if(url.endsWith('/profiles')) {
    const body=JSON.parse(options.body);
    assert.deepEqual(Object.keys(body).sort(),['documents','job_id']);
    assert.equal(body.documents[0].status,'partial');
    assert.ok(!body.documents.some(d=>d.status==='needs_review'));
  }
  const response=await fetch(url,{...options,headers:{...options.headers,Origin:origin}});
  const payload=await response.clone().json();
  if(url.endsWith('/profiles'))profileWire=payload;else extractionWire=payload;
  return response;
};
const extraction=new cv.CvApiAdapter({baseUrl:origin+'/api/cv',fetchImpl:transport});
const job=await extraction.createExtraction([
 new File([readFileSync(pdfPath)],'synthetic-phase2.pdf',{type:'application/pdf'}),
 new File([readFileSync(docxPath)],'synthetic-phase2.docx',{type:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'})
]);
assert.equal(job.schemaVersion,'1.1');assert.equal(job.transportVersion,'1.0');
assert.equal(job.documents[0].parserStatus,'partial');
assert.equal(job.documents[0].status,'needs_review');
const adapter=new pa.CvProfileAdapter({baseUrl:origin+'/api/cv',fetchImpl:transport});
const profile=await adapter.createProfile(job);
assert.equal(profile.schemaVersion,'0.1');
assert.ok(profile.proposals.length>0);
assert.ok(profile.proposals.every(p=>p.status==='proposed'));
assert.deepEqual(new Set(profile.proposals.map(p=>p.category)),new Set(pa.CATEGORIES));
assert.ok(profile.proposals.every(p=>p.evidence.length && p.evidence.every(e=>e.verified && e.resolved)));
let nonBmpOffset=false;
for(const proposal of profileWire.proposals)for(const e of proposal.evidence){
 const doc=extractionWire.documents.find(d=>d.document_id===e.document_id);
 const segment=doc.segments[e.segment_index];
 assert.equal(Array.from(segment.text).slice(e.start,e.end).join(''),e.quote);
 assert.deepEqual(pa.normalizeLocator(e.locator, "evidence"),pa.normalizeLocator(segment.locator, "source"));
 if(segment.text.slice(e.start,e.end)!==e.quote)nonBmpOffset=true;
}
assert.ok(nonBmpOffset,'real DOCX must exercise Python code-point offsets different from UTF-16');
const python=profile.proposals.find(p=>p.category==='skill'&&p.value.name==='python');
assert.equal(new Set(python.evidence.map(e=>e.documentId)).size,2);
assert.deepEqual(new Set(profile.conflicts.map(c=>c.kind)),new Set(['conflicting_stated_level','conflicting_description']));
const tampered=structuredClone(profileWire);
tampered.proposals[0].evidence[0].quote='UNSUPPORTED-SYNTHETIC-QUOTE';
const invalid=pa.normalizeProfileEnvelope(tampered,{source:pa.sourceFromJob(job)});
const invalidState=review.createReviewState(invalid);
assert.equal(review.applyReviewAction(invalidState,{kind:'approve',proposalId:invalid.proposals[0].id},{adapter:pa}).applied,false);
let state=review.createReviewState(profile);
const view=()=>review.buildViewModel(profile,state,pa);
assert.equal(view().groups.length,6);
assert.equal(view().counts.approved,0);
const action=(a)=>{const result=review.applyReviewAction(state,a,{adapter:pa});if(result.applied)state=result.state;return result;};
assert.equal(action({kind:'approve',proposalId:python.id}).applied,true);
assert.equal(view().counts.approved,1);
assert.equal(action({kind:'reject',proposalId:python.id}).applied,true);
assert.equal(view().proposals.find(p=>p.id===python.id).status,'rejected');
assert.equal(action({kind:'approve',proposalId:python.id}).applied,true);
const edited=action({kind:'edit',proposalId:python.id,value:{name:'unquoted-synthetic-skill'}});
assert.equal(edited.applied,true);
assert.equal(view().proposals.find(p=>p.id===python.id).status,'superseded');
assert.equal(view().proposals.find(p=>p.id===edited.revisionId).status,'proposed');
assert.equal(view().counts.approved,0);
assert.equal(action({kind:'approve',proposalId:edited.revisionId}).applied,false);
for(const conflict of profile.conflicts){
 const id=conflict.proposalIds[0];
 assert.equal(action({kind:'approve',proposalId:id}).applied,false);
 assert.equal(action({kind:'resolve_conflict',conflictId:conflict.conflictId,kept:[id],note:'Explicit synthetic reviewer choice'}).applied,true);
 assert.equal(action({kind:'approve',proposalId:id}).applied,true);
}
assert.equal(view().counts.unresolved,0);
assert.ok(view().history.some(e=>e.kind==='edit'));
assert.equal(view().history.filter(e=>e.kind==='resolve_conflict').length,2);
assert.deepEqual(requests.map(r=>new URL(r.url).pathname),['/api/cv/extractions','/api/cv/profiles']);
assert.ok(profile.proposals.every(p=>p.status==='proposed'),'local actions must not mutate the engine envelope');
for(const path of ['/workspace/profile-adapter.js','/workspace/profile-review.js']){
 const response=await fetch(origin+path);assert.equal(response.status,200);
 assert.match(response.headers.get('content-security-policy'),/connect-src 'self'/);
 assert.equal(response.headers.get('access-control-allow-origin'),null);
}
for(const path of ['/workspace/fixtures/profile-synthetic.json','/workspace/fixtures/profile-preview-source.json','/src/joblens_public/profile/engine.py'])
 assert.equal((await fetch(origin+path)).status,404);
console.log(JSON.stringify({result:'PASS',proposals:profile.proposals.length,categories:view().groups.length,conflicts:profile.conflicts.length,realPartialPreserved:true,nonBmpOffset,localHistory:view().history.length,apiRequests:requests.length}));
