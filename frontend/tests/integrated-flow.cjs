const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const { execFileSync } = require('node:child_process');
const cfg = JSON.parse(fs.readFileSync(process.env.PM_INTEGRATED_FIXTURE, 'utf8'));
const sql = query => execFileSync('psql',['-X','-qAt','-v','ON_ERROR_STOP=1',cfg.db,'-c',query],{encoding:'utf8'}).trim();
const cookieName=`sb-${new URL(cfg.supabase).hostname.split('.')[0]}-auth-token`;
async function signIn(context, session) {
 // Exercise legacy JSON session cookies: upgrades must preserve saved sessions.
 await context.addCookies([{name:cookieName,value:encodeURIComponent(JSON.stringify(session)),domain:'127.0.0.1',path:'/'}]);
}
test('real browser API worker database publication, refresh, reopening and isolation',async({page,context,browser,request})=>{
 const errors=[],blocked=[],paid=[];
 page.on('pageerror',e=>errors.push(e.message));
 const restrict = r=>{
  const url=new URL(r.request().url());
  if(!['127.0.0.1','localhost','::1'].includes(url.hostname)){blocked.push(url.origin);return r.abort();}
  if(r.request().method()==='POST'&&url.pathname.startsWith('/api/'))paid.push(url.pathname);
  return r.continue();
 };
 await context.route('**/*',restrict);
 await signIn(context,cfg.sessions[0]);
 await page.goto('/');
 await page.locator('#invention').fill('Synthetic integrated irrigation controller with humidity sensors and adaptive scheduling.');
 const submitted=page.waitForResponse(r=>r.request().method()==='POST'&&r.url()===`${cfg.api}/jobs`);
 await page.getByRole('button',{name:/Analyze patents/}).click();
 const response=await submitted;expect(response.status()).toBe(202);
 const {job_id:job}=await response.json();expect(job).toMatch(/^[0-9a-f-]{36}$/);
 await expect(page).toHaveURL(new RegExp(`/results/${job}$`));
 await expect(page.getByRole('heading',{name:'Retrieved evidence',exact:true})).toBeVisible({timeout:60000});
 const records=page.getByRole('list',{name:'Saved evidence records'}).getByRole('button');
 await expect(records).toHaveCount(10);
 await records.first().click();
 const exact=await page.getByTestId('evidence-text').textContent();expect(exact.length).toBeGreaterThan(20);
 await expect(page.getByText('Synthetic demo text',{exact:true})).toBeVisible();
 const fingerprint=sql(`SELECT md5(row_to_json(r)::text) FROM search_results r WHERE search_id='${job}'`);
 const usage=()=>sql(`SELECT operation||':'||count(*) FROM usage_reservations WHERE user_id='${cfg.sessions[0].user.id}' GROUP BY operation ORDER BY operation`);
 expect(usage()).toBe('job:1');
 expect(sql(`SELECT state||':'||(execution_inputs->>'mock_mode') FROM analysis_queue WHERE search_id='${job}'`)).toBe('finished:true');
 for(let i=0;i<2;i++){
  if(i===0)await page.reload();else{await page.goto('/dashboard');await page.goto(`/results/${job}`);}
  await expect(records).toHaveCount(10);await records.first().click();
  expect(await page.getByTestId('evidence-text').textContent()).toBe(exact);
 }
 expect(sql(`SELECT md5(row_to_json(r)::text) FROM search_results r WHERE search_id='${job}'`)).toBe(fingerprint);
 expect(usage()).toBe('job:1');expect(paid).toEqual(['/api/jobs']);
 for (const width of [320,390,1280]) {
  await page.setViewportSize({width,height:900});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:`${cfg.output}/results-${width}.png`,fullPage:true});
  await page.screenshot({path:`${cfg.output}/results-${width}-viewport.png`});
 }
 // Actual API ownership and database RLS, with a separate authenticated account.
 const other=await browser.newContext();await other.route('**/*',restrict);
 await signIn(other,cfg.sessions[1]);const foreign=await other.newPage();
 await foreign.goto(`/results/${job}`);await expect(foreign.getByText(/unavailable to your account/)).toBeVisible();
 await expect(foreign.getByRole('heading',{name:'Retrieved evidence',exact:true})).toHaveCount(0);
 for(const tail of ['', '/evidence','/analyze-claims']){
  const denied=await request.get(`${cfg.api}/jobs/${job}${tail}`,{headers:{Authorization:`Bearer ${cfg.sessions[1].access_token}`}});expect(denied.status()).toBe(404);
 }
 for(const table of ['searches','search_results','patents']){
  const key=table==='searches'?'id':'search_id';const denied=await request.get(`${cfg.supabase}/rest/v1/${table}?${key}=eq.${job}`,{headers:{apikey:cfg.anon,Authorization:`Bearer ${cfg.sessions[1].access_token}`}});
  expect(denied.status()).toBe(200);expect(await denied.json()).toEqual([]);
 }
 await other.close();
 // Account switch in the already-open tab clears prior-owner content.
 await context.clearCookies();await signIn(context,cfg.sessions[1]);
 await page.evaluate(({name,session})=>{const channel=new BroadcastChannel(name);channel.postMessage({event:'SIGNED_IN',session});channel.close();},{name:cookieName,session:cfg.sessions[1]});
 await expect(page.getByText(/unavailable to your account/)).toBeVisible();
 await expect(page.getByTestId('evidence-text')).toHaveCount(0);
 expect(usage()).toBe('job:1');expect(paid).toEqual(['/api/jobs']);expect(errors).toEqual([]);
 expect(blocked.every(origin=>origin==='https://fonts.googleapis.com'||origin==='https://fonts.gstatic.com')).toBe(true);
 fs.writeFileSync(`${cfg.output}/evidence.json`,JSON.stringify({job,patents:10,usage:usage(),queue:'finished',refreshes:2,accountIsolation:true,paidRequests:paid,externalBrowserOriginsBlocked:[...new Set(blocked)],pageErrors:errors,reportFingerprint:fingerprint},null,2));
});
