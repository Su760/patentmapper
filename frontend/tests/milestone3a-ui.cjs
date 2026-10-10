const { test, expect } = require('@playwright/test');
const job='10000000-0000-0000-0000-000000000001';
const owner='00000000-0000-0000-0000-000000000001';
const exact='  Exact saved α\n  second line &hellip;  ';
const observation={provider:'serpapi',provider_record_id:'patent/US123/en',publication_id:'US123A1',source_url:'https://patents.google.com/patent/US123/en',retrieved_at:'2026-10-04T12:00:00+00:00',matching_queries:['humidity sensor'],text:exact,text_type:'search_snippet',language:'en',dates:{priority:'2018-01-01',filing:null,publication:'2022-01-01'},requested_jurisdiction:'us',jurisdiction_filter:{country:'US'},coverage_limitations:['Limited results; no full patent claims retrieved.']};
async function setup(page,context){
 const host=new URL(process.env.NEXT_PUBLIC_SUPABASE_URL||'https://example.supabase.co').hostname.split('.')[0];
 await context.addCookies([{name:`sb-${host}-auth-token`,value:encodeURIComponent(JSON.stringify({access_token:'fixture-token',refresh_token:'fixture-refresh',expires_at:Math.floor(Date.now()/1000)+3600,expires_in:3600,token_type:'bearer',user:{id:owner,email:'fixture@example.test',aud:'authenticated'}})),domain:'127.0.0.1',path:'/'}]);
 const calls={paid:0,evidence:0};
 await page.route('**/api/**',route=>{
  if(route.request().method()==='POST') calls.paid++;
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/evidence')){calls.evidence++;expect(route.request().headers().authorization).toBe('Bearer fixture-token');return route.fulfill({json:{evidence_version:1,requested_jurisdiction:'us',clusters:[{theme_name:'Control',description:'AI inference',patent_ids:['serpapi:patent/US123/en']}],citation_links:[],warnings:['Cluster 1: excluded 1 unknown patent references.'],patents:[{patent_id:'serpapi:patent/US123/en',title:'Humidity controller',evidence_status:'available',evidence:{version:1,observations:[observation]}},{patent_id:'old-id',title:'Legacy controller',abstract:'Old saved text',url:null,evidence:null,evidence_status:'legacy_unknown'}]}});}
  if(path.endsWith('/analyze-claims'))return route.fulfill({json:{claims:null}});
  if(path.endsWith(job))return route.fulfill({json:{job_id:job,status:'completed'}});
  return route.fulfill({status:503,json:{detail:'Test usage unavailable'}});
 });
 await page.route('**/rest/v1/**',route=>route.fulfill({json:route.request().url().includes('search_results')?{clusters:[{theme_name:'Control',description:'AI inference',patent_ids:['ghost','serpapi:patent/US123/en'],filing_trend:[{year:2018,count:5},{year:2022,count:9}]}],citation_links:[{source:'ghost',target:'serpapi:patent/US123/en',strength:.8}],white_space_analysis:'',final_report:'# Saved report',coverage_warnings:[],evidence_version:1}:{invention_idea:'Humidity irrigation controller',created_at:'2026-01-01T00:00:00Z'}}));
 return calls;
}
for(const mobile of [false,true])test(`saved evidence search/select/reopen has zero paid calls (${mobile?'mobile':'desktop'})`,async({page,context})=>{
 if(mobile)await page.setViewportSize({width:390,height:844});
 const calls=await setup(page,context); await page.goto(`/results/${job}`);
 await expect(page.getByRole('heading',{name:'Retrieved evidence',exact:true})).toBeVisible();
 await page.getByRole('button',{name:/Humidity controller/}).click();
 expect(await page.getByTestId('evidence-text').textContent()).toBe(exact);
 await expect(page.getByText('Search snippet',{exact:true})).toBeVisible();
 await expect(page.getByText('Filing date: Unknown',{exact:true})).toBeVisible();
 await expect(page.getByRole('link',{name:'Open saved source'})).toHaveAttribute('href',observation.source_url);
 await expect(page.getByText(/excluded 1 unknown patent/)).toBeVisible();
 await expect(page.getByRole('heading',{name:'Technology trends'})).toHaveCount(0);
 await expect(page.getByRole('link',{name:'ghost',exact:true})).toHaveCount(0);
 await page.getByRole('searchbox',{name:'Search saved evidence'}).fill('Old saved text');
 await page.getByRole('button',{name:/Legacy controller/}).click();
 await expect(page.getByText(/Historical provenance is unknown/)).toBeVisible();
 await expect(page.getByTestId('legacy-evidence-text')).toHaveText('Old saved text');
 await page.reload(); await expect(page.getByRole('heading',{name:'Retrieved evidence',exact:true})).toBeVisible();
 await page.getByRole('button',{name:/Humidity controller/}).click();
 expect(await page.getByTestId('evidence-text').textContent()).toBe(exact);
 expect(calls.paid).toBe(0);expect(calls.evidence).toBe(2);
 await page.screenshot({path:`/tmp/pm-m3a-${mobile?'mobile':'desktop'}.png`,fullPage:true});
 // Existing sticky toolbar overflow is documented separately; verify the new panel fits.
 expect(await page.locator("#saved-evidence").evaluate(el=>[el,...el.querySelectorAll("*")].every(e=>e.getBoundingClientRect().right<=innerWidth+1))).toBe(true);
});
test('synthetic demo evidence remains local',async({page})=>{
 let privateCalls=0; await page.route('**/api/**',r=>{privateCalls++;return r.abort();});
 await page.goto('/results/demo');
 await expect(page.getByRole('heading',{name:'Retrieved evidence',exact:true})).toBeVisible();
 await page.getByRole('button',{name:/Synthetic irrigation/}).click();
 await expect(page.getByText('Synthetic demo text',{exact:true})).toBeVisible();
 await expect(page.getByRole('link',{name:'Open saved source'})).toHaveCount(0);
 expect(privateCalls).toBe(0);
});

test('malformed legacy cluster references do not crash saved results',async({page,context})=>{
 await setup(page,context);
 await page.route('**/rest/v1/search_results*',r=>r.fulfill({json:{clusters:[{theme_name:'Malformed',description:'Old',patent_ids:null}],citation_links:[],white_space_analysis:'',final_report:'# Legacy report'}}));
 await page.goto(`/results/${job}`);
 await expect(page.getByRole('heading',{name:'Retrieved evidence',exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Legacy report',exact:true})).toBeVisible();
});

test('account change cancels pending evidence and cannot reveal the prior owner',async({page,context})=>{
 const calls=await setup(page,context); let pending;
 await page.route(`**/api/jobs/${job}/evidence`,r=>{pending=r;});
 await page.goto(`/results/${job}`);
 await expect(page.getByRole('heading',{name:'Saved report',exact:true})).toBeVisible();
 await expect.poll(()=>!!pending).toBe(true);
 await page.route(`**/api/jobs/${job}`,r=>r.fulfill({status:404,json:{detail:'Unavailable'}}));
 const aborted=page.waitForEvent('requestfailed',r=>r.url().endsWith('/evidence'));
 const host=new URL(process.env.NEXT_PUBLIC_SUPABASE_URL||'https://example.supabase.co').hostname.split('.')[0];
 await page.evaluate(host=>{const channel=new BroadcastChannel(`sb-${host}-auth-token`);channel.postMessage({event:'SIGNED_IN',session:{access_token:'other-token',user:{id:'00000000-0000-0000-0000-000000000002',email:'other@example.test'}}});channel.close();},host);
 await aborted;
 await expect(page.getByText(/unavailable to your account/)).toBeVisible();
 await pending.fulfill({json:{patents:[{patent_id:'secret',title:'Previous owner secret'}],clusters:[],citation_links:[],warnings:[]}}).catch(()=>{});
 await expect(page.getByText('Previous owner secret')).toHaveCount(0);
 await expect(page.getByRole('heading',{name:'Saved report',exact:true})).toHaveCount(0);
 expect(calls.paid).toBe(0);
});

test('evidence failures expose a free read retry and retain the saved report',async({page,context})=>{
 const calls=await setup(page,context);
 await page.route(`**/api/jobs/${job}/evidence`,r=>r.fulfill({status:503,json:{detail:'Saved evidence temporarily unavailable'}}));
 await page.goto(`/results/${job}`);
 await expect(page.getByRole('button',{name:'Retry saved evidence'})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Saved report',exact:true})).toBeVisible();
 await page.unroute(`**/api/jobs/${job}/evidence`);
 await page.getByRole('button',{name:'Retry saved evidence'}).click();
 await page.getByRole('button',{name:/Humidity controller/}).click();
 expect(await page.getByTestId('evidence-text').textContent()).toBe(exact);
 expect(calls.paid).toBe(0);
});
