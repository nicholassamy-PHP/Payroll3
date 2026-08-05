from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
import hashlib
import uuid
from datetime import datetime, timedelta
import json
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer

load_dotenv()

app = Flask(__name__, static_folder='Public', static_url_path='')
CORS(app)

@app.after_request
def add_no_cache_headers(response):
    # We ship frequent small updates to the JS/HTML files; without this,
    # browsers can keep serving an old cached copy after a redeploy, which
    # looks like "the fix didn't work" even though the server is current.
    if request.path.endswith(('.js', '.html', '.css')) or request.path == '/':
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

DATABASE_URL = os.getenv('DATABASE_URL')

# ---- Stripe billing config (set these in Render's environment) ----
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
STRIPE_PRICE_BASE = os.getenv('STRIPE_PRICE_BASE')          # $20/mo recurring price id
STRIPE_PRICE_EMPLOYEE = os.getenv('STRIPE_PRICE_EMPLOYEE')  # $5/mo per-employee recurring price id
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')  # whsec_... from the Stripe webhook
APP_URL = os.getenv('APP_URL', 'https://payroll3-sr7d.onrender.com')

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

# ==================== AUTH HELPERS ====================
# SECRET_KEY signs the login tokens. Set a strong value in Render's env vars;
# the fallback only keeps local dev working.
SECRET_KEY = os.getenv('SECRET_KEY') or 'change-me-set-SECRET_KEY-in-render'
_token_signer = URLSafeTimedSerializer(SECRET_KEY, salt='apexpay-auth')
TOKEN_MAX_AGE = 7 * 24 * 3600  # tokens valid for 7 days

def make_token(user_id):
    return _token_signer.dumps({'uid': user_id})

def get_auth_user_id():
    """Return the user id from a valid Bearer token, or None."""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    try:
        return _token_signer.loads(auth[7:], max_age=TOKEN_MAX_AGE).get('uid')
    except Exception:
        return None

def verify_password(stored_hash, password):
    """Check a password. Also accepts legacy unsalted SHA-256 so old accounts still work."""
    if stored_hash and len(stored_hash) == 64 and all(c in '0123456789abcdef' for c in stored_hash.lower()):
        return hashlib.sha256(password.encode()).hexdigest() == stored_hash
    try:
        return check_password_hash(stored_hash, password)
    except Exception:
        return False

def is_legacy_hash(stored_hash):
    return bool(stored_hash) and len(stored_hash) == 64 and all(c in '0123456789abcdef' for c in stored_hash.lower())

def owns_company(cur, user_id, company_id):
    cur.execute('SELECT 1 FROM companies WHERE id = %s AND user_id = %s', (company_id, user_id))
    return cur.fetchone() is not None

# ==================== TAX TABLES (year-keyed) ====================
# To update for a new year: copy the latest block, change the ~15 numbers to
# match the official Revenu Quebec + CRA source-deduction guides, and add it
# under the new year key. The calculation logic below never needs to change.
# A payroll run always uses the block matching its pay-period year, so past
# paycheques stay correct.
#
# Sources for 2026 (verify each January):
#   Revenu Quebec - Employers: Principal Changes for 2026
#   CRA T4127 Payroll Deductions Formulas / PDOC
INF = float('inf')

TAX_YEARS = {
    2026: {
        'qpp': {
            'max_pensionable': 74600.0,     # YMPE
            'basic_exemption': 3500.0,
            'base_rate': 0.053,             # base plan (credited against tax)
            'enhancement_rate': 0.010,      # first additional (deducted from income)
            'qpp2_ceiling': 85000.0,        # YAMPE
            'qpp2_rate': 0.04,              # second additional (deducted from income)
        },
        'ei_employer_multiple': 1.4,        # employer EI = 1.4x employee
        'fss': {                            # employer Health Services Fund (auto by industry + payroll)
            'threshold_low': 1000000.0,     # <= this total payroll -> flat low rate
            'threshold_high': 7800000.0,    # >= this -> max rate
            'rate_low_other': 0.0165,       # <=$1M, general sectors
            'rate_low_primary_mfg': 0.0125, # <=$1M, primary/manufacturing sectors
            'rate_high': 0.0426,            # >=$7.8M
            # industries (from company setup) that qualify for the reduced rate
            'primary_mfg_industries': ['manufacturing', 'primary', 'agriculture', 'forestry', 'mining', 'fishing'],
        },
        'qpip': {
            'max_insurable': 103000.0,
            'employee_rate': 0.00430,
            'employer_rate': 0.00602,
        },
        'ei': {
            'max_insurable': 68900.0,
            'employee_rate': 0.0130,        # Quebec reduced employee rate
            'employer_rate': 0.0182,
        },
        'federal': {
            'basic_personal_amount': 16452.0,
            'quebec_abatement': 0.165,      # reduces federal tax for Quebec residents
            'brackets': [
                (58523.0, 0.14),
                (117045.0, 0.205),
                (181440.0, 0.26),
                (258482.0, 0.29),
                (INF, 0.33),
            ],
        },
        'quebec': {
            'basic_personal_amount': 18952.0,
            'brackets': [
                (51780.0, 0.14),
                (103545.0, 0.19),
                (126000.0, 0.24),
                (INF, 0.2575),
            ],
        },
    },
}

DEFAULT_TAX_YEAR = 2026

def _bracket_tax(annual_income, brackets):
    """Progressive tax on an annual amount given [(upper_threshold, rate), ...]."""
    tax = 0.0
    lower = 0.0
    for upper, rate in brackets:
        if annual_income > lower:
            taxed = min(annual_income, upper) - lower
            tax += taxed * rate
            lower = upper
        else:
            break
    return tax

def calculate_quebec_deductions(gross_pay, periods_per_year, year=DEFAULT_TAX_YEAR):
    """
    Estimate Quebec source deductions for one pay period using the annualized
    formula method (income x periods -> annual amounts -> divide back).

    This is an ESTIMATE for a standard employee. It must be validated against
    the CRA PDOC and Revenu Quebec WinRAS calculators before real-world use.
    Returns a dict of per-period amounts.
    """
    cfg = TAX_YEARS.get(int(year), TAX_YEARS[DEFAULT_TAX_YEAR])
    p = periods_per_year if periods_per_year and periods_per_year > 0 else 26
    annual = gross_pay * p

    # --- QPP: base (credited) vs enhanced (deducted from income) ---
    q = cfg['qpp']
    contributory = max(0.0, min(annual, q['max_pensionable']) - q['basic_exemption'])
    qpp_base = contributory * q['base_rate']
    qpp_enh = contributory * q['enhancement_rate']
    qpp2_contributory = max(0.0, min(annual, q['qpp2_ceiling']) - q['max_pensionable'])
    qpp2 = qpp2_contributory * q['qpp2_rate']
    qpp_total_annual = qpp_base + qpp_enh + qpp2
    enhancement_deduction = qpp_enh + qpp2   # reduces taxable income

    # --- EI (Quebec reduced) ---
    ei = cfg['ei']
    ei_annual = min(annual, ei['max_insurable']) * ei['employee_rate']

    # --- QPIP ---
    qpip = cfg['qpip']
    qpip_annual = min(annual, qpip['max_insurable']) * qpip['employee_rate']

    # Taxable income = income minus the QPP enhancement deduction.
    taxable = annual - enhancement_deduction

    # Non-refundable credits at the lowest rate (14%): basic personal amount
    # plus base QPP + EI + QPIP.
    credit_contribs = qpp_base + ei_annual + qpip_annual

    # --- Federal income tax (with Quebec abatement) ---
    fed = cfg['federal']
    fed_basic = _bracket_tax(taxable, fed['brackets'])
    fed_credits = 0.14 * (fed['basic_personal_amount'] + credit_contribs)
    fed_tax_annual = max(0.0, fed_basic - fed_credits) * (1 - fed['quebec_abatement'])

    # --- Quebec income tax ---
    qc = cfg['quebec']
    qc_basic = _bracket_tax(taxable, qc['brackets'])
    qc_credits = 0.14 * (qc['basic_personal_amount'] + credit_contribs)
    qc_tax_annual = max(0.0, qc_basic - qc_credits)

    qpp_amt = round(qpp_total_annual / p, 2)
    ei_amt = round(ei_annual / p, 2)
    qpip_amt = round(qpip_annual / p, 2)
    federal_tax = round(fed_tax_annual / p, 2)
    quebec_tax = round(qc_tax_annual / p, 2)
    net = round(gross_pay - qpp_amt - ei_amt - qpip_amt - federal_tax - quebec_tax, 2)

    # --- Employer contributions (for remittance reports) ---
    employer_qpp = qpp_amt  # employer matches employee QPP
    employer_ei = round((ei_annual * cfg.get('ei_employer_multiple', 1.4)) / p, 2)
    employer_qpip = round((min(annual, qpip['max_insurable']) * qpip['employer_rate']) / p, 2)
    employer_fss = round((annual * cfg.get('fss_rate', 0.0)) / p, 2)

    return {
        'qpp': qpp_amt,
        'qpip': qpip_amt,
        'ei': ei_amt,
        'federal_tax': federal_tax,
        'quebec_tax': quebec_tax,
        'net_pay': net,
        'employer_qpp': employer_qpp,
        'employer_ei': employer_ei,
        'employer_qpip': employer_qpip,
        'employer_fss': employer_fss,
    }

def fss_rate(industry, total_annual_payroll, year=DEFAULT_TAX_YEAR):
    """Employer Health Services Fund rate, chosen by industry + total payroll."""
    cfg = TAX_YEARS.get(int(year), TAX_YEARS[DEFAULT_TAX_YEAR]).get('fss')
    if not cfg:
        return 0.0
    low = cfg['rate_low_primary_mfg'] if (industry or '').lower() in cfg['primary_mfg_industries'] else cfg['rate_low_other']
    tp = total_annual_payroll or 0
    if tp <= cfg['threshold_low']:
        return low
    if tp >= cfg['threshold_high']:
        return cfg['rate_high']
    # Linear slide between the low rate (at $1M) and the max rate (at $7.8M).
    span = cfg['threshold_high'] - cfg['threshold_low']
    frac = (tp - cfg['threshold_low']) / span
    return round(low + (cfg['rate_high'] - low) * frac, 6)

# ==================== AUTHENTICATION ====================

@app.route('/api/signup', methods=['POST'])
def signup():
    try:
        data = request.json
        name = data.get('name', '').strip()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')

        if not name or not email or not password or len(password) < 6:
            return jsonify({'error': 'Invalid input'}), 400

        password_hash = generate_password_hash(password)
        user_id = str(uuid.uuid4())

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute(
                'INSERT INTO users (id, name, email, password_hash) VALUES (%s, %s, %s, %s)',
                (user_id, name, email, password_hash)
            )
            conn.commit()
        except psycopg2.IntegrityError:
            conn.rollback()
            cur.close()
            conn.close()
            return jsonify({'error': 'Email already exists'}), 409

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'token': make_token(user_id),
            'user': {'id': user_id, 'name': name, 'email': email}
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/signin', methods=['POST'])
def signin():
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')

        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            'SELECT id, name, email, password_hash FROM users WHERE email = %s',
            (email,)
        )
        row = cur.fetchone()

        if not row or not verify_password(row[3], password):
            cur.close()
            conn.close()
            return jsonify({'error': 'Invalid email or password'}), 401

        # Transparently upgrade old SHA-256 hashes to the salted format.
        if is_legacy_hash(row[3]):
            cur.execute('UPDATE users SET password_hash = %s WHERE id = %s',
                        (generate_password_hash(password), row[0]))
            conn.commit()

        user = (row[0], row[1], row[2])

        company = None
        if user:
            cur.execute(
                '''SELECT id, company_name, company_type, company_address, industry, trial_start_date, subscription_status
                   FROM companies WHERE user_id = %s ORDER BY created_at LIMIT 1''',
                (user[0],)
            )
            comp = cur.fetchone()
            if comp:
                company = {
                    'id': comp[0],
                    'company_name': comp[1],
                    'company_type': comp[2],
                    'company_address': comp[3],
                    'industry': comp[4],
                    'trial_start_date': comp[5].strftime('%Y-%m-%d') if comp[5] else None,
                    'subscription_status': comp[6] or 'trial'
                }

        cur.close()
        conn.close()

        return jsonify({
            'token': make_token(user[0]),
            'user': {'id': user[0], 'name': user[1], 'email': user[2]},
            'company': company
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== COMPANY SETUP ====================

@app.route('/api/setup', methods=['POST'])
def setup():
    try:
        user_id = get_auth_user_id()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        data = request.json
        company_name = data.get('companyName', '').strip()
        company_type = data.get('companyType', 'single')
        company_address = data.get('companyAddress', '').strip()
        industry = data.get('industry', '')

        if not company_name:
            return jsonify({'error': 'Missing required fields'}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        # If this user already has a company, return it instead of creating a duplicate.
        cur.execute(
            '''SELECT id, company_name, company_type, company_address, industry, trial_start_date, subscription_status
               FROM companies WHERE user_id = %s ORDER BY created_at LIMIT 1''',
            (user_id,)
        )
        existing = cur.fetchone()
        if existing:
            cur.close()
            conn.close()
            return jsonify({
                'success': True,
                'company': {
                    'id': existing[0],
                    'company_name': existing[1],
                    'company_type': existing[2],
                    'company_address': existing[3],
                    'industry': existing[4],
                    'trial_start_date': existing[5].strftime('%Y-%m-%d') if existing[5] else None,
                    'subscription_status': existing[6] or 'trial'
                }
            }), 200

        company_id = str(uuid.uuid4())
        trial_start_date = datetime.now().strftime('%Y-%m-%d')

        try:
            cur.execute(
                '''INSERT INTO companies
                   (id, user_id, company_name, company_type, company_address, industry, trial_start_date)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                (company_id, user_id, company_name, company_type, company_address, industry, trial_start_date)
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            return jsonify({'error': str(e)}), 500

        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'company': {
                'id': company_id,
                'company_name': company_name,
                'company_type': company_type,
                'company_address': company_address,
                'industry': industry,
                'trial_start_date': trial_start_date,
                'subscription_status': 'trial'
            }
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/company', methods=['GET'])
def get_company():
    """Fresh company lookup (including subscription_status) — the dashboard
    calls this on every load so billing state is never stale, especially
    right after returning from Stripe Checkout."""
    try:
        user_id = get_auth_user_id()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        company_id = request.args.get('companyId')
        if not company_id:
            return jsonify({'error': 'Company ID required'}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        if not owns_company(cur, user_id, company_id):
            cur.close()
            conn.close()
            return jsonify({'error': 'Not authorized'}), 403

        cur.execute(
            '''SELECT id, company_name, company_type, company_address, industry, trial_start_date, subscription_status
               FROM companies WHERE id = %s''',
            (company_id,)
        )
        c = cur.fetchone()
        cur.close()
        conn.close()

        if not c:
            return jsonify({'error': 'Company not found'}), 404

        return jsonify({
            'company': {
                'id': c[0],
                'company_name': c[1],
                'company_type': c[2],
                'company_address': c[3],
                'industry': c[4],
                'trial_start_date': c[5].strftime('%Y-%m-%d') if c[5] else None,
                'subscription_status': c[6] or 'trial'
            }
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/update-company', methods=['PUT'])
def update_company():
    try:
        user_id = get_auth_user_id()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        data = request.json
        company_id = data.get('companyId')
        company_name = data.get('companyName', '').strip()
        company_type = data.get('companyType', 'single')
        company_address = data.get('companyAddress', '').strip()
        industry = data.get('industry', '')

        if not company_id or not company_name:
            return jsonify({'error': 'Missing required fields'}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        if not owns_company(cur, user_id, company_id):
            cur.close()
            conn.close()
            return jsonify({'error': 'Not authorized'}), 403

        try:
            cur.execute(
                '''UPDATE companies
                   SET company_name = %s, company_type = %s, company_address = %s, industry = %s, updated_at = NOW()
                   WHERE id = %s''',
                (company_name, company_type, company_address, industry, company_id)
            )
            conn.commit()

            cur.execute(
                'SELECT id, company_name, company_type, company_address, industry, trial_start_date, subscription_status FROM companies WHERE id = %s',
                (company_id,)
            )
            company = cur.fetchone()
            cur.close()
            conn.close()

            if not company:
                return jsonify({'error': 'Company not found'}), 404

            return jsonify({
                'success': True,
                'company': {
                    'id': company[0],
                    'company_name': company[1],
                    'company_type': company[2],
                    'company_address': company[3],
                    'industry': company[4],
                    'trial_start_date': company[5].strftime('%Y-%m-%d') if company[5] else None,
                    'subscription_status': company[6] or 'trial'
                }
            }), 200
        except Exception as e:
            conn.rollback()
            cur.close()
            conn.close()
            return jsonify({'error': str(e)}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== EMPLOYEES ====================

@app.route('/api/payroll-employees', methods=['GET'])
def get_employees():
    try:
        user_id = get_auth_user_id()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        company_id = request.args.get('companyId')

        if not company_id:
            return jsonify({'error': 'Company ID required'}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        if not owns_company(cur, user_id, company_id):
            cur.close()
            conn.close()
            return jsonify({'error': 'Not authorized'}), 403
        # Pull each employee plus their year-to-date totals (for the Reports tab).
        cur.execute(
            '''SELECT e.id, e.first_name, e.last_name, e.code, e.email, e.active, e.hire_date, e.pay_rate,
                      COALESCE(SUM(pr.gross_pay), 0),
                      COALESCE(SUM(pr.net_pay), 0),
                      COALESCE(SUM(pr.cpp_contribution), 0),
                      COALESCE(SUM(pr.qpip_contribution), 0),
                      COALESCE(SUM(pr.ei_contribution), 0),
                      COALESCE(SUM(pr.federal_tax + pr.provincial_tax), 0)
               FROM employees e
               LEFT JOIN payroll_runs pr ON pr.employee_id = e.id
               WHERE e.company_id = %s
               GROUP BY e.id, e.first_name, e.last_name, e.code, e.email, e.active, e.hire_date, e.pay_rate
               ORDER BY e.last_name, e.first_name''',
            (company_id,)
        )
        employees = cur.fetchall()
        cur.close()
        conn.close()

        result = []
        for emp in employees:
            result.append({
                'id': emp[0],
                'first_name': emp[1],
                'last_name': emp[2],
                'code': emp[3],
                'email': emp[4],
                'active': emp[5],
                'hire_date': emp[6].strftime('%Y-%m-%d') if emp[6] else None,
                'pay_rate': float(emp[7]) if emp[7] is not None else 0,
                'ytd_gross': float(emp[8]),
                'ytd_net': float(emp[9]),
                'ytd_qpp': float(emp[10]),
                'ytd_qpip': float(emp[11]),
                'ytd_ei': float(emp[12]),
                'ytd_tax': float(emp[13])
            })

        return jsonify({'employees': result}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def _fetch_employee(cur, employee_id):
    cur.execute(
        'SELECT id, first_name, last_name, code, email, active, hire_date, pay_rate FROM employees WHERE id = %s',
        (employee_id,)
    )
    emp = cur.fetchone()
    if not emp:
        return None
    return {
        'id': emp[0],
        'first_name': emp[1],
        'last_name': emp[2],
        'code': emp[3],
        'email': emp[4],
        'active': emp[5],
        'hire_date': emp[6].strftime('%Y-%m-%d') if emp[6] else None,
        'pay_rate': float(emp[7]) if emp[7] is not None else 0
    }

@app.route('/api/payroll-employees', methods=['POST'])
def create_employee():
    try:
        user_id = get_auth_user_id()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        data = request.json
        company_id = data.get('companyId')
        first_name = data.get('firstName', '').strip()
        last_name = data.get('lastName', '').strip()
        code = data.get('code', '').strip()
        email = data.get('email', '')
        hire_date = data.get('hireDate')
        pay_rate = data.get('payRate') or 0

        if not company_id or not first_name or not last_name or not code:
            return jsonify({'error': 'First name, last name, and code required'}), 400

        employee_id = str(uuid.uuid4())

        conn = get_db_connection()
        cur = conn.cursor()

        if not owns_company(cur, user_id, company_id):
            cur.close()
            conn.close()
            return jsonify({'error': 'Not authorized'}), 403

        try:
            cur.execute(
                '''INSERT INTO employees (id, company_id, first_name, last_name, code, email, hire_date, pay_rate)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                (employee_id, company_id, first_name, last_name, code, email or None, hire_date or None, pay_rate)
            )
            conn.commit()
        except psycopg2.IntegrityError:
            conn.rollback()
            cur.close()
            conn.close()
            return jsonify({'error': 'Employee code already exists'}), 409

        employee = _fetch_employee(cur, employee_id)
        cur.close()
        conn.close()

        return jsonify({'success': True, 'employee': employee}), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/payroll-employees', methods=['PUT'])
def update_employee():
    try:
        user_id = get_auth_user_id()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        data = request.json
        employee_id = data.get('employeeId') or data.get('id')

        if not employee_id:
            return jsonify({'error': 'Employee ID required'}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        # Verify the employee belongs to a company this user owns.
        cur.execute(
            '''SELECT 1 FROM employees e JOIN companies c ON c.id = e.company_id
               WHERE e.id = %s AND c.user_id = %s''',
            (employee_id, user_id)
        )
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({'error': 'Not authorized'}), 403

        existing = _fetch_employee(cur, employee_id)
        if not existing:
            cur.close()
            conn.close()
            return jsonify({'error': 'Employee not found'}), 404

        # Only overwrite fields that were actually provided; keep the rest as-is.
        first_name = data['firstName'].strip() if 'firstName' in data else existing['first_name']
        last_name = data['lastName'].strip() if 'lastName' in data else existing['last_name']
        email = data['email'] if 'email' in data else existing['email']
        hire_date = data['hireDate'] if 'hireDate' in data else existing['hire_date']
        active = data['active'] if 'active' in data else existing['active']
        pay_rate = data['payRate'] if 'payRate' in data else existing['pay_rate']

        cur.execute(
            '''UPDATE employees
               SET first_name = %s, last_name = %s, email = %s, hire_date = %s, active = %s, pay_rate = %s, updated_at = NOW()
               WHERE id = %s''',
            (first_name, last_name, email, hire_date or None, active, pay_rate, employee_id)
        )
        conn.commit()

        employee = _fetch_employee(cur, employee_id)
        cur.close()
        conn.close()

        return jsonify({'success': True, 'employee': employee}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== PAYROLL CALCULATION ====================

# Pay frequency label -> number of pay periods per year (used to annualize).
PERIODS_PER_YEAR = {
    'weekly': 52,
    'biweekly': 26,
    'semimonthly': 24,
    'monthly': 12,
}

def calculate_gross_pay(hours, pay_rate):
    rate = float(pay_rate or 0)
    paid_hours = (
        (hours.get('regular_hours') or 0)
        + (hours.get('holiday_paid_hours') or 0)
        + (hours.get('vacation_paid_hours') or 0)
        + (hours.get('special_hours') or 0)
        + (hours.get('maternity_hours') or 0)
        + (hours.get('ssl_hours') or 0)
    )
    other_amount = hours.get('other_amount') or 0
    return round(paid_hours * rate + other_amount, 2)

@app.route('/api/payroll-calculate', methods=['POST'])
def calculate_payroll():
    try:
        data = request.json
        company_id = data.get('companyId')
        pay_end_date = data.get('payEndDate')
        payment_date = data.get('paymentDate')
        hours_map = data.get('hours', {})
        pay_frequency = data.get('payFrequency', 'biweekly')
        periods_per_year = PERIODS_PER_YEAR.get(pay_frequency, 26)

        if not company_id or not pay_end_date or not payment_date:
            return jsonify({'error': 'Company, pay end date and payment date are required'}), 400

        user_id = get_auth_user_id()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        payroll_year = int(str(pay_end_date)[:4])

        conn = get_db_connection()
        cur = conn.cursor()

        if not owns_company(cur, user_id, company_id):
            cur.close()
            conn.close()
            return jsonify({'error': 'Not authorized'}), 403

        # Company industry drives the FSS (Health Services Fund) rate.
        cur.execute('SELECT industry FROM companies WHERE id = %s', (company_id,))
        crow = cur.fetchone()
        company_industry = crow[0] if crow else ''

        # Create a new pay period (next number for this year).
        cur.execute(
            'SELECT COALESCE(MAX(pay_number), 0) + 1 FROM pay_periods WHERE company_id = %s AND payroll_year = %s',
            (company_id, payroll_year)
        )
        pay_number = cur.fetchone()[0]

        period_id = str(uuid.uuid4())
        cur.execute(
            '''INSERT INTO pay_periods
               (id, company_id, pay_end_date, payment_date, pay_number, payroll_year, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s)''',
            (period_id, company_id, pay_end_date, payment_date, pay_number, payroll_year, 'completed')
        )

        cur.execute(
            'SELECT id, first_name, last_name, pay_rate, code FROM employees WHERE company_id = %s AND active = true',
            (company_id,)
        )
        employees = cur.fetchall()

        results = []

        for emp in employees:
            emp_id = emp[0]
            emp_name = f"{emp[1]} {emp[2]}"
            pay_rate = emp[3]
            emp_hours = hours_map.get(emp_id, {})

            gross_pay = calculate_gross_pay(emp_hours, pay_rate)
            d = calculate_quebec_deductions(gross_pay, periods_per_year, payroll_year)
            net_pay = d['net_pay']

            # Persist the hours that were entered for this employee/period.
            cur.execute(
                '''INSERT INTO hours_input
                   (id, period_id, employee_id, regular_hours, holiday_paid_hours, vacation_paid_hours,
                    special_hours, maternity_hours, ssl_hours, other_amount)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (period_id, employee_id) DO NOTHING''',
                (str(uuid.uuid4()), period_id, emp_id,
                 emp_hours.get('regular_hours') or 0,
                 emp_hours.get('holiday_paid_hours') or 0,
                 emp_hours.get('vacation_paid_hours') or 0,
                 emp_hours.get('special_hours') or 0,
                 emp_hours.get('maternity_hours') or 0,
                 emp_hours.get('ssl_hours') or 0,
                 emp_hours.get('other_amount') or 0)
            )

            # Year-to-date from earlier periods this year.
            cur.execute(
                '''SELECT COALESCE(SUM(gross_pay), 0), COALESCE(SUM(net_pay), 0)
                   FROM payroll_runs WHERE employee_id = %s
                   AND period_id IN (SELECT id FROM pay_periods WHERE company_id = %s AND payroll_year = %s AND pay_number < %s)''',
                (emp_id, company_id, payroll_year, pay_number)
            )
            ytd_data = cur.fetchone()
            ytd_gross = float(ytd_data[0]) + gross_pay
            ytd_net = float(ytd_data[1]) + net_pay

            # payroll_runs columns are reused for Quebec:
            #   cpp_contribution -> QPP, provincial_tax -> Quebec tax,
            #   qpip_contribution -> QPIP (added via migration).
            cur.execute(
                '''INSERT INTO payroll_runs
                   (id, period_id, employee_id, gross_pay, cpp_contribution, qpip_contribution, ei_contribution, federal_tax, provincial_tax, net_pay, ytd_gross, ytd_net)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (period_id, employee_id) DO UPDATE SET
                     gross_pay = EXCLUDED.gross_pay,
                     cpp_contribution = EXCLUDED.cpp_contribution,
                     qpip_contribution = EXCLUDED.qpip_contribution,
                     ei_contribution = EXCLUDED.ei_contribution,
                     federal_tax = EXCLUDED.federal_tax,
                     provincial_tax = EXCLUDED.provincial_tax,
                     net_pay = EXCLUDED.net_pay,
                     ytd_gross = EXCLUDED.ytd_gross,
                     ytd_net = EXCLUDED.ytd_net''',
                (str(uuid.uuid4()), period_id, emp_id, gross_pay, d['qpp'], d['qpip'], d['ei'],
                 d['federal_tax'], d['quebec_tax'], net_pay, ytd_gross, ytd_net)
            )

            results.append({
                'employee_name': emp_name,
                'employee_code': emp[4] if len(emp) > 4 else '',
                'gross_pay': gross_pay,
                'qpp': d['qpp'],
                'qpip': d['qpip'],
                'ei': d['ei'],
                'federal_tax': d['federal_tax'],
                'quebec_tax': d['quebec_tax'],
                'net_pay': net_pay,
                'employer_qpp': d['employer_qpp'],
                'employer_ei': d['employer_ei'],
                'employer_qpip': d['employer_qpip'],
                'employer_fss': d['employer_fss'],
                'ytd_gross': ytd_gross,
                'ytd_net': ytd_net
            })

        conn.commit()
        cur.close()
        conn.close()

        def s(field):
            return round(sum(r[field] for r in results), 2)

        totals = {
            'employees_paid': sum(1 for r in results if r['gross_pay'] > 0),
            'gross_total': s('gross_pay'),
            'net_total': s('net_pay'),
            'qpp_total': s('qpp'),
            'qpip_total': s('qpip'),
            'ei_total': s('ei'),
            'tax_total': round(sum(r['federal_tax'] + r['quebec_tax'] for r in results), 2)
        }

        # Remittance summary: what the employer owes each government for this run.
        # CRA gets federal income tax + EI (employee + employer).
        # Revenu Quebec gets Quebec tax + QPP (ee+er) + QPIP (ee+er) + FSS.
        emp_qpp, emp_ei, emp_qpip = s('employer_qpp'), s('employer_ei'), s('employer_qpip')
        fed_tax_total = round(sum(r['federal_tax'] for r in results), 2)
        qc_tax_total = round(sum(r['quebec_tax'] for r in results), 2)

        # FSS is on the employer's TOTAL payroll; rate is chosen by industry + payroll size.
        est_annual_payroll = totals['gross_total'] * periods_per_year
        applied_fss_rate = fss_rate(company_industry, est_annual_payroll, payroll_year)
        emp_fss = round(totals['gross_total'] * applied_fss_rate, 2)

        remittance = {
            'cra': {
                'federal_income_tax': fed_tax_total,
                'ei_employee': totals['ei_total'],
                'ei_employer': emp_ei,
                'total': round(fed_tax_total + totals['ei_total'] + emp_ei, 2),
            },
            'revenu_quebec': {
                'quebec_income_tax': qc_tax_total,
                'qpp_employee': totals['qpp_total'],
                'qpp_employer': emp_qpp,
                'qpip_employee': totals['qpip_total'],
                'qpip_employer': emp_qpip,
                'fss_employer': emp_fss,
                'fss_rate': round(applied_fss_rate * 100, 4),
                'total': round(qc_tax_total + totals['qpp_total'] + emp_qpp + totals['qpip_total'] + emp_qpip + emp_fss, 2),
            },
        }

        return jsonify({
            'success': True,
            'payroll': results,
            'totals': totals,
            'remittance': remittance,
            'payNumber': pay_number
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== YEAR-END SLIPS (T4 / RL-1) ====================

@app.route('/api/year-end', methods=['GET'])
def year_end():
    try:
        user_id = get_auth_user_id()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        company_id = request.args.get('companyId')
        year = request.args.get('year')

        if not company_id or not year:
            return jsonify({'error': 'Company ID and year are required'}), 400

        year = int(year)
        cfg = TAX_YEARS.get(year, TAX_YEARS[DEFAULT_TAX_YEAR])
        ympe = cfg['qpp']['max_pensionable']
        ei_max = cfg['ei']['max_insurable']
        qpip_max = cfg['qpip']['max_insurable']

        conn = get_db_connection()
        cur = conn.cursor()

        if not owns_company(cur, user_id, company_id):
            cur.close()
            conn.close()
            return jsonify({'error': 'Not authorized'}), 403
        cur.execute(
            '''SELECT e.first_name, e.last_name, e.code,
                      COALESCE(SUM(pr.gross_pay), 0),
                      COALESCE(SUM(pr.cpp_contribution), 0),
                      COALESCE(SUM(pr.qpip_contribution), 0),
                      COALESCE(SUM(pr.ei_contribution), 0),
                      COALESCE(SUM(pr.federal_tax), 0),
                      COALESCE(SUM(pr.provincial_tax), 0)
               FROM employees e
               JOIN payroll_runs pr ON pr.employee_id = e.id
               JOIN pay_periods pp ON pp.id = pr.period_id
               WHERE e.company_id = %s AND pp.payroll_year = %s
               GROUP BY e.id, e.first_name, e.last_name, e.code
               ORDER BY e.last_name, e.first_name''',
            (company_id, year)
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        slips = []
        for r in rows:
            gross = float(r[3])
            qpp = float(r[4])
            qpip = float(r[5])
            ei = float(r[6])
            fed_tax = float(r[7])
            qc_tax = float(r[8])
            pensionable = round(min(gross, ympe), 2)
            ei_insurable = round(min(gross, ei_max), 2)
            qpip_insurable = round(min(gross, qpip_max), 2)

            slips.append({
                'first_name': r[0],
                'last_name': r[1],
                'code': r[2],
                'gross': round(gross, 2),
                'qpp': round(qpp, 2),
                'qpip': round(qpip, 2),
                'ei': round(ei, 2),
                'federal_tax': round(fed_tax, 2),
                'quebec_tax': round(qc_tax, 2),
                # T4 (federal) boxes
                't4': {
                    'box10': 'QC',
                    'box14': round(gross, 2),        # Employment income
                    'box16': 0,                       # CPP (blank in Quebec)
                    'box17': round(qpp, 2),          # QPP contributions
                    'box18': round(ei, 2),           # EI premiums
                    'box22': round(fed_tax, 2),      # Income tax deducted (federal)
                    'box24': ei_insurable,            # EI insurable earnings
                    'box26': pensionable,             # CPP/QPP pensionable earnings
                    'box55': round(qpip, 2),         # PPIP (QPIP) premiums
                    'box56': qpip_insurable,          # PPIP insurable earnings
                },
                # RL-1 (Quebec) boxes
                'rl1': {
                    'boxA': round(gross, 2),         # Employment income
                    'boxB': round(qpp, 2),           # QPP contribution
                    'boxC': round(ei, 2),            # EI premium
                    'boxE': round(qc_tax, 2),        # Quebec income tax withheld
                    'boxG': pensionable,              # QPP pensionable salary
                    'boxH': round(qpip, 2),          # QPIP premium
                    'boxI': qpip_insurable,           # QPIP eligible wages
                },
            })

        return jsonify({'year': year, 'slips': slips}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== SAMY — AI ASSISTANT ====================

SAMY_SYSTEM_FR = (
    "Tu es NICO (Networked Intelligence & Core Operations), l'assistant IA d'ApexPayGo, un logiciel de paie pour le Québec (Canada). "
    "FORMAT: réponds en TEXTE BRUT seulement — jamais de Markdown (pas de #, pas de **, pas de listes à puces avec -). "
    "Pour une liste d'étapes, numérote-les simplement sur des lignes séparées (1. 2. 3.). Reste bref.\n\n"
    "VOICI LA STRUCTURE RÉELLE DE L'APPLICATION (ne décris que ceci, n'invente rien d'autre) :\n"
    "- Inscription (page Créer un compte) : nom complet, courriel, mot de passe.\n"
    "- Configuration de l'entreprise (après l'inscription) : type d'entreprise (Entreprise unique ou Multi-entreprises), "
    "nom de l'entreprise, adresse de l'entreprise, secteur d'activité (menu déroulant). Il n'y a PAS de numéro d'entreprise du Québec demandé.\n"
    "- Tableau de bord (page de compte) : renseignements de l'entreprise, renseignements du compte, statut de l'essai/abonnement, "
    "bouton \"Ouvrir le système de paie\".\n"
    "- Système de paie (4 onglets) :\n"
    "  1. Tableau de bord : statistiques (nb employés, brut cumulatif).\n"
    "  2. Employés : formulaire pour ajouter un employé (prénom, nom, code d'employé, courriel, date d'embauche, taux horaire $/heure), "
    "et la liste des employés (activer/désactiver).\n"
    "  3. Paie : choisir la date de fin de période, la date de paiement et la fréquence de paie (hebdomadaire/aux deux semaines/bimensuel/mensuel), "
    "puis entrer les heures par employé (régulier, férié, vacances, maternité, maladie, spécial, autre) et cliquer \"Calculer la paie\". "
    "Les résultats montrent le brut, le RRQ, le RQAP, l'AE, l'impôt fédéral, l'impôt du Québec, le net, et un sommaire des versements "
    "à remettre (ARC et Revenu Québec). On peut imprimer un talon de paie par employé.\n"
    "  4. Rapports : sommaire cumulatif annuel, et des feuillets de fin d'année T4/RL-1 générés par année d'imposition.\n"
    "- Facturation : abonnement mensuel (base + un montant par employé additionnel, le premier employé étant inclus).\n\n"
    "IMPORTANT : les calculs d'ApexPayGo sont des estimations basées sur les taux 2026; les montants "
    "officiels doivent être confirmés par un comptable avant toute production ou versement. Ne donne jamais "
    "de conseil juridique ou fiscal définitif, et n'invente pas de champs ou d'étapes qui n'existent pas dans l'application. "
    "Si une question sort du cadre de la paie ou du logiciel, ramène gentiment la conversation vers la paie."
)

SAMY_SYSTEM_EN = (
    "You are NICO (Networked Intelligence & Core Operations), the AI assistant for ApexPayGo, a payroll application for Quebec, Canada. "
    "FORMAT: reply in PLAIN TEXT only — never Markdown (no #, no **, no bullet dashes). "
    "For a list of steps, just number them on separate lines (1. 2. 3.). Keep it brief.\n\n"
    "HERE IS THE APP'S ACTUAL STRUCTURE (only describe this, never invent anything else):\n"
    "- Sign up (Create Account page): full name, email, password.\n"
    "- Company setup (right after signup): company type (Single Company or Multi-Company), company name, "
    "company address, industry (dropdown). There is NO Quebec business number field.\n"
    "- Account Dashboard: company info, account info, trial/subscription status, an \"Open Payroll System\" button.\n"
    "- Payroll System (4 tabs):\n"
    "  1. Dashboard: stats (employee count, YTD gross).\n"
    "  2. Employees: a form to add an employee (first name, last name, employee code, email, hire date, pay rate $/hour), "
    "and the employee list (activate/deactivate).\n"
    "  3. Payroll: pick the pay period end date, payment date, and pay frequency (weekly/bi-weekly/semi-monthly/monthly), "
    "then enter hours per employee (regular, holiday, vacation, maternity, SSL, special, other) and click \"Calculate Payroll\". "
    "Results show gross, QPP, QPIP, EI, federal tax, Quebec tax, net pay, and a remittance summary (what to send the CRA and "
    "Revenu Quebec). A pay stub can be printed per employee.\n"
    "  4. Reports: a year-to-date summary, and year-end T4/RL-1 slips generated per tax year.\n"
    "- Billing: a monthly subscription (a base fee + a per-additional-employee amount; the first employee is included free).\n\n"
    "IMPORTANT: ApexPayGo's calculations are estimates based on 2026 rates; official amounts must be confirmed by an "
    "accountant before any filing or remittance. Never give definitive legal or tax advice, and never invent fields or "
    "steps that don't exist in the app. If a question falls outside payroll or the software, gently steer the "
    "conversation back to payroll."
)

@app.route('/api/assistant', methods=['POST'])
def assistant():
    try:
        user_id = get_auth_user_id()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        if not os.getenv('ANTHROPIC_API_KEY'):
            return jsonify({'reply': "NICO n'est pas encore configuré. / NICO is not configured yet."}), 200

        data = request.json or {}
        lang = 'en' if data.get('lang') == 'en' else 'fr'
        raw = data.get('messages', [])

        # Sanitize + cap the conversation we forward (last 12 turns, 2000 chars each).
        convo = []
        for m in raw[-12:]:
            role = 'assistant' if m.get('role') == 'assistant' else 'user'
            content = str(m.get('content', ''))[:2000].strip()
            if content:
                convo.append({'role': role, 'content': content})
        if not convo:
            return jsonify({'error': 'No message provided'}), 400

        from anthropic import Anthropic
        client = Anthropic()  # reads ANTHROPIC_API_KEY
        resp = client.messages.create(
            model='claude-haiku-4-5',  # fast + cheap, ideal for a help widget
            max_tokens=1024,
            system=SAMY_SYSTEM_FR if lang == 'fr' else SAMY_SYSTEM_EN,
            messages=convo,
        )
        reply = ''.join(b.text for b in resp.content if getattr(b, 'type', None) == 'text')
        return jsonify({'reply': reply}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== STRIPE ====================

@app.route('/api/stripe-checkout', methods=['POST'])
def stripe_checkout():
    try:
        user_id = get_auth_user_id()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        if not (STRIPE_SECRET_KEY and STRIPE_PRICE_BASE and STRIPE_PRICE_EMPLOYEE):
            return jsonify({'error': 'Billing is not configured yet.'}), 503

        data = request.json or {}
        company_id = data.get('companyId')
        if not company_id:
            return jsonify({'error': 'Company ID required'}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        if not owns_company(cur, user_id, company_id):
            cur.close()
            conn.close()
            return jsonify({'error': 'Not authorized'}), 403

        # Bill $20 base (includes the first employee free) + $5 per additional active employee.
        cur.execute('SELECT COUNT(*) FROM employees WHERE company_id = %s AND active = true', (company_id,))
        emp_count = cur.fetchone()[0]
        billable_employees = max(0, emp_count - 1)

        cur.execute(
            '''SELECT c.stripe_customer_id, u.email
               FROM companies c JOIN users u ON u.id = c.user_id WHERE c.id = %s''',
            (company_id,)
        )
        row = cur.fetchone()
        customer_id = row[0] if row else None
        email = row[1] if row else None
        cur.close()
        conn.close()

        import stripe
        stripe.api_key = STRIPE_SECRET_KEY

        line_items = [{'price': STRIPE_PRICE_BASE, 'quantity': 1}]
        if billable_employees > 0:
            line_items.append({'price': STRIPE_PRICE_EMPLOYEE, 'quantity': billable_employees})

        params = {
            'mode': 'subscription',
            'line_items': line_items,
            'success_url': APP_URL + '/dashboard?billing=success',
            'cancel_url': APP_URL + '/dashboard?billing=cancel',
            'client_reference_id': company_id,
            'metadata': {'company_id': company_id},
            'subscription_data': {'metadata': {'company_id': company_id}},
            'allow_promotion_codes': True,
        }
        if customer_id:
            params['customer'] = customer_id
        elif email:
            params['customer_email'] = email

        session = stripe.checkout.Session.create(**params)
        return jsonify({'checkoutUrl': session.url}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stripe-webhook', methods=['POST'])
def stripe_webhook():
    # Stripe calls this directly (no user auth). Verify the signature instead.
    payload = request.get_data()
    sig = request.headers.get('Stripe-Signature', '')
    try:
        import stripe
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        # Temporary: surface the real reason in the response so it shows up
        # in Stripe's "Event deliveries" panel instead of a generic 400.
        secret_set = bool(STRIPE_WEBHOOK_SECRET)
        secret_len = len(STRIPE_WEBHOOK_SECRET) if STRIPE_WEBHOOK_SECRET else 0
        return jsonify({
            'error': 'Invalid signature',
            'detail': str(e),
            'webhook_secret_configured': secret_set,
            'webhook_secret_length': secret_len
        }), 400

    try:
        etype = event['type']
        obj = event['data']['object']
        conn = get_db_connection()
        cur = conn.cursor()

        if etype == 'checkout.session.completed':
            company_id = obj.get('client_reference_id') or (obj.get('metadata') or {}).get('company_id')
            if company_id:
                cur.execute(
                    '''UPDATE companies
                       SET stripe_customer_id = %s, stripe_subscription_id = %s,
                           subscription_status = 'active', updated_at = NOW()
                       WHERE id = %s''',
                    (obj.get('customer'), obj.get('subscription'), company_id)
                )
                conn.commit()

        elif etype in ('customer.subscription.updated', 'customer.subscription.deleted'):
            status = obj.get('status')
            mapped = 'active' if status in ('active', 'trialing') else (
                'canceled' if status in ('canceled', 'unpaid') else 'past_due')
            company_id = (obj.get('metadata') or {}).get('company_id')
            if company_id:
                cur.execute(
                    'UPDATE companies SET subscription_status = %s, updated_at = NOW() WHERE id = %s',
                    (mapped, company_id)
                )
            else:
                cur.execute(
                    'UPDATE companies SET subscription_status = %s, updated_at = NOW() WHERE stripe_subscription_id = %s',
                    (mapped, obj.get('id'))
                )
            conn.commit()

        cur.close()
        conn.close()
    except Exception:
        pass  # never fail the webhook back to Stripe on our own DB errors

    return jsonify({'received': True}), 200

# ==================== FRONTEND ====================

@app.route('/')
def index():
    return send_from_directory('Public', 'index.html')

@app.route('/signup')
def signup_page():
    return send_from_directory('Public', 'signup.html')

@app.route('/signin')
def signin_page():
    return send_from_directory('Public', 'signin.html')

@app.route('/setup')
def setup_page():
    return send_from_directory('Public', 'setup.html')

@app.route('/dashboard')
def dashboard_page():
    return send_from_directory('Public', 'dashboard.html')

@app.route('/payroll')
def payroll_page():
    return send_from_directory('Public', 'payroll.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('Public', filename)

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))

