(function(){
  'use strict';
  const $=id=>document.getElementById(id);
  function submit(){
    const id=String($('admin-identifier').value||'').trim().toLowerCase(), pw=$('admin-password').value;
    const ok=(id==='admin'||id==='admin@sruglobal.in'||id==='+919361748842') && pw==='Admin@123';
    if(!ok){$('admin-error').textContent='Admin credentials are invalid.';return;}
    localStorage.setItem('sru_session',JSON.stringify({id:'U001',username:'admin',role:'Admin',email:'admin@sruglobal.in',phone:'+919361748842',at:new Date().toISOString()}));
    location.replace('portal.html#dashboard');
  }
  $('admin-login-form').addEventListener('submit',e=>{e.preventDefault();submit();});
})();
