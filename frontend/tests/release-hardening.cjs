const { test, expect } = require('@playwright/test');
const job='10000000-0000-0000-0000-000000000001',owner='00000000-0000-0000-0000-000000000001';
const notice='AI inference from available abstracts, search snippets or titles.';
const claim={patent_id:'fixture',title:'Saved overlap',likely_claims:['Saved aspect'],overlap_level:'low',overlap_explanation:'Limited overlap',differentiators:'Different design'};
const long='LongIdentifier'.repeat(18);
async function setup(page,context,{cached={claims:[claim]},generated={claims:[claim]},lengthy=false}={}){
 const host=new URL(process.env.NEXT_PUBLIC_SUPABASE_URL||'https://example.supabase.co').hostname.split('.')[0];
 await context.addCookies([{name:`sb-${host}-auth-token`,value:encodeURIComponent(JSON.stringify({access_token:'fixture-token',refresh_token:'fixture-refresh',expires_at:Math.floor(Date.now()/1000)+3600,expires_in:3600,token_type:'bearer',user:{id:owner,email:'fixture@example.test',aud:'authenticated'}})),domain:'127.0.0.1',path:'/'}]);
 const calls={paid:0},id=lengthy?long:'fixture';
 const cluster={theme_name:lengthy?long:'Control',description:lengthy?long:'A saved cluster',patent_ids:[id,'second'],ipc_codes:[],top_assignees:[],filing_trend:[]};
 await page.route('**/api/**',r=>{
  const paid=r.request().method()==='POST';if(paid)calls.paid++;
  const path=new URL(r.request().url()).pathname;
  if(path.endsWith('/analyze-claims'))return r.fulfill({json:paid?generated:cached});
  if(path.endsWith('/evidence'))return r.fulfill({json:{evidence_version:1,requested_jurisdiction:'us',clusters:[cluster],citation_links:[{source:id,target:'second',strength:0.8,is_ai_inferred:true}],warnings:[],patents:[{patent_id:id,title:lengthy?long:'Saved evidence',evidence_status:'available',evidence:{version:1,observations:[{provider:'synthetic',provider_record_id:id,publication_id:lengthy?long:null,source_url:null,retrieved_at:null,matching_queries:[lengthy?long:'fixture query'],text:lengthy?long:'Exact synthetic evidence',text_type:'synthetic',language:'en',dates:{priority:null,filing:null,publication:null},requested_jurisdiction:'us',jurisdiction_filter:null,coverage_limitations:['Synthetic test only']}]}},{patent_id:'second',title:'Second saved record',abstract:'Second synthetic text',evidence:null,evidence_status:'legacy_unknown'}]}});
  if(path.endsWith(job))return r.fulfill({json:{job_id:job,status:'completed'}});
  return r.fulfill({status:503,json:{detail:'Test usage unavailable'}});
 });
 await page.route('**/rest/v1/**',r=>r.fulfill({json:r.request().url().includes('search_results')?{clusters:[cluster],citation_links:[],white_space_analysis:`### Gap 1: ${lengthy?long:'Synthetic gap'}\n**Viability: Unknown**\n${lengthy?long:'Synthetic opportunity'}`,final_report:`# Saved report\n\n${lengthy?long:'Synthetic report'}`,coverage_warnings:[]}:{invention_idea:lengthy?long:'Synthetic invention',created_at:'2026-01-01T00:00:00Z'}}));
 return calls;
}
test('malformed cached overlap is visibly excluded, valid rows survive, no paid replacement',async({page,context})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const calls=await setup(page,context,{cached:{claims:[{...claim,likely_claims:null},{...claim,patent_id:'valid'}],warnings:[{},'Saved warning']}});
 await page.goto(`/results/${job}`);
 await expect(page.getByText('Saved aspect',{exact:true})).toBeVisible();
 await expect(page.getByText(/Excluded.*malformed overlap/).first()).toBeVisible();
 await page.reload();await expect(page.getByText('Saved aspect',{exact:true})).toBeVisible();
 expect(calls.paid).toBe(0);expect(errors).toEqual([]);
});
test('malformed generated overlap is excluded after one explicit generation',async({page,context})=>{
 const calls=await setup(page,context,{cached:{claims:null},generated:{claims:[{...claim,likely_claims:null}],warnings:null}});
 await page.goto(`/results/${job}`);await page.getByRole('button',{name:'Generate claims',exact:true}).click();
 await expect(page.getByText(/Excluded.*malformed overlap/).first()).toBeVisible();
 await expect(page.getByRole('heading',{name:'Saved report',exact:true})).toBeVisible();expect(calls.paid).toBe(1);
});
for(const cached of [{claims:'bad'},{claims:[{...claim,title:{}},{...claim,overlap_level:'unsafe'}]}, {}, null])test(`malformed overlap response ${JSON.stringify(cached)} cannot crash or generate`,async({page,context})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));const calls=await setup(page,context,{cached});
 await page.goto(`/results/${job}`);await expect(page.getByText(/Excluded.*malformed overlap/).first()).toBeVisible();
 await expect(page.getByRole('heading',{name:'Saved report',exact:true})).toBeVisible();expect(calls.paid).toBe(0);expect(errors).toEqual([]);
});
test('loading and read error show the overlap inference notice once',async({page,context})=>{
 const calls=await setup(page,context);let pending;await page.route('**/analyze-claims',r=>{pending=r;});
 await page.goto(`/results/${job}`);await expect(page.getByText('Loading saved claims...')).toBeVisible();
 await expect(page.getByText(notice,{exact:false})).toHaveCount(1);
 await pending.fulfill({status:503,json:{detail:'Saved cache unavailable'}});
 await expect(page.getByRole('button',{name:'Retry saved claims'})).toBeVisible();
 await expect(page.getByText(notice,{exact:false})).toHaveCount(1);expect(calls.paid).toBe(0);
});
for(const width of [320,390,1280])test(`entire results page fits ${width}px with long text and usable actions`,async({page,context})=>{
 await context.grantPermissions(['clipboard-read','clipboard-write']);
 await page.setViewportSize({width,height:900});const calls=await setup(page,context,{lengthy:true,cached:{claims:[{...claim,patent_id:long,title:long,likely_claims:[long],overlap_explanation:long,differentiators:long}]}});
 await page.goto(`/results/${job}`);await page.getByRole('button',{name:new RegExp(long)}).first().click();await expect(page.getByTestId('evidence-text')).toHaveText(long);
 await page.locator('.pm-graph-panel svg g').first().dispatchEvent('click');
 await expect(page.getByRole('button',{name:'Close',exact:true})).toBeVisible();
 const overflowing=await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e instanceof HTMLElement&&e.getBoundingClientRect().width>0&&(e.getBoundingClientRect().right>innerWidth+1||e.getBoundingClientRect().left< -1)).map(e=>({tag:e.tagName,class:e.className,right:e.getBoundingClientRect().right})).slice(0,20));
 expect(overflowing).toEqual([]);expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
 await page.getByRole('button',{name:'Close',exact:true}).click();
 await page.evaluate(()=>{window.print=()=>{window.__printed=true;};});await page.getByRole('button',{name:'⤓ Export',exact:true}).click();expect(await page.evaluate(()=>window.__printed)).toBe(true);
 await page.getByRole('button',{name:'Share',exact:true}).click();await expect(page.locator('.pm-sticky-meta').getByRole('button',{name:'Copied!',exact:true})).toBeVisible();expect(await page.evaluate(()=>navigator.clipboard.readText())).toBe(page.url());
 await page.getByRole('button',{name:'⚖ Claims',exact:true}).click();await expect(page.getByRole('button',{name:'Regenerate claims',exact:true})).toBeInViewport();
 expect(await page.locator('.pm-sticky-bar').evaluate(el=>el.getBoundingClientRect().top >= document.querySelector('.pm-nav').getBoundingClientRect().bottom-1)).toBe(true);
 await page.getByRole('button',{name:'⤓ Export',exact:true}).click();
 expect(await page.locator('.pm-ws-head .pm-badge').evaluate(el=>el.getBoundingClientRect().height)).toBeLessThan(35);
 await page.evaluate(()=>window.scrollTo(0,0));
 await page.screenshot({path:`/tmp/pm-release-${width}.png`,fullPage:true});
 await page.screenshot({path:`/tmp/pm-release-${width}-viewport.png`});expect(calls.paid).toBe(0);
});

test('legacy chunked auth cookies remain readable and sign-out clears private results',async({page,context})=>{
 const calls=await setup(page,context);
 const cookies=await context.cookies();const auth=cookies.find(c=>c.name.includes('auth-token'));
 await context.clearCookies();const mid=Math.floor(auth.value.length/2);
 await context.addCookies([{name:auth.name+'.0',value:auth.value.slice(0,mid),domain:'127.0.0.1',path:'/'},{name:auth.name+'.1',value:auth.value.slice(mid),domain:'127.0.0.1',path:'/'}]);
 await page.route('**/auth/v1/logout*',r=>r.fulfill({status:204}));
 await page.goto(`/results/${job}`);await expect(page.getByText('Saved aspect',{exact:true})).toBeVisible();
 await page.getByTitle('fixture@example.test',{exact:true}).click();
 await expect(page.getByText(/Sign in to access this private analysis/)).toBeVisible();
 await expect(page.getByText('Saved aspect',{exact:true})).toHaveCount(0);
 expect((await context.cookies()).filter(c=>c.name.startsWith(auth.name))).toEqual([]);
 expect(calls.paid).toBe(0);
});

test('dashboard history recovers from error after same-owner session refresh',async({page,context})=>{
 await setup(page,context);let recovered=false;
 await page.route('**/rest/v1/searches*',r=>recovered?r.fulfill({json:[]}):r.fulfill({status:503,json:{message:'Fixture history outage'}}));
 await page.goto('/dashboard');
 await expect(page.getByText('Could not load your analyses. Reload to retry or sign in again.')).toBeVisible();
 recovered=true;
 const host=new URL(process.env.NEXT_PUBLIC_SUPABASE_URL||'https://example.supabase.co').hostname.split('.')[0];
 await page.evaluate(({host,owner})=>{const channel=new BroadcastChannel(`sb-${host}-auth-token`);channel.postMessage({event:'TOKEN_REFRESHED',session:{access_token:'refreshed-token',user:{id:owner,email:'fixture@example.test'}}});channel.close();},{host,owner});
 await expect(page.getByText('Could not load your analyses. Reload to retry or sign in again.')).toHaveCount(0);
 await expect(page.getByText('No searches yet')).toBeVisible();
});
