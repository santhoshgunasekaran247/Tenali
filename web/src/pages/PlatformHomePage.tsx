import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDownRight, ArrowRight, BarChart3, Boxes, CircleDollarSign, ClipboardList, Globe2, Menu, Sparkles, Store, UsersRound, X } from "lucide-react";
import { policyPath, policyRequest, type PublicPolicy } from "../features/policies";
import productTour from "../content/product-tour.json";
import "./platform-home.css";

const capabilities = [
  { icon: Boxes, number: "01", title: "Add the things you sell", text: "Keep product names, prices and stock in one list. Already have an Excel sheet? Use bulk upload instead of typing everything again." },
  { icon: ClipboardList, number: "02", title: "Make a bill for a sale", text: "Choose the customer and products, check the amount and save the bill. Keep your purchase bills here too." },
  { icon: BarChart3, number: "03", title: "See what is left in stock", text: "Check how much stock you own, what is running low and where items are kept when you have more than one store." },
  { icon: CircleDollarSign, number: "04", title: "Know who has paid", text: "Record money received and money paid. Check which customers still owe you and which suppliers you need to pay." },
  { icon: Store, number: "05", title: "Sell on your own website", text: "Your products become your online shop. Customers can send a WhatsApp list enquiry or place an order. Add your own domain when you are ready." },
  { icon: Sparkles, number: "06", title: "Ask Tenali AI for help", text: "Get AI help alongside your everyday work. Turn a bill into a draft or a catalogue into an Excel upload. You review the details before saving. AI needs to be enabled." },
];

function tourTime(seconds: number) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function PlatformHomePage() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [contactEmail, setContactEmail] = useState("");
  const [contactUnavailable, setContactUnavailable] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [activeChapter, setActiveChapter] = useState(0);
  const [videoNotice, setVideoNotice] = useState("");
  const [videoMuted, setVideoMuted] = useState(false);
  const seekToChapter = (seconds: number) => {
    const video = videoRef.current;
    if (!video) return;
    setVideoNotice("");
    video.currentTime = seconds;
    video.focus();
    void video.play().catch(() => setVideoNotice("Press the video's play button to continue, or read the steps below."));
  };
  useEffect(() => {
    const previous = document.title;
    document.title = "Tenali | Your business, online shop and AI helper";
    return () => { document.title = previous; };
  }, []);
  useEffect(() => {
    let active = true;
    void policyRequest<PublicPolicy>("/legal/platform/contact").then(policy => {
      if (active) {
        setContactEmail(policy.content.contact_email);
        setContactUnavailable(!policy.content.contact_email);
      }
    }).catch(() => {
      if (active) setContactUnavailable(true);
    });
    return () => { active = false; };
  }, []);

  return <div className="marketing">
    <a className="marketing-skip" href="#main-content">Skip to content</a>
    <header className="marketing-header">
      <a className="marketing-brand" href="#top" aria-label="Tenali home"><img src="/tenali-logo.png" alt="Tenali" /></a>
      <button className="marketing-menu" type="button" aria-expanded={menuOpen} aria-controls="marketing-nav" aria-label={menuOpen ? "Close menu" : "Open menu"} onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? <X size={21} /> : <Menu size={21} />}</button>
      <nav id="marketing-nav" className={menuOpen ? "marketing-nav is-open" : "marketing-nav"} aria-label="Main navigation" onClick={() => setMenuOpen(false)}>
        <a href="#what-we-do">What you can do</a><a href="#how-it-works">Getting started</a><a href="#demo">Watch the guide</a><a href="#about">Who it is for</a><a href="#contact">Contact</a>
        <Link className="marketing-nav-login" to="/login">Sign in</Link><Link className="marketing-button small" to="/register">Set up my business <ArrowRight size={16} /></Link>
      </nav>
    </header>

    <main id="main-content">
      <section className="marketing-hero" id="top">
        <div className="marketing-container hero-grid">
          <div className="hero-copy">
            <p className="marketing-kicker"><span /> FOR SHOPS, TRADERS AND SELLERS</p>
            <h1>Your business. Your online shop.<br/><em>Your AI helper.</em></h1>
            <p className="hero-description">Tenali is an app for running your shop and selling online. Keep products, bills, stock and payments together. Get AI help beside your everyday work, and give customers your own ecommerce website—not just another listing.</p>
            <div className="marketing-actions"><Link className="marketing-button" to="/register">Set up my business <ArrowRight size={18} /></Link><a className="marketing-button secondary" href="#demo">Watch the step-by-step guide <ArrowDownRight size={18} /></a></div>
            <p className="hero-note">WhatsApp list enquiries · Razorpay payments · Shiprocket or your own delivery · Your own domain. Connect the services you need.</p>
          </div>
          <div className="hero-visual">
            <div className="hero-visual-label"><span /> A QUICK CHECK OF YOUR BUSINESS</div>
            <img className="workspace-screenshot" src="/tenali-workspace-preview.jpg" alt="Tenali operations dashboard showing sample business data" />
            <p className="preview-caption">A real Tenali screen, with sample numbers.</p>
          </div>
        </div>
      </section>

      <section className="marketing-strip" aria-label="Everyday tasks"><div className="marketing-container"><span>WHAT DID I SELL?</span><span>WHAT IS LEFT?</span><span>WHO STILL NEEDS TO PAY?</span><ArrowRight size={19}/></div></section>

      <section className="marketing-section" id="what-we-do"><div className="marketing-container">
        <div className="section-intro"><div><p className="marketing-kicker">WHAT YOU CAN DO</p><h2>The work you do every day.<br/><em>Without jumping between lists.</em></h2></div><p>A sale, a purchase, a payment or a stock check. Keep these records in the same app, so you know where to look when you need an answer.</p></div>
        <div className="capability-grid">{capabilities.map(({icon: Icon, number, title, text}) => <article className="capability" key={number}><div className="capability-top"><Icon size={23} strokeWidth={1.6}/><span>{number}</span></div><h3>{title}</h3><p>{text}</p></article>)}</div>
        <div className="marketing-online-guide"><h3>Your website, connected to your daily work</h3><p>Customers can collect several products into a WhatsApp enquiry list, then talk to you about quantities and prices. That conversation is not a paid order. To accept online purchases, connect Razorpay for payments and choose Shiprocket, your own courier or store pickup. You can also connect a domain you own.</p><p>These are choices, not compulsory extras. AI, online checkout and provider accounts need the relevant setup and access; they are not switched on just by signing up.</p></div>
      </div></section>

      <section className="marketing-how" id="how-it-works"><div className="marketing-container how-grid"><div><p className="marketing-kicker light">GETTING STARTED</p><h2>Start with your shop.<br/>Then your first product.</h2><p>You do not have to set up everything at once. Begin with the basics and use the other tools when you need them.</p><Link className="marketing-text-link light-link" to="/register">Set up my business <ArrowRight size={17}/></Link></div>
        <div className="steps"><div><span>01</span><div><h3>Create your business account</h3><p>Sign up, then add your business details and stores.</p></div></div><div><span>02</span><div><h3>Add products and people</h3><p>Add what you sell, your customers and your suppliers. Use Excel for a longer product list.</p></div></div><div><span>03</span><div><h3>Record your first sale</h3><p>Make a bill, record the payment and check your stock. Share your online shop when it is ready.</p></div></div></div>
      </div></section>

      <section className="marketing-section demo-section" id="demo"><div className="marketing-container demo-grid"><div className="demo-intro"><p className="marketing-kicker">WATCH THE GUIDE</p><h2>See how to use Tenali.<br/><em>One step at a time.</em></h2><p>Start with AI, accounts and money borrowed or lent. Then follow purchase bills, stores, menus, your dashboard, products, sales and your online shop. We explain what the fields mean, not just where to click.</p><p className="demo-disclaimer">A narrated guide with a gentle Indian-English female voice and quiet background music. Read the instructions in the dark panel and follow the app in the light panel. Captions and the written guide work without sound. Actual app screens use sample data; no customer records or live AI replies are shown. Some features need to be enabled for your business.</p><a className="marketing-text-link" href="#demo-transcript" onClick={() => document.getElementById("demo-transcript")?.setAttribute("open", "")}>Read every step instead <ArrowRight size={17}/></a></div>
        <div className="demo-player"><video controls preload="metadata" playsInline ref={videoRef} aria-label="How to use Tenali: a narrated step-by-step guide" poster="/tenali-product-tour-poster.jpg"
          onVolumeChange={event => setVideoMuted(event.currentTarget.muted || event.currentTarget.volume === 0)}
          onTimeUpdate={event => setActiveChapter(productTour.chapters.reduce((current, chapter, index) => event.currentTarget.currentTime >= chapter.start ? index : current, 0))}
          onError={() => setVideoNotice("The video could not be loaded. You can still read every step below.")}>
          <source src="/tenali-product-tour.mp4" type="video/mp4"/><track kind="captions" src="/tenali-product-tour.vtt" srcLang="en" label="English"/><track kind="chapters" src="/tenali-product-tour-chapters.vtt" srcLang="en" label="Guide chapters"/>Your browser cannot play this video. Read the steps below.</video><div className="demo-player-caption"><span><span className="demo-dot"/> INSTRUCTIONS LEFT · APP SCREEN RIGHT</span><span>{tourTime(productTour.duration)} · SAMPLE DATA · PAUSE ANY TIME</span><button type="button" className="demo-audio-toggle" aria-pressed={videoMuted} onClick={() => {
            const video = videoRef.current;
            if (!video) return;
            if (videoMuted) { video.muted = false; if (video.volume === 0) video.volume = 1; }
            else video.muted = true;
            setVideoMuted(video.muted);
          }}>{videoMuted ? "Unmute guide" : "Mute guide"}</button></div></div>
        {videoNotice ? <p className="demo-notice" role="status">{videoNotice}</p> : null}
        <nav className="demo-chapters" aria-label="Video chapters"><h3>Jump to the part you need</h3><p>Choose a time to play that chapter. Use full screen for a closer look at the app.</p><ol>{productTour.chapters.map((chapter, index) => <li key={chapter.start}><button type="button" aria-current={activeChapter === index ? "true" : undefined} onClick={() => seekToChapter(chapter.start)}><span className="demo-chapter-time">{tourTime(chapter.start)}</span><span><strong>{chapter.title}</strong><small>{chapter.summary}</small></span></button></li>)}</ol></nav>
        <details className="demo-transcript" id="demo-transcript"><summary>Read the full step-by-step guide</summary>
          {productTour.chapters.map((chapter, index) => <section key={chapter.start}><h3>{tourTime(chapter.start)} — {chapter.title}</h3><ol>{productTour.steps.filter(step => step.chapter === index).map(step => <li key={step.start}><span className="demo-step-time">{tourTime(step.start)}–{tourTime(step.end)}</span><strong>{step.title}</strong><p>{step.instruction}</p><p className="demo-step-note">{step.note}</p></li>)}</ol></section>)}
        </details>
      </div></section>

      <section className="marketing-about" id="about"><div className="marketing-container about-grid"><div><p className="marketing-kicker">WHO IS IT FOR?</p><h2>For people who buy<br/><em>and sell products.</em></h2></div><div><p className="about-lead">A shop, a trading business or a seller with stock to manage. Tenali helps you keep the everyday records together, with your own online shop and AI help when you need it.</p><p>Use it yourself or give your team their own access. You can keep selling at your counter without opening an online shop. Tenali is made by Sru Global.</p><div className="about-values"><span><UsersRound size={19}/> Work on your own or with a team</span><span><Globe2 size={19}/> Your own online shop</span></div></div></div></section>

      <section className="marketing-contact" id="contact"><div className="marketing-container contact-grid"><div><p className="marketing-kicker light">LET’S GET STARTED</p><h2>Your next bill.<br/>Your next stock check.</h2><p>Keep them in one place. Set up your business or contact us if you need help deciding.</p></div><div className="contact-actions"><Link className="marketing-button contact-button" to="/register">Set up my business <ArrowRight size={18}/></Link>{contactEmail ? <a className="contact-link" href={`mailto:${contactEmail}`}>{contactEmail} <ArrowRight size={17}/></a> : contactUnavailable ? <p>Contact details could not be loaded. Please try the business information page.</p> : <p>Loading contact details…</p>}<Link className="contact-link" to={policyPath("platform", "contact")}>Contact & business information <ArrowRight size={17}/></Link><p>Questions about an order? Please contact the seller directly through their storefront.</p></div></div></section>
    </main>
    <footer className="marketing-footer"><div className="marketing-container footer-grid"><div><img src="/tenali-logo.png" alt="Tenali" /><p>Products, bills, stock and your online shop.<br/>Made by Sru Global.</p></div><div><strong>EXPLORE</strong><a href="#what-we-do">What you can do</a><a href="#demo">How to use Tenali</a><Link to="/login">Sign in</Link></div><div><strong>INFORMATION</strong><Link to={policyPath("platform", "contact")}>Contact</Link><Link to={policyPath("platform", "privacy")}>Privacy</Link><Link to={policyPath("platform", "terms")}>Terms</Link><Link to={policyPath("platform", "data-deletion")}>Data deletion</Link></div></div><div className="marketing-container footer-bottom"><span>© {new Date().getFullYear()} Sru Global. Tenali.</span><a href="#top">BACK TO TOP ↑</a></div></footer>
  </div>;
}
