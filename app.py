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

# Assumed number of pay periods per year (biweekly). Used to prorate the
# annual basic personal amounts so a single paycheque is taxed sensibly.
PAY_PERIODS_PER_YEAR = 26

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

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
                'ytd_cpp': float(emp[10]),
                'ytd_ei': float(emp[11]),
                'ytd_tax': float(emp[12])
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

def calculate_taxes(gross_pay):
    cpp = round(max(0.0, gross_pay * 0.0595), 2)
    ei = round(gross_pay * 0.0163, 2)

    federal_basic = 15705 / PAY_PERIODS_PER_YEAR
    provincial_basic = 16202 / PAY_PERIODS_PER_YEAR

    taxable = gross_pay - cpp - ei
    federal_tax = round(max(0.0, (taxable - federal_basic) * 0.15), 2)
    provincial_tax = round(max(0.0, (taxable - provincial_basic) * 0.20), 2)

    return {
        'cpp': cpp,
        'ei': ei,
        'federalTax': federal_tax,
        'provincialTax': provincial_tax
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
            'SELECT id, first_name, last_name, pay_rate FROM employees WHERE company_id = %s AND active = true',
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
            taxes = calculate_taxes(gross_pay)
            net_pay = round(gross_pay - taxes['cpp'] - taxes['ei'] - taxes['federalTax'] - taxes['provincialTax'], 2)

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

            cur.execute(
                '''INSERT INTO payroll_runs
                   (id, period_id, employee_id, gross_pay, cpp_contribution, ei_contribution, federal_tax, provincial_tax, net_pay, ytd_gross, ytd_net)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (period_id, employee_id) DO UPDATE SET
                     gross_pay = EXCLUDED.gross_pay,
                     cpp_contribution = EXCLUDED.cpp_contribution,
                     ei_contribution = EXCLUDED.ei_contribution,
                     federal_tax = EXCLUDED.federal_tax,
                     provincial_tax = EXCLUDED.provincial_tax,
                     net_pay = EXCLUDED.net_pay,
                     ytd_gross = EXCLUDED.ytd_gross,
                     ytd_net = EXCLUDED.ytd_net''',
                (str(uuid.uuid4()), period_id, emp_id, gross_pay, taxes['cpp'], taxes['ei'],
                 taxes['federalTax'], taxes['provincialTax'], net_pay, ytd_gross, ytd_net)
            )

            results.append({
                'employee_name': emp_name,
                'gross_pay': gross_pay,
                'cpp_contribution': taxes['cpp'],
                'ei_contribution': taxes['ei'],
                'federal_tax': taxes['federalTax'],
                'provincial_tax': taxes['provincialTax'],
                'net_pay': net_pay,
                'ytd_gross': ytd_gross,
                'ytd_net': ytd_net
            })

        conn.commit()
        cur.close()
        conn.close()

        totals = {
            'employees_paid': sum(1 for r in results if r['gross_pay'] > 0),
            'gross_total': round(sum(r['gross_pay'] for r in results), 2),
            'net_total': round(sum(r['net_pay'] for r in results), 2),
            'cpp_total': round(sum(r['cpp_contribution'] for r in results), 2),
            'ei_total': round(sum(r['ei_contribution'] for r in results), 2),
            'tax_total': round(sum(r['federal_tax'] + r['provincial_tax'] for r in results), 2)
        }

        return jsonify({
            'success': True,
            'payroll': results,
            'totals': totals,
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
