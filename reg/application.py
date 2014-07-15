from os import environ
from functools import wraps
from binascii import unhexlify

from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask.ext.login import LoginManager, login_required, login_user, current_user, logout_user
from flask_wtf.csrf import CsrfProtect
from flask_sslify import SSLify
from itsdangerous import URLSafeSerializer, BadSignature, URLSafeTimedSerializer, SignatureExpired
from sqlalchemy import func

from models import db, Account, Hacker, Team
from forms import LoginForm, RegistrationForm, LotteryForm, ResetForm, ForgotForm, ForgotResetForm
from errors import AuthenticationError
from emails import mail, send_account_confirmation_email, send_forgot_password_email, send_password_reset_email

MAX_TEAM_SIZE = 4

application = Flask(__name__, instance_relative_config=True)

# For AWS
app = application

try:
    configuration_module_name = environ['HACKMIT_FLASK_CONFIG_MODULE']
    app.config.from_object(configuration_module_name)
except KeyError:
    app.config.from_object('config.dev.DevelopmentConfig')

# Redirect all requests to HTTPS
sslify = SSLify(app, subdomains=True, permanent=True)

# Secure the app with CsrfProtect
csrf = CsrfProtect(app)

# All pages protected by CSRF, if validation fails, render csrf_error page
@csrf.error_handler
def csrf_error(reason):
    return render_template('csrf_error.html', reason=reason), 400

app.secret_key = app.config['SECRET_KEY'] # For Flask

db.init_app(app)
mail.init_app(app)

# Must be used in conjunction with the @login_required decorator.
def email_confirmed(function):
    @wraps(function)
    def wrapped_email_confirmed_function(**kwargs):
        account = Account.query.filter_by(id=current_user.id).first()
        if not account.email_confirmed():
            return render_template('server_message.html', header="You need to verify your email to get here!", subheader="You can resend the confirmation email from the dashboard.")
        else:
            return function(**kwargs)
    return wrapped_email_confirmed_function

# Must be used in conjunction with the @login_required and @email_confirmed decorators
def hackers_only(function):
    @wraps(function)
    def wrapped_hackers_only_function(*args, **kwargs):
        hacker = Hacker.query.filter_by(account_id=current_user.id).first()
        if not hacker:
            return render_template('server_message.html', header="You need to be a hacker to access this!", subheader="This ain't a UNIX file system.")
        else:
            return function(*args, **kwargs)
    return wrapped_hackers_only_function

# Must be used in conjunction with the @login_required, @email_confirmed, and @hackers_only decorators
def lottery_submitted(function):
    @wraps(function)
    def wrapped_lottery_submitted_function(*args, **kwargs):
        hacker = Hacker.query.filter_by(account_id=current_user.id).first()
        if not hacker.lottery_submitted():
            return render_template('server_message.html', header="You need to submit the lottery form to do that!", subheader="Hope you're feeling lucky.")
        else:
            return function(*args, **kwargs)
    return wrapped_lottery_submitted_function

# Register the error handler so it's not an internal server error
@app.errorhandler(AuthenticationError)
def handle_authentication_error(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response

login_manager = LoginManager()
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return Account.query.get(int(user_id))

@login_manager.unauthorized_handler
def unauthorized():
    return redirect(url_for('login'))

# TODO: move all static files to nginx and use uWSGI to hook into Flask

@app.errorhandler(404)
def not_found(error):
    return render_template('server_message.html', header="404", subheader="Whoa, you must be lost.")

@app.route('/')
def index():
    return render_template('index.html')

extra = app.config.get('EXTRA_URL')
if extra is not None:
    @app.route('/' + extra)
    def hex():
        try:
            template_name = unhexlify(extra)
            return render_template(template_name + '.html')
        except TypeError:
            pass

@app.route('/sponsor')
def sponsors():
    return app.send_static_file('assets/docs/HackMIT2014Sponsorship.pdf')

@app.route('/register')
def get_registration_page():
    if current_user.is_authenticated():
        return redirect(url_for('dashboard'))
    else:
        return render_template('register.html')

@app.route('/accounts', methods=['POST'])
def register_user():
    form = RegistrationForm()
    role = form.role.data
    email_address = form.email.data
    hashed_password = form.hashedPassword.data

    if not form.validate_on_submit():
        raise AuthenticationError('Your data is bad and you should feel bad.', status_code=403)

    if Account.query.filter(func.lower(Account.email_address) == func.lower(email_address)).first() != None:
        # Send back an error saying that this account already exists
        raise AuthenticationError('This account already exists!', status_code=420)

    new_account = Account(email_address, hashed_password)
    db.session.add(new_account)
    if role =="hacker": #TODO Move away from this hardcoded string and turn into a table lookup
        db.session.flush()
        new_hacker = Hacker(new_account.id)
        db.session.add(new_hacker)
    db.session.commit()

    s = URLSafeSerializer(app.config['SECRET_KEY'])
    confirm = s.dumps(new_account.id)

    send_account_confirmation_email(email_address, confirm=confirm)

    # Return a message of success
    return jsonify({'message': 'Successfully Registered!'})

@app.route('/account/resend')
@login_required
def resendEmail():
    if current_user.email_confirmed():
        render_template('server_message.html', header="You're already confirmed!", subheader="We do, however, appreciate your enthusiasm.")
    account_id = current_user.id
    s = URLSafeSerializer(app.config['SECRET_KEY'])
    confirm = s.dumps(account_id)
    email_address = current_user.email_address
    send_account_confirmation_email(email_address, confirm=confirm)
    return redirect(url_for('dashboard'))

@app.route('/accounts/<account_id>', methods=['PUT'])
@login_required
def update(account_id):

    form = ResetForm()
    email = form.email.data
    old_password = form.oldPassword.data
    new_password = form.newPassword.data

    account = Account.query.filter_by(id=account_id).first()

    if account.email_address != email:
        raise AuthenticationError("You email doesn't seem to match our records.")

    if not account.check_password(old_password):
        raise AuthenticationError("Your password is wrong!")

    if old_password == new_password:
        raise AuthenticationError("Your new password can't be the same as your old password!")

    account.update_password(new_password)
    db.session.commit()

    logout_user()

    return jsonify({"message": "Password successfully updated!"})

@app.route('/login')
def login():
    if current_user.is_authenticated():
        return redirect(url_for('dashboard'))
    else:
        return render_template('login.html')

@app.route('/sessions', methods=['POST'])
def sessions():
    form = LoginForm()

    if not form.validate_on_submit():
        raise AuthenticationError("Your data is bad and you should feel bad. What did you do?", status_code=403)

    email_address = form.email.data
    hashed_password = form.hashedPassword.data

    stored_account = Account.query.filter(func.lower(Account.email_address) == func.lower(email_address)).first()
    if stored_account == None:
        raise AuthenticationError("Sorry, it doesn't look like you have an account.", status_code=401)

    if not stored_account.check_password(hashed_password):
        raise AuthenticationError("Your username or password do not match.", status_code=402)
    login_user(stored_account)
    return jsonify({'url': url_for('dashboard')})

@app.route('/dashboard')
@login_required
def dashboard():
    email_confirmed = False # Email is confirmed, show lottery
    lottery_complete = False # Lottery is complete, also show teams
    account = load_user(current_user.id)
    hacker = None
    if account.email_confirmed():
        email_confirmed = True
        hacker = Hacker.query.filter_by(account_id=current_user.id).first()
        if hacker.lottery_submitted():
            lottery_complete = True

    return render_template('dashboard.html', hacker=hacker, email_confirmed=email_confirmed, lottery_complete=lottery_complete)

@app.route('/confirm')
def confirm():
    confirm = request.args.get('confirm')
    if confirm != None:
        s = URLSafeSerializer(app.config['SECRET_KEY'])
        try:
            confirm_user_id = s.loads(confirm)
            account = Account.query.get(int(confirm_user_id))
            if account is None:
                return render_template('server_message.html', header="You don't seem to have an account.", subheader="What are you waiting for? Go register!")
            account.confirm_email()
            db.session.commit()
            email_confirmed = True

            return redirect(url_for('login'))
        except BadSignature:
            pass

    return render_template('server_message.html', header="That's not a valid confirmation code!", subheader="Check for typos in the link, or login and resend the confirmation email.")

@app.route('/forgot', methods=['GET', 'POST'])
def forgot():
    if request.method == 'GET':
        token = request.args.get('token')
        if current_user.is_authenticated():
            return redirect(url_for('dashboard'))
        elif token != None:
            s = URLSafeTimedSerializer(app.config['SECRET_KEY'])
            try:
                confirm_user_id = s.loads(token, max_age=1800) # Max age of 30 minutes
                account = load_user(confirm_user_id)
                if account is None:
                    return render_template('server_message.html', header="You don't seem to have an account.", subheader="What are you waiting for? Go register!")
                return render_template('forgot_set_password.html', token=token)
            except SignatureExpired:
                return render_template('server_message.html', header="Oops. Your token has expired.", subheader="You should probably try again!")
            except BadSignature:
                return render_template('server_message.html', header="Oops. Your token is invalid.")
        else:
            return render_template('forgot.html')

    if request.method == 'POST':
        form = ForgotForm()
        email = form.email.data
        account = Account.query.filter(func.lower(Account.email_address) == func.lower(email)).first()
        if account != None:
            # Send an email to reset
            s = URLSafeTimedSerializer(app.config['SECRET_KEY'])
            token = s.dumps(account.id)

            send_forgot_password_email(email, token=token)

            return jsonify({"message": "Email sent! Check your email for a link to reset your password."})
        else:
            raise AuthenticationError("This account doesn't exist!", status_code=420)

@app.route('/accounts/reset', methods=['POST'])
def forgot_reset():
    token = request.args.get('token')
    if token is None:
        return render_template('server_message', header="You can't forgot the password for an account that doesn't exist!", subheader="Go register for a real account now!")
    form = ForgotResetForm()
    new_password = form.newPassword.data
    s = URLSafeTimedSerializer(app.config['SECRET_KEY'])
    try:
        confirm_user_id = s.loads(token, max_age=1800) # Max age of 30 minutes
        account = load_user(confirm_user_id)
        if account is None:
            return render_template('server_message.html', header="You don't seem to have an account.", subheader="What are you waiting for? Go register!")

        # In case the user hasn't already been confirmed.
        account.confirm_email()
        account.update_password(new_password)
        db.session.commit()

        # Notify the user that their password has been reset
        send_password_reset_email(account.email_address)

        return jsonify({"message": "You have successfully reset your password!"})

    except SignatureExpired:
        return render_template('server_message.html', header="Oops. Your token has expired.", subheader="You should probably try again!")

    except BadSignature:
        return render_template('server_message.html', header="Oops. Your token is invalid.")


@app.route('/lottery')
@login_required
@email_confirmed
@hackers_only
def lottery():
    hacker = Hacker.query.filter_by(account_id=current_user.id).first().get_hacker_details()
    return render_template('lottery.html', hacker=hacker)

@app.route('/team')
@login_required
@email_confirmed
@hackers_only
@lottery_submitted
def team():
    hacker = Hacker.query.filter_by(account_id=current_user.id).first()
    team_id = hacker.team_id
    team = None

    if team_id:
        team = {}
        teammateAccounts = [
            {
                "id": hacker.account_id,
                "name": hacker.name
            }
            for hacker in Hacker.query.filter_by(team_id=team_id).all()
        ]
        teammates = [
            {
                "name": account["name"],
                "email": Account.query.filter_by(id=account["id"]).first().email_address
            }
            for account in teammateAccounts
        ]
        team["teammates"] = teammates
        team["teamInviteCode"] = Team.query.filter_by(id=team_id).first().team_invite_code

    return render_template('team.html', team=team)

@app.route('/team/leave', methods=['POST'])
@login_required
@email_confirmed
@hackers_only
@lottery_submitted
def leave_team():
    hacker = Hacker.query.filter_by(account_id=current_user.id).first()
    hacker.team_id = None
    db.session.commit()
    return jsonify({"message": "It's been real, see ya!"})


@app.route('/teams', methods=['POST'])
@login_required
@email_confirmed
@hackers_only
@lottery_submitted
def teams():
    hacker = Hacker.query.filter_by(account_id=current_user.id).first()
    team = Team() # Create a new team
    db.session.add(team) # Add the team to the DB
    db.session.flush()
    hacker.team_id = team.id #Assign the hacker that team id

    db.session.commit()
    return jsonify({"message": "Team successfully created"})

@app.route('/teams/<team_invite_code>', methods=['POST'])
@login_required
@email_confirmed
@hackers_only
@lottery_submitted
def join_team(team_invite_code):

    # Find the team associated with the invite code
    team = Team.query.filter_by(team_invite_code=team_invite_code).first()

    if team is None:
        raise AuthenticationError("Aww. That doesn't seem to be a valid invite code.")

    members = Hacker.query.filter_by(team_id=team.id).all()

    if len(members) >= MAX_TEAM_SIZE:
        raise AuthenticationError("Aww. There are too many people on this team!")

    # Get the current hacker
    hacker = Hacker.query.filter_by(account_id=current_user.id).first()

    hacker.team_id = team.id
    db.session.commit()

    return jsonify({"message": "Hacking is better with friends!"})


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/reset')
@login_required
def reset():
    email = Account.query.filter_by(id=current_user.id).first().email_address
    return render_template('reset.html', email=email)

@app.route('/hackers', methods=['POST'])
@login_required
@email_confirmed
@hackers_only
def hackers():
    form = LotteryForm()
    # First find the hacker if they already exist
    if not form.validate_on_submit():
        # TODO make this nicer
        raise AuthenticationError("That's not valid data!")

    # TODO: invite_code validation and hookup
    if form.school_id.data != "166683" and form.adult.data is not True:
        raise AuthenticationError("Sorry, you need to be 18+ at the time of HackMIT to attend. Maybe next year?")

    shortened_invite_code = form.inviteCode.data[:8]
    previous_hacker_with_code = Hacker.query.filter_by(invite_code=shortened_invite_code).first()

    if form.inviteCode.data != "" and previous_hacker_with_code is not None and previous_hacker_with_code.account_id != current_user.id:
        raise AuthenticationError("Somebody beat you to it! That code has already been used. Try again or submit without a code to save your data.")

    hacker = Hacker.query.filter_by(account_id=current_user.id).first()
    hacker.update_lottery_info(form.name.data, form.gender.data, form.school_id.data, form.school.data, form.adult.data, form.location.data, shortened_invite_code, form.interests.data)

    db.session.commit()
    return jsonify({'message': "Successfully Updated!"})

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    port = app.config['PORT']
    if not port:
        port = 5000 # Default
    debug = app.config['DEBUG']
    if not debug:
        print 'NOT DEBUG'
    app.run(port=port, debug=debug)
