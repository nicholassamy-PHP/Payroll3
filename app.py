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

app = Flask(__name__, static_folder='public', static_url_path='')
CORS(app)

DATABASE_URL = os.getenv('DATABASE_URL')

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

# ==================== AUTHENTICATION ====================

@app.route('/api/signup', methods=['POST'])
def signup():
    try:
        data = request.json
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
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
            conn.close()
            return jsonify({'error': 'Email already exists'}), 409
        finally:
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
        email = data.get('email', '').strip()
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
        cur.close()
        conn.close()

        if not user:
            return jsonify({'error': 'Invalid email or password'}), 401

        token = f"token_{datetime.now().timestamp()}"

        return jsonify({
            'token': token,
            'user': {'id': user[0], 'name': user[1], 'email': user[2]}
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

        company_id = str(uuid.uuid4())
        trial_start_date = datetime.now().strftime('%Y-%m-%d')

        conn = get_db_connection()
        cur = conn.cursor()

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
        finally:
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
                   SET company_name = %s, company_type = %s, company_address = %s, industry = %s
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
        cur.execute(
            'SELECT id, first_name, last_name, code, email, active, hire_date FROM employees WHERE company_id = %s ORDER BY last_name, first_name',
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
                'hire_date': emp[6].strftime('%Y-%m-%d') if emp[6] else None
            })

        return jsonify({'employees': result}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

        if not company_id or not first_name or not last_name or not code:
            return jsonify({'error': 'First name, last name, and code required'}), 400

        employee_id = str(uuid.uuid4())

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute(
                '''INSERT INTO employees (id, company_id, first_name, last_name, code, email, hire_date)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                (employee_id, company_id, first_name, last_name, code, email or None, hire_date or None)
            )
            conn.commit()

            cur.execute(
                'SELECT * FROM employees WHERE id = %s',
                (employee_id,)
            )
            emp = cur.fetchone()
            cur.close()
            conn.close()

            return jsonify({
                'success': True,
                'employee': {
                    'id': emp[0],
                    'first_name': emp[3],
                    'last_name': emp[4],
                    'code': emp[5],
                    'email': emp[6],
                    'active': emp[7],
                    'hire_date': emp[8].strftime('%Y-%m-%d') if emp[8] else None
                }
            }), 201
        except psycopg2.IntegrityError:
            conn.rollback()
            cur.close()
            conn.close()
            return jsonify({'error': 'Employee code already exists'}), 409

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/payroll-employees', methods=['PUT'])
def update_employee():
    try:
        data = request.json
        employee_id = data.get('employeeId')
        first_name = data.get('firstName', '').strip()
        last_name = data.get('lastName', '').strip()
        email = data.get('email', '')
        hire_date = data.get('hireDate')
        active = data.get('active', True)

        if not employee_id:
            return jsonify({'error': 'Employee ID required'}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            '''UPDATE employees
               SET first_name = %s, last_name = %s, email = %s, hire_date = %s, active = %s
               WHERE id = %s''',
            (first_name, last_name, email, hire_date, active, employee_id)
        )
        conn.commit()

        cur.execute('SELECT * FROM employees WHERE id = %s', (employee_id,))
        emp = cur.fetchone()
        cur.close()
        conn.close()

        if not emp:
            return jsonify({'error': 'Employee not found'}), 404

        return jsonify({
            'success': True,
            'employee': {
                'id': emp[0],
                'first_name': emp[3],
                'last_name': emp[4],
                'code': emp[5],
                'email': emp[6],
                'active': emp[7],
                'hire_date': emp[8].strftime('%Y-%m-%d') if emp[8] else None
            }
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== PAYROLL CALCULATION ====================

def calculate_taxes(gross_pay):
    cpp = max(0, min(gross_pay * 0.0595, 3867.50 * 0.0595))
    ei = gross_pay * 0.0163
    federal_basic = 15705
    provincial_basic = 16202

    federal_tax = max(0, (gross_pay - cpp - ei - federal_basic) * 0.15)
    provincial_tax = max(0, (gross_pay - cpp - ei - provincial_basic) * 0.2)

    return {
        'cpp': round(cpp * 100) / 100,
        'ei': round(ei * 100) / 100,
        'federalTax': round(federal_tax * 100) / 100,
        'provincialTax': round(provincial_tax * 100) / 100
    }

def calculate_gross_pay(hours):
    hourly_rate = 20
    regular_pay = (hours.get('regular_hours') or 0) * hourly_rate
    holiday_pay = (hours.get('holiday_paid_hours') or 0) * hourly_rate
    vacation_pay = (hours.get('vacation_paid_hours') or 0) * hourly_rate
    special_pay = (hours.get('special_hours') or 0) * hourly_rate
    maternity_pay = (hours.get('maternity_hours') or 0) * hourly_rate
    ssl_pay = (hours.get('ssl_hours') or 0) * hourly_rate
    other_amount = hours.get('other_amount') or 0

    return regular_pay + holiday_pay + vacation_pay + special_pay + maternity_pay + ssl_pay + other_amount

@app.route('/api/payroll-calculate', methods=['POST'])
def calculate_payroll():
    try:
        data = request.json
        company_id = data.get('companyId')
        period_id = data.get('periodId')
        hours_data = data.get('hoursData', {})

        if not company_id or not period_id or not hours_data:
            return jsonify({'error': 'Missing required fields'}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            'SELECT * FROM pay_periods WHERE id = %s AND company_id = %s',
            (period_id, company_id)
        )
        period = cur.fetchone()

        if not period:
            cur.close()
            conn.close()
            return jsonify({'error': 'Period not found'}), 404

        cur.execute(
            'SELECT * FROM employees WHERE company_id = %s AND active = true',
            (company_id,)
        )
        employees = cur.fetchall()

        payroll_runs = []

        for emp in employees:
            emp_id = emp[0]
            emp_hours = hours_data.get(emp_id, {})

            gross_pay = calculate_gross_pay(emp_hours)
            taxes = calculate_taxes(gross_pay)
            net_pay = gross_pay - taxes['cpp'] - taxes['ei'] - taxes['federalTax'] - taxes['provincialTax']

            cur.execute(
                '''SELECT COALESCE(SUM(gross_pay), 0) as ytd_gross, COALESCE(SUM(net_pay), 0) as ytd_net
                   FROM payroll_runs WHERE employee_id = %s
                   AND period_id IN (SELECT id FROM pay_periods WHERE company_id = %s AND payroll_year = %s AND pay_number < %s)''',
                (emp_id, company_id, period[4], period[3])
            )
            ytd_data = cur.fetchone()
            ytd_gross = ytd_data[0] if ytd_data else 0
            ytd_net = ytd_data[1] if ytd_data else 0

            run_id = str(uuid.uuid4())
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
                (run_id, period_id, emp_id, gross_pay, taxes['cpp'], taxes['ei'], taxes['federalTax'], taxes['provincialTax'], net_pay, ytd_gross + gross_pay, ytd_net + net_pay)
            )

            payroll_runs.append({
                'employee_id': emp_id,
                'gross_pay': gross_pay,
                'cpp': taxes['cpp'],
                'ei': taxes['ei'],
                'federal_tax': taxes['federalTax'],
                'provincial_tax': taxes['provincialTax'],
                'net_pay': net_pay,
                'ytd_gross': ytd_gross + gross_pay,
                'ytd_net': ytd_net + net_pay
            })

        cur.execute(
            'UPDATE pay_periods SET status = %s WHERE id = %s',
            ('completed', period_id)
        )

        conn.commit()
        cur.close()
        conn.close()

        totals = {
            'employees_paid': sum(1 for run in payroll_runs if run['gross_pay'] > 0),
            'gross_total': sum(run['gross_pay'] for run in payroll_runs),
            'net_total': sum(run['net_pay'] for run in payroll_runs),
            'cpp_total': sum(run['cpp'] for run in payroll_runs),
            'ei_total': sum(run['ei'] for run in payroll_runs),
            'tax_total': sum(run['federal_tax'] + run['provincial_tax'] for run in payroll_runs)
        }

        return jsonify({
            'success': True,
            'payrollRuns': payroll_runs,
            'totals': totals
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
    return send_from_directory('public', 'index.html')

@app.route('/signup')
def signup_page():
    return send_from_directory('public', 'signup.html')

@app.route('/signin')
def signin_page():
    return send_from_directory('public', 'signin.html')

@app.route('/setup')
def setup_page():
    return send_from_directory('public', 'setup.html')

@app.route('/dashboard')
def dashboard_page():
    return send_from_directory('public', 'dashboard.html')

@app.route('/payroll')
def payroll_page():
    return send_from_directory('public', 'payroll.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('public', filename)

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))

