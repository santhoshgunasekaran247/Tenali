(function(){
  'use strict';
  const $ = id => document.getElementById(id);
  const DEMO = {
    'admin@sruglobal.in': {id:'U001',username:'admin',email:'admin@sruglobal.in',phone:'+919361748842',role:'Admin',status:'active',password:'Admin@123'},
    'contributor@sruglobal.in': {id:'U002',username:'contributor',email:'contributor@sruglobal.in',phone:'+919361748843',role:'Contributor',status:'active',password:'Contrib@123'},
    'accounts@sruglobal.in': {id:'U003',username:'accounts',email:'accounts@sruglobal.in',phone:'+919361748844',role:'Accounts',status:'active',password:'Accounts@123'},
    'user@sruglobal.in': {id:'U004',username:'user',email:'user@sruglobal.in',phone:'+919361748845',role:'User',status:'active',password:'User@123'}
  };
  const ALIASES = {
    admin:'admin@sruglobal.in', contributor:'contributor@sruglobal.in', accounts:'accounts@sruglobal.in', user:'user@sruglobal.in',
    '+919361748842':'admin@sruglobal.in', '+919361748843':'contributor@sruglobal.in', '+919361748844':'accounts@sruglobal.in', '+919361748845':'user@sruglobal.in'
  };
  function normalize(v){ return String(v||'').trim().toLowerCase(); }
  function findUser(identifier){
    const id=normalize(identifier); const key=ALIASES[id]||id;
    if(DEMO[key]) return DEMO[key];
    return Object.values(DEMO).find(u=>normalize(u.email)===id || normalize(u.username)===id || normalize(u.phone)===id) || null;
  }
  function login(){
    const err=$('login-error'); err.textContent='';
    const id=$('identifier').value, pw=$('password').value;
    const u=findUser(id);
    if(!u || u.status!=='active' || pw!==u.password){ err.textContent='Invalid credentials or disabled account.'; return; }
    localStorage.setItem('sru_session', JSON.stringify({id:u.id,username:u.username,role:u.role,email:u.email,phone:u.phone,at:new Date().toISOString()}));
    location.replace('portal.html?demo='+encodeURIComponent(u.username)+'#dashboard');
  }
  const form=$('login-form');
  if(form) form.addEventListener('submit',function(e){e.preventDefault();login();});
  document.querySelectorAll('[data-provider]').forEach(btn=>btn.addEventListener('click',()=>alert(btn.textContent+' login will be connected through the server-side OAuth configuration.')));
  $('phone-verify').onclick=e=>{e.preventDefault();alert('Phone OTP verification is a server-side production integration.');};
  $('email-verify').onclick=e=>{e.preventDefault();alert('Email verification is a server-side production integration.');};
})();
