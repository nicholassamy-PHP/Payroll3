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

load_dotenv()

app = Flask(__name__, static_folder='Public', static_url_path='')
CORS(app)

DATABASE_URL = os.getenv('DATABASE_URL')

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

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
        'fss_rate': 0.0,                    # employer Health Services Fund - SET per company (Revenu Quebec assigns 1.25%-4.26%)
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

        password_hash = hashlib.sha256(password.encode()).hexdigest()
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

        password_hash = hashlib.sha256(password.encode()).hexdigest()

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            'SELECT id, name, email FROM users WHERE email = %s AND password_hash = %s',
            (email, password_hash)
        )
        user = cur.fetchone()

        company = None
        if user:
            cur.execute(
                '''SELECT id, company_name, company_type, company_address, industry, trial_start_date
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
                    'trial_start_date': comp[5].strftime('%Y-%m-%d') if comp[5] else None
                }

        cur.close()
        conn.close()

        if not user:
            return jsonify({'error': 'Invalid email or password'}), 401

        token = f"token_{datetime.now().timestamp()}"

        return jsonify({
            'token': token,
            'user': {'id': user[0], 'name': user[1], 'email': user[2]},
            'company': company
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== COMPANY SETUP ====================

@app.route('/api/setup', methods=['POST'])
def setup():
    try:
        data = request.json
        user_id = data.get('userId')
        company_name = data.get('companyName', '').strip()
        company_type = data.get('companyType', 'single')
        company_address = data.get('companyAddress', '').strip()
        industry = data.get('industry', '')

        if not user_id or not company_name:
            return jsonify({'error': 'Missing required fields'}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        # If this user already has a company, return it instead of creating a duplicate.
        cur.execute(
            '''SELECT id, company_name, company_type, company_address, industry, trial_start_date
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
                    'trial_start_date': existing[5].strftime('%Y-%m-%d') if existing[5] else None
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
                'trial_start_date': trial_start_date
            }
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/update-company', methods=['PUT'])
def update_company():
    try:
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

        try:
            cur.execute(
                '''UPDATE companies
                   SET company_name = %s, company_type = %s, company_address = %s, industry = %s, updated_at = NOW()
                   WHERE id = %s''',
                (company_name, company_type, company_address, industry, company_id)
            )
            conn.commit()

            cur.execute(
                'SELECT id, company_name, company_type, company_address, industry, trial_start_date FROM companies WHERE id = %s',
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
                    'trial_start_date': company[5].strftime('%Y-%m-%d') if company[5] else None
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
        company_id = request.args.get('companyId')

        if not company_id:
            return jsonify({'error': 'Company ID required'}), 400

        conn = get_db_connection()
        cur = conn.cursor()
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
        data = request.json
        employee_id = data.get('employeeId') or data.get('id')

        if not employee_id:
            return jsonify({'error': 'Employee ID required'}), 400

        conn = get_db_connection()
        cur = conn.cursor()

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

        payroll_year = int(str(pay_end_date)[:4])

        conn = get_db_connection()
        cur = conn.cursor()

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
        emp_qpp, emp_ei, emp_qpip, emp_fss = s('employer_qpp'), s('employer_ei'), s('employer_qpip'), s('employer_fss')
        fed_tax_total = round(sum(r['federal_tax'] for r in results), 2)
        qc_tax_total = round(sum(r['quebec_tax'] for r in results), 2)

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

# ==================== STRIPE ====================

@app.route('/api/stripe-checkout', methods=['POST'])
def stripe_checkout():
    try:
        data = request.json
        checkout_url = f"https://checkout.stripe.com/pay/test?client_secret=test_{datetime.now().timestamp()}"
        return jsonify({'checkoutUrl': checkout_url}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
