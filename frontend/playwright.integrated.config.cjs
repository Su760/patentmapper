const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
 testDir:'./tests',testMatch:'integrated-flow.cjs',workers:1,retries:0,forbidOnly:true,
 timeout:90000,
 use:{baseURL:'http://127.0.0.1:3119',browserName:'chromium'},
 webServer:{command:'npm run start -- --hostname 127.0.0.1 --port 3119',url:'http://127.0.0.1:3119',reuseExistingServer:false},
});
