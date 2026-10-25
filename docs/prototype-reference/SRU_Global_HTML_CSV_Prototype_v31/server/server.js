import express from 'express';
import session from 'express-session';
import multer from 'multer';
import bcrypt from 'bcryptjs';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import {fileURLToPath} from 'url';
import dotenv from 'dotenv';
dotenv.config();
const __dirname=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(__dirname,'..');
const dataDir=path.resolve(root,process.env.DATA_DIR||'data');
const uploadDir=path.resolve(root,process.env.UPLOAD_DIR||'uploads');
fs.mkdirSync(uploadDir,{recursive:true});
const app=express();
app.use(express.json({limit:'2mb'}));app.use(express.urlencoded({extended:true}));
app.use(session({secret:process.env.SESSION_SECRET||'CHANGE_ME',resave:false,saveUninitialized:false,cookie:{httpOnly:true,sameSite:'lax',secure:false,maxAge:8*60*60*1000}}));
app.use(express.static(root));
function csvRows(file){const raw=fs.readFileSync(path.join(dataDir,file),'utf8').trim();const [head,...lines]=raw.split(/\r?\n/);const headers=head.split(',');return lines.filter(Boolean).map(line=>{const vals=[];let c='',q=false;for(let i=0;i<line.length;i++){const ch=line[i],n=line[i+1];if(ch==='"'){if(q&&n==='"'){c+='"';i++}else q=!q}else if(ch===','&&!q){vals.push(c);c=''}else c+=ch}vals.push(c);return Object.fromEntries(headers.map((h,i)=>[h,vals[i]||'']))})}
function appendActivity(user,action,module,reference='',details=''){const file=path.join(dataDir,'activity_log.csv');const line=[`A${Date.now()}`,new Date().toISOString(),user?.id||'',user?.username||'',user?.role||'',action,module,reference,'server',details].map(v=>String(v).replace(/"/g,'""')).map(v=>`"${v}"`).join(',')+'\n';if(!fs.existsSync(file))fs.writeFileSync(file,'activity_id,timestamp,user_id,username,role,action,module,reference,ip_or_device,details\n');fs.appendFileSync(file,line)}
function requireAuth(req,res,next){if(!req.session.user)return res.status(401).json({error:'Authentication required'});next()}
function requireRole(...roles){return (req,res,next)=>{if(!req.session.user||!roles.includes(req.session.user.role))return res.status(403).json({error:'Insufficient role'});next()}}
app.get('/api/session',(req,res)=>res.json({user:req.session.user||null}));
app.post('/api/login',(req,res)=>{const {identifier,password}=req.body||{};const users=csvRows('users.csv');const u=users.find(x=>[x.username,x.email,x.phone].some(v=>(v||'').toLowerCase()===(identifier||'').trim().toLowerCase()));if(!u||u.status!=='active')return res.status(401).json({error:'Invalid credentials'});const ok=u.password_hash?bcrypt.compareSync(password,u.password_hash):crypto.createHash('sha256').update(password).digest('hex')===u.password_sha256;if(!ok)return res.status(401).json({error:'Invalid credentials'});req.session.user={id:u.id,username:u.username,email:u.email,phone:u.phone,role:u.role};appendActivity(req.session.user,'login','auth','','Successful login');res.json({user:req.session.user})});
app.post('/api/logout',(req,res)=>req.session.destroy(()=>res.json({ok:true})));
app.get('/api/users',requireRole('Admin'),(req,res)=>res.json(csvRows('users.csv')));
app.get('/api/roles',requireAuth,(req,res)=>res.json(csvRows('roles.csv')));
app.get('/api/menu-config',requireRole('Admin'),(req,res)=>res.json(csvRows('menu_config.csv')));
app.get('/api/company',requireAuth,(req,res)=>res.json(csvRows('company.csv')[0]||{}));
app.get('/api/accounts',requireRole('Accounts','Admin'),(req,res)=>res.json(csvRows('accounts.csv')));
app.get('/api/transactions',requireRole('Accounts','Admin'),(req,res)=>res.json(csvRows('transactions.csv')));
app.get('/api/stock',requireRole('Contributor','Accounts','Admin'),(req,res)=>res.json(csvRows('stock.csv')));
app.get('/api/bills',requireRole('Contributor','Accounts','Admin'),(req,res)=>res.json(csvRows('bills.csv')));
const upload=multer({storage:multer.diskStorage({destination:uploadDir,filename:(req,file,cb)=>cb(null,Date.now()+'-'+file.originalname.replace(/[^a-zA-Z0-9._-]/g,'_'))}),limits:{fileSize:15*1024*1024}});
app.post('/api/bills/upload',requireRole('Contributor','Accounts','Admin'),upload.single('bill'),(req,res)=>{if(!req.file)return res.status(400).json({error:'No bill file'});appendActivity(req.session.user,'upload','bills',req.file.filename,req.file.originalname);res.json({ok:true,file:req.file.filename,original_name:req.file.originalname,uploaded_by:req.session.user.username,uploaded_at:new Date().toISOString()})});
const providerConfig={google:{configured:!!(process.env.GOOGLE_CLIENT_ID&&process.env.GOOGLE_CLIENT_SECRET)},facebook:{configured:!!(process.env.FACEBOOK_CLIENT_ID&&process.env.FACEBOOK_CLIENT_SECRET)},yahoo:{configured:!!(process.env.YAHOO_CLIENT_ID&&process.env.YAHOO_CLIENT_SECRET)},microsoft:{configured:!!(process.env.MICROSOFT_CLIENT_ID&&process.env.MICROSOFT_CLIENT_SECRET)},instagram:{configured:!!(process.env.INSTAGRAM_CLIENT_ID&&process.env.INSTAGRAM_CLIENT_SECRET)}};
app.get('/auth/:provider',(req,res)=>{const p=req.params.provider;if(!providerConfig[p])return res.status(404).send('Unknown provider');if(!providerConfig[p].configured)return res.status(501).send(`${p} OAuth is not configured. Add provider credentials to server/.env.`);res.status(501).send(`OAuth adapter placeholder for ${p}. Wire the provider authorization-code flow and callback using the provider SDK/official endpoints.`)});
app.get('/auth/:provider/callback',(req,res)=>res.status(501).send('Federated callback adapter not configured.'));
app.listen(process.env.PORT||8080,()=>console.log(`SRU Global portal running on http://localhost:${process.env.PORT||8080}`));
