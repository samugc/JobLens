import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const cv = require('../../web/workspace/api-adapter.js');
const [base, pdfPath, docxPath] = process.argv.slice(2);
let calls = 0;
let wire;
const adapter = new cv.CvApiAdapter({baseUrl: `${base}/api/cv`, fetchImpl: async (url, options) => {
  assert.equal(new URL(url).origin, base);
  assert.equal(options.headers['X-JobLens-Request'], '1');
  calls++;
  // Node does not add the browser's Origin header automatically.
  const response = await fetch(url, {...options, headers: {...options.headers, Origin: base}});
  wire = await response.clone().json();
  return response;
}});
const pdf = new File([readFileSync(pdfPath)], 'synthetic.pdf', {type:'application/pdf'});
const docx = new File([readFileSync(docxPath)], 'synthetic.docx', {type:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'});
const result = await adapter.createExtraction([pdf,docx]);
assert.equal(result.status, 'complete');
assert.equal(result.schemaVersion, '1.1');
assert.equal(result.transportVersion, '1.0');
assert.equal(result.documentCount, 2);
for (let i=0;i<2;i++) {
  assert.equal(result.documents[i].fullText, wire.documents[i].text);
  assert.equal(result.documents[i].parserStatus, wire.documents[i].status);
  assert.deepEqual(result.documents[i].warnings, wire.documents[i].warnings);
  for (let j=0;j<wire.documents[i].segments.length;j++) {
    assert.equal(result.documents[i].segments[j].text, wire.documents[i].segments[j].text);
    for(const [key,value] of Object.entries(wire.documents[i].segments[j].locator))
      assert.equal(result.documents[i].segments[j].locator[key],value);
  }
}
assert.match(result.documents[0].fullText,/INTEGRATION-SYNTHETIC-MARKER/);
const partial = await adapter.createExtraction([pdf,new File(['SYNTHETIC-BROKEN'], 'broken.docx')]);
assert.equal(partial.status,'partial');
assert.equal(partial.documents[1].parserStatus,'malformed');
assert.equal(partial.documents[1].fullText,'');
assert.ok(partial.documents[1].warnings.length);
const before=calls;
await assert.rejects(adapter.createExtraction([new File([new Uint8Array(cv.MAX_BATCH_BYTES+1)],'oversized.pdf')]), e=>e.code==='batch_too_large');
assert.equal(calls,before);
const form=new FormData();
for(let i=0;i<6;i++)form.append('files',pdf,`synthetic-${i}.pdf`);
await assert.rejects(adapter.request('/extractions',{method:'POST',body:form,headers:{'X-JobLens-Request':'1'}}), e=>e.code==='too_many_documents');
assert.equal(wire.batch.document_count,6);
assert.deepEqual(wire.documents,[]);
assert.throws(()=>cv.normalizeBatchEnvelope(wire),e=>e.code==='too_many_documents');
assert.equal(calls,3);
for(const path of ['/','/workspace/','/workspace/app.js','/workspace/api-adapter.js','/workspace/styles.css','/workspace/favicon.svg','/api/status','/api/bootstrap']) {
  const response=await fetch(base+path); assert.equal(response.status,200,path);
  assert.equal(response.headers.get('access-control-allow-origin'),null);
  assert.match(response.headers.get('content-security-policy'),/connect-src 'self'/);
}
console.log('Real mounted HTTP + native adapter: PASS; 3 POSTs, no polling; synthetic PDF/DOCX text, locators, warnings, rejection and size preflight verified.');
