import { useEffect } from "react";
import { Link } from "react-router-dom";
import { ArrowDownRight, ArrowRight, BarChart3, Boxes, CircleDollarSign, ClipboardList, Globe2, Menu, Sparkles, Store, UsersRound, X } from "lucide-react";
import { useState } from "react";
import { policyPath, policyRequest, type PublicPolicy } from "../features/policies";
import "./platform-home.css";

const capabilities = [
  { icon: BarChart3, number: "01", title: "Dashboards for clarity", text: "Bring sales, cash flow and operational follow-ups together in a dashboard and reports." },
  { icon: Sparkles, number: "02", title: "Tenali AI assistance", text: "Ask about your business records and get help navigating everyday work where AI is enabled." },
  { icon: Boxes, number: "03", title: "Inventory, in context", text: "Organise products, variants and stock across your stores, with the information your team needs close at hand." },
  { icon: ClipboardList, number: "04", title: "Sales & purchasing", text: "Create bills and purchase records, track orders and keep your day-to-day transactions moving." },
  { icon: CircleDollarSign, number: "05", title: "Money, made clearer", text: "Follow receivables, payments and account activity so the next action is easier to see." },
  { icon: Store, number: "06", title: "A storefront of your own", text: "Share your catalogue online and configure your storefront, orders and checkout for your business." },
];

export function PlatformHomePage() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [contactEmail, setContactEmail] = useState("");
  const [contactUnavailable, setContactUnavailable] = useState(false);
  useEffect(() => {
    const previous = document.title;
    document.title = "Tenali | A clearer way to run your business";
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
        <a href="#what-we-do">What we do</a><a href="#how-it-works">How it works</a><a href="#demo">Product tour</a><a href="#about">About</a><a href="#contact">Contact</a>
        <Link className="marketing-nav-login" to="/login">Sign in</Link><Link className="marketing-button small" to="/register">Get started <ArrowRight size={16} /></Link>
      </nav>
    </header>

    <main id="main-content">
      <section className="marketing-hero" id="top">
        <div className="marketing-container hero-grid">
          <div className="hero-copy">
            <p className="marketing-kicker"><span /> BUILT FOR THE BUSINESS OF EVERY DAY</p>
            <h1>Make room for <em>better business.</em></h1>
            <p className="hero-description">Bring stock, sales and your storefront together with clear dashboards and AI assistance, in a workspace designed to be affordable, accessible and simple.</p>
            <div className="marketing-actions"><Link className="marketing-button" to="/register">Get started <ArrowRight size={18} /></Link><a className="marketing-button secondary" href="#demo">See the product tour <ArrowDownRight size={18} /></a></div>
            <p className="hero-note">One workspace. Simple tools for everyday decisions.</p>
          </div>
          <div className="hero-visual">
            <div className="hero-visual-label"><span /> YOUR BUSINESS, IN VIEW</div>
            <img className="workspace-screenshot" src="/tenali-workspace-preview.jpg" alt="Tenali operations dashboard showing sample business data" />
            <p className="preview-caption">ACTUAL WORKSPACE SCREEN · SAMPLE DATA</p>
          </div>
        </div>
      </section>

      <section className="marketing-strip"><div className="marketing-container"><span>LESS FRAGMENTATION.</span><span>MORE CLARITY.</span><span>BETTER FOLLOW-THROUGH.</span><ArrowRight size={19}/></div></section>

      <section className="marketing-section" id="what-we-do"><div className="marketing-container">
        <div className="section-intro"><div><p className="marketing-kicker">01 / WHAT WE DO</p><h2>All the essentials.<br/><em>Better connected.</em></h2></div><p>Running a business means keeping track of many moving parts. Tenali brings the everyday work together, so your team can spend less time piecing it together.</p></div>
        <div className="capability-grid">{capabilities.map(({icon: Icon, number, title, text}) => <article className="capability" key={number}><div className="capability-top"><Icon size={23} strokeWidth={1.6}/><span>{number}</span></div><h3>{title}</h3><p>{text}</p></article>)}</div>
      </div></section>

      <section className="marketing-how" id="how-it-works"><div className="marketing-container how-grid"><div><p className="marketing-kicker light">02 / HOW IT WORKS</p><h2>From the first item<br/>to the next opportunity.</h2><p>Start with the foundations, then connect the work around them. Tenali helps you move from scattered tasks to a more complete view.</p><Link className="marketing-text-link light-link" to="/register">Create your workspace <ArrowRight size={17}/></Link></div>
        <div className="steps"><div><span>01</span><div><h3>Set up your workspace</h3><p>Add your business details, team and stores.</p></div></div><div><span>02</span><div><h3>Bring your operations together</h3><p>Organise products, manage transactions and follow activity.</p></div></div><div><span>03</span><div><h3>Stay close to what matters</h3><p>Share your catalogue and use your dashboard to follow up.</p></div></div></div>
      </div></section>

      <section className="marketing-section demo-section" id="demo"><div className="marketing-container demo-grid"><div><p className="marketing-kicker">03 / A QUICK LOOK</p><h2>See the bigger picture<br/><em>in under a minute.</em></h2><p>See Tenali's dashboard and AI interface in a short screen-based tour.</p><p className="demo-disclaimer">Screens show the actual application with sample data. Features and availability depend on your workspace configuration.</p><a className="marketing-text-link" href="#demo-transcript">Read the tour transcript <ArrowRight size={17}/></a></div>
        <div className="demo-player"><video controls preload="metadata" playsInline aria-label="Tenali workspace screen tour" poster="/tenali-workspace-preview.jpg"><source src="/tenali-product-tour.webm" type="video/webm"/>Your browser cannot play this video. Read the transcript below.</video><div className="demo-player-caption"><span><span className="demo-dot"/> THE TENALI PRODUCT TOUR</span><span>REAL SCREENS · SAMPLE DATA · NO AUDIO</span></div></div>
        <details className="demo-transcript" id="demo-transcript"><summary>Product tour transcript</summary><p>The tour shows actual Tenali screens with sample data. The dashboard displays financial information and follow-ups. The Tenali AI welcome screen offers guidance and help preparing work for review when enabled. The dashboard returns with a reminder about simple everyday decisions. The tour has no audio and does not show live interactions or AI responses.</p></details>
      </div></section>

      <section className="marketing-about" id="about"><div className="marketing-container about-grid"><div><p className="marketing-kicker">04 / WHO WE ARE</p><h2>Practical tools for<br/><em>real business.</em></h2></div><div><p className="about-lead">Tenali is a business platform by Sru Global, built to make everyday operations easier to see and manage.</p><p>We believe useful software should bring the right information together without making work feel more complicated. Whether you are managing products, serving customers or following up with your team, Tenali gives those tasks a common home.</p><div className="about-values"><span><UsersRound size={19}/> Made for teams</span><span><Globe2 size={19}/> Built for business</span></div></div></div></section>

      <section className="marketing-contact" id="contact"><div className="marketing-container contact-grid"><div><p className="marketing-kicker light">05 / LET’S CONNECT</p><h2>Ready for a clearer<br/>way to work?</h2><p>Explore Tenali for your business, or get in touch to learn more.</p></div><div className="contact-actions"><Link className="marketing-button contact-button" to="/register">Create a workspace <ArrowRight size={18}/></Link>{contactEmail ? <a className="contact-link" href={`mailto:${contactEmail}`}>{contactEmail} <ArrowRight size={17}/></a> : contactUnavailable ? <p>Contact details could not be loaded. Please try the business information page.</p> : <p>Loading contact details…</p>}<Link className="contact-link" to={policyPath("platform", "contact")}>Contact & business information <ArrowRight size={17}/></Link><p>Questions about an order? Please contact the seller directly through their storefront.</p></div></div></section>
    </main>
    <footer className="marketing-footer"><div className="marketing-container footer-grid"><div><img src="/tenali-logo.png" alt="Tenali" /><p>A clearer way to run your business.<br/>A platform by Sru Global.</p></div><div><strong>EXPLORE</strong><a href="#what-we-do">What we do</a><a href="#demo">Product tour</a><Link to="/login">Sign in</Link></div><div><strong>INFORMATION</strong><Link to={policyPath("platform", "contact")}>Contact</Link><Link to={policyPath("platform", "privacy")}>Privacy</Link><Link to={policyPath("platform", "terms")}>Terms</Link><Link to={policyPath("platform", "data-deletion")}>Data deletion</Link></div></div><div className="marketing-container footer-bottom"><span>© {new Date().getFullYear()} Sru Global. Tenali.</span><a href="#top">BACK TO TOP ↑</a></div></footer>
  </div>;
}
