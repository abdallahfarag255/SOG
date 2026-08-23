from werkzeug.security import check_password_hash


class AuthService:
    def __init__(self, user_repository):
        self._user_repository = user_repository

    def verify(self, username: str, password: str) -> bool:
        user = self._user_repository.get_by_username(username)
        if not user:
            return False
        return check_password_hash(user["password_hash"], password)
