from datetime import timedelta, datetime

from ..models import db

from ..auth.models import Role

class Admit(db.Model, Role):
    __bind_key__ = 'local'
    __tablename__ = 'admits'

    creation = db.Column(db.DateTime())
    dietary_restriction = db.Column(db.String(6))
    legal_waiver = db.Column(db.Boolean)
    photo_release = db.Column(db.Boolean)
    #travel
    #resume
    confirmed = db.Column(db.Boolean)

    @staticmethod
    def is_registrable():
        return False

    @staticmethod
    def role_name():
        return 'admit'

    @staticmethod
    def implied_roles():
        return ['attendee', 'hacker']

    def get_admit_data(self):
        data = {}

        data['dietary_restriction'] = self.dietary_restriction
        data['legal_waiver'] = self.legal_waiver
        data['photo_release'] = self.photo_release

        return data

    def get_deadline(self):
        return self.creation + timedelta(7)

    def update_admit_data(self, session, dietary_restriction, legal_waiver, photo_release):
        self.dietary_restriction = dietary_restriction
        self.legal_waiver = legal_waiver
        self.photo_release = photo_release

    def confirm_admit(self, session):
        self.confirmed = True

    def __init__(self, account_id):
        self.account_id = account_id
        self.creation = datetime.utcnow()
        self.confirmed = False
