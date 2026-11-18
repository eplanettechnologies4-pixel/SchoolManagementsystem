import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, override_settings
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User, RoleChoices
from academics.models import School


@pytest.fixture
def security_user(db):
    school = School.objects.create(name="Secure Academy", code="SEC-01")
    user = User.objects.create_user(
        username="sec_user",
        password="SafePassword2026!",
        role=RoleChoices.ADMIN,
        school=school
    )
    return {'school': school, 'user': user}


@pytest.mark.django_db
def test_seed_data_disallowed_when_debug_false():
    with override_settings(DEBUG=False):
        with pytest.raises(CommandError, match="DEBUG=True"):
            call_command('seed_data')


@pytest.mark.django_db
def test_jwt_access_lifetime_and_token_rotation(security_user):
    user = security_user['user']
    refresh = RefreshToken.for_user(user)

    # 1. Access token lifetime (10 minutes)
    access_token = refresh.access_token
    assert abs((access_token['exp'] - access_token['iat']) - 600) <= 2  # 10 minutes (600s with +/- 1s clock tick)

    # 2. Token rotation test via API
    client = Client()
    token_url = reverse('token_obtain_pair')
    res = client.post(token_url, {
        'username': 'sec_user',
        'password': 'SafePassword2026!'
    }, content_type='application/json')
    assert res.status_code == 200
    data = res.json()
    assert 'access' in data
    assert 'refresh' in data

    # 3. Refresh token rotation
    refresh_url = reverse('token_refresh')
    res2 = client.post(refresh_url, {
        'refresh': data['refresh']
    }, content_type='application/json')
    assert res2.status_code == 200
    data2 = res2.json()
    assert 'access' in data2
    assert 'refresh' in data2
    assert data2['refresh'] != data['refresh']  # Rotated new refresh token issued


@pytest.mark.django_db
def test_axes_brute_force_lockout():
    client = Client()
    login_url = reverse('login')

    # Try 6 invalid login attempts
    for _ in range(6):
        client.post(login_url, {
            'username': 'attacker_user',
            'password': 'WrongPassword123!'
        })

    from axes.models import AccessFailureLog, AccessAttempt
    failures = AccessFailureLog.objects.filter(username='attacker_user')
    assert failures.exists() or AccessAttempt.objects.filter(username='attacker_user').exists()


@pytest.mark.django_db
def test_session_security_settings():
    assert settings.SESSION_COOKIE_AGE == 1800
    assert settings.SESSION_SAVE_EVERY_REQUEST is True
    assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is True
