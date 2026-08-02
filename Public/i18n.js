/* ApexPayGo shared internationalization.
   Default language: French (for Quebec). English available; Spanish added later.
   Usage in HTML:
     <element data-i18n="key">          -> sets textContent
     <input data-i18n-ph="key">          -> sets placeholder
     <element data-i18n-html="key">       -> sets innerHTML
     <div id="langSwitch"></div>          -> a FR/EN switcher is injected here
   In JS: i18n.t('key'), i18n.setLang('fr'|'en'), i18n.getLang()
*/
(function () {
  const T = {
    fr: {
      brand_tagline: "Système de paie",
      // index / landing
      welcome_title: "Bienvenue chez ApexPayGo",
      welcome_sub: "Système de gestion de la paie",
      logged_in_msg: "Vous êtes connecté à votre compte de paie.",
      name_label: "Nom",
      email_label: "Courriel",
      logout: "Déconnexion",
      manage_msg: "Gérez votre paie et vos données d'employés avec ApexPayGo.",
      sign_in: "Se connecter",
      create_account: "Créer un compte",
      // sign in
      signin_title: "Se connecter",
      password_label: "Mot de passe",
      email_ph: "votre@courriel.com",
      password_ph: "Entrez votre mot de passe",
      signing_in: "Connexion en cours...",
      signin_success: "✓ Connexion réussie! Redirection...",
      signin_failed: "Échec de la connexion",
      no_account: "Vous n'avez pas de compte?",
      create_one: "Créer un compte",
      // sign up
      signup_title: "Créer un compte",
      fullname_label: "Nom complet",
      fullname_ph: "Jean Tremblay",
      password_ph_signup: "Au moins 6 caractères",
      sign_up: "S'inscrire",
      creating_account: "Création du compte...",
      signup_success: "✓ Compte créé avec succès! Redirection...",
      signup_failed: "Échec de l'inscription",
      have_account: "Vous avez déjà un compte?",
      // setup
      setup_title: "Configurez votre entreprise",
      setup_sub: "Configurez votre compte ApexPayGo",
      trial_banner: "🎉 Essai gratuit de 7 jours – aucune carte de crédit requise",
      company_type: "Type d'entreprise",
      select_ph: "Sélectionnez...",
      single_company: "Entreprise unique",
      multi_company: "Multi-entreprises",
      company_name: "Nom de l'entreprise",
      company_name_ph: "Corporation Acme",
      company_address: "Adresse de l'entreprise",
      company_address_ph: "123 rue Principale, Ville, Province",
      industry: "Secteur d'activité",
      ind_technology: "Technologie",
      ind_healthcare: "Santé",
      ind_finance: "Finance",
      ind_retail: "Commerce de détail",
      ind_manufacturing: "Fabrication",
      ind_education: "Éducation",
      ind_other: "Autre",
      complete_setup: "Terminer et aller au tableau de bord",
      setting_up: "Configuration...",
      setup_failed: "Échec de la configuration",
      generic_error: "Erreur"
    },
    en: {
      brand_tagline: "Payroll System",
      welcome_title: "Welcome to ApexPayGo",
      welcome_sub: "Payroll Management System",
      logged_in_msg: "You are logged in to your payroll account.",
      name_label: "Name",
      email_label: "Email",
      logout: "Logout",
      manage_msg: "Manage your payroll and employee data with ApexPayGo.",
      sign_in: "Sign In",
      create_account: "Create Account",
      signin_title: "Sign In",
      password_label: "Password",
      email_ph: "your@email.com",
      password_ph: "Enter your password",
      signing_in: "Signing In...",
      signin_success: "✓ Signed in successfully! Redirecting...",
      signin_failed: "Sign in failed",
      no_account: "Don't have an account?",
      create_one: "Create one",
      signup_title: "Create Account",
      fullname_label: "Full Name",
      fullname_ph: "John Doe",
      password_ph_signup: "At least 6 characters",
      sign_up: "Sign Up",
      creating_account: "Creating Account...",
      signup_success: "✓ Account created successfully! Redirecting...",
      signup_failed: "Sign up failed",
      have_account: "Already have an account?",
      setup_title: "Setup Your Company",
      setup_sub: "Configure your ApexPayGo account",
      trial_banner: "🎉 7-Day Free Trial – No Credit Card Required",
      company_type: "Company Type",
      select_ph: "Select...",
      single_company: "Single Company",
      multi_company: "Multi-Company",
      company_name: "Company Name",
      company_name_ph: "Acme Corporation",
      company_address: "Company Address",
      company_address_ph: "123 Main Street, City, Province",
      industry: "Industry",
      ind_technology: "Technology",
      ind_healthcare: "Healthcare",
      ind_finance: "Finance",
      ind_retail: "Retail",
      ind_manufacturing: "Manufacturing",
      ind_education: "Education",
      ind_other: "Other",
      complete_setup: "Complete Setup & Go to Dashboard",
      setting_up: "Setting up...",
      setup_failed: "Setup failed",
      generic_error: "Error"
    }
  };

  function getLang() { return localStorage.getItem('lang') || 'fr'; }
  function t(key) { const l = getLang(); return (T[l] && T[l][key]) || (T.en && T.en[key]) || key; }

  function apply(root) {
    root = root || document;
    root.querySelectorAll('[data-i18n]').forEach(function (el) { el.textContent = t(el.getAttribute('data-i18n')); });
    root.querySelectorAll('[data-i18n-ph]').forEach(function (el) { el.setAttribute('placeholder', t(el.getAttribute('data-i18n-ph'))); });
    root.querySelectorAll('[data-i18n-html]').forEach(function (el) { el.innerHTML = t(el.getAttribute('data-i18n-html')); });
    document.documentElement.lang = getLang();
    document.querySelectorAll('.lang-switch [data-lang]').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-lang') === getLang());
    });
  }

  function setLang(l) { localStorage.setItem('lang', l); apply(); document.dispatchEvent(new Event('langchange')); }

  function switcherHTML() {
    return '<button type="button" data-lang="fr" onclick="i18n.setLang(\'fr\')">FR</button>' +
           '<button type="button" data-lang="en" onclick="i18n.setLang(\'en\')">EN</button>';
  }

  window.i18n = { t: t, getLang: getLang, setLang: setLang, apply: apply };

  document.addEventListener('DOMContentLoaded', function () {
    var style = document.createElement('style');
    style.textContent =
      '.lang-switch{position:fixed;top:12px;right:14px;display:flex;gap:4px;z-index:3000}' +
      '.lang-switch button{padding:4px 10px;border:1px solid rgba(120,120,140,.4);background:rgba(255,255,255,.85);color:#1e40af;border-radius:4px;font-size:12px;font-weight:700;cursor:pointer;line-height:1}' +
      '.lang-switch button.active{background:#1e40af;color:#fff;border-color:#1e40af}';
    document.head.appendChild(style);
    document.querySelectorAll('#langSwitch').forEach(function (el) {
      el.className = 'lang-switch';
      el.innerHTML = switcherHTML();
    });
    apply();
  });
})();
