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
      generic_error: "Erreur",
      dashboard_title: "Tableau de bord ApexPayGo",
      trial_active_title: "🎉 Essai gratuit actif",
      trial_days_remaining: "Il vous reste {days} jour(s)",
      trial_expired_title: "⚠️ Essai expiré",
      trial_expired_text: "Votre essai gratuit est terminé. Veuillez mettre à niveau pour continuer à utiliser ApexPayGo.",
      upgrade_now: "Mettre à niveau — à partir de 20$/mois",
      status_active: "Actif",
      status_trial_expired: "Essai expiré — Mise à niveau requise",
      company_info: "Renseignements sur l'entreprise",
      account_info: "Renseignements du compte",
      payroll_system: "Système de paie",
      label_company_name: "Nom de l'entreprise :",
      label_company_type: "Type d'entreprise :",
      label_address: "Adresse :",
      label_industry: "Secteur :",
      label_name: "Nom :",
      label_email: "Courriel :",
      label_status: "Statut :",
      label_payroll_processing: "Traitement de la paie :",
      payroll_ready: "Prêt",
      edit_company_info: "Modifier les infos de l'entreprise",
      open_payroll_system: "Ouvrir le système de paie",
      edit_company_title: "Modifier les renseignements de l'entreprise",
      company_address_label: "Adresse de l'entreprise",
      cancel: "Annuler",
      save_changes: "Enregistrer",
      update_success: "Renseignements de l'entreprise mis à jour avec succès!",
      update_failed: "Échec de la mise à jour"
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
      generic_error: "Error",
      dashboard_title: "ApexPayGo Dashboard",
      trial_active_title: "🎉 7-Day Free Trial Active",
      trial_days_remaining: "You have {days} day(s) remaining",
      trial_expired_title: "⚠️ Trial Expired",
      trial_expired_text: "Your free trial has ended. Please upgrade to continue using ApexPayGo.",
      upgrade_now: "Upgrade Now — starting at $20/month",
      status_active: "Active",
      status_trial_expired: "Trial Expired - Upgrade Required",
      company_info: "Company Information",
      account_info: "Account Information",
      payroll_system: "Payroll System",
      label_company_name: "Company Name:",
      label_company_type: "Company Type:",
      label_address: "Address:",
      label_industry: "Industry:",
      label_name: "Name:",
      label_email: "Email:",
      label_status: "Status:",
      label_payroll_processing: "Payroll Processing:",
      payroll_ready: "Ready",
      edit_company_info: "Edit Company Info",
      open_payroll_system: "Open Payroll System",
      edit_company_title: "Edit Company Information",
      company_address_label: "Company Address",
      cancel: "Cancel",
      save_changes: "Save Changes",
      update_success: "Company information updated successfully!",
      update_failed: "Update failed"
    }
  };

  function getLang() { return localStorage.getItem('lang') || 'fr'; }
  function t(key, vars) {
    const l = getLang();
    let s = (T[l] && T[l][key]) || (T.en && T.en[key]) || key;
    if (vars) { Object.keys(vars).forEach(function (k) { s = s.replace('{' + k + '}', vars[k]); }); }
    return s;
  }

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
      '.lang-switch.lang-switch-inline{position:static;top:auto;right:auto;z-index:auto}' +
      '.lang-switch button{padding:4px 10px;border:1px solid rgba(120,120,140,.4);background:rgba(255,255,255,.85);color:#1e40af;border-radius:4px;font-size:12px;font-weight:700;cursor:pointer;line-height:1}' +
      '.lang-switch button.active{background:#1e40af;color:#fff;border-color:#1e40af}' +
      '.navbar .lang-switch button{background:rgba(255,255,255,.15);color:#fff;border-color:rgba(255,255,255,.4)}' +
      '.navbar .lang-switch button.active{background:#fff;color:#1e40af;border-color:#fff}';
    document.head.appendChild(style);
    document.querySelectorAll('#langSwitch').forEach(function (el) {
      // If this page has a navbar, group the switch together with the last
      // navbar button (Logout) so the navbar keeps 2 flex children (title +
      // right-side group) instead of floating fixed over the corner.
      var navbar = document.querySelector('.navbar');
      if (navbar && !navbar.contains(el)) {
        var lastBtn = navbar.lastElementChild;
        var wrap = document.createElement('div');
        wrap.style.display = 'flex';
        wrap.style.alignItems = 'center';
        wrap.style.gap = '10px';
        navbar.insertBefore(wrap, lastBtn);
        wrap.appendChild(el);
        wrap.appendChild(lastBtn);
      }
      el.className = navbar ? 'lang-switch lang-switch-inline' : 'lang-switch';
      el.innerHTML = switcherHTML();
    });
    apply();
  });
})();
